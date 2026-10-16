"""Coordinateur Infoclimat : récupération HTTP, parsing délégué.

Ce module ne contient **aucune** règle de parsing HTML. Il télécharge la
page, la passe à :mod:`custom_components.infoclimat.parsing`, traduit les
erreurs de parsing en erreurs Home Assistant, et journalise le rapport de
chaque cycle. Toute la connaissance du site vit dans le paquet ``parsing``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    STALE_AFTER_MINUTES,
    URL_PATTERN,
)
from .parsing import (
    AntiBotChallengeError,
    EmptyObservationError,
    InfoclimatParseError,
    ObservationTableNotFoundError,
    StationWithoutDataError,
    decode_page,
    parse_station_page,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

#: Quand le site sert sa page anti-robot, il ne sert à rien d'insister : on
#: espace les requêtes avant de réessayer. C'est la cause du blocage (une
#: cadence trop soutenue) qu'on traite, pas seulement son symptôme.
ANTIBOT_BACKOFF = timedelta(minutes=30)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

#: Chaque cause d'échec a son message, pour que le journal de Home Assistant
#: dise *pourquoi* la station est muette, et pas seulement qu'elle l'est.
_ERROR_MESSAGES: tuple[tuple[type[BaseException], str], ...] = (
    # AntiBotChallengeError est traité à part : il déclenche un ralentissement.
    (
        StationWithoutDataError,
        "La station {station} ne publie aucune donnée temps réel"
        " ({raison})",
    ),
    (
        ObservationTableNotFoundError,
        "Le tableau des relevés est introuvable pour la station {station} "
        "(le site a probablement changé de structure).",
    ),
    (
        EmptyObservationError,
        "Le tableau de la station {station} a été trouvé mais aucun relevé "
        "exploitable n'a pu en être extrait.",
    ),
)


class InfoclimatCoordinator(DataUpdateCoordinator):
    """Interroge la page publique d'une station Infoclimat."""

    def __init__(
        self,
        hass: HomeAssistant,
        station_id: str,
        scan_interval: int,
    ) -> None:
        """Initialisation."""
        self._station_id = station_id
        self._url = URL_PATTERN.format(station_id=station_id)
        self._stale_after = timedelta(minutes=STALE_AFTER_MINUTES)
        self._configured_interval = timedelta(minutes=scan_interval)
        self._throttled = False

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}-{station_id}",
            update_interval=timedelta(minutes=scan_interval),
        )

    @property
    def station_id(self) -> str:
        """Identifiant de la station suivie."""
        return self._station_id

    @property
    def station_url(self) -> str:
        """URL publique de la station."""
        return self._url

    async def _async_update_data(self) -> dict[str, Any]:
        """Télécharge la page puis la passe au moteur de parsing."""
        html = await self._async_fetch()

        try:
            observation = await self.hass.async_add_executor_job(
                parse_station_page, html
            )
        except AntiBotChallengeError as err:
            self._throttle()
            raise UpdateFailed(
                f"Infoclimat a détecté des requêtes automatisées pour la "
                f"station {self._station_id} et a renvoyé sa page anti-robot. "
                f"Nouvel essai dans {_format_age(self.update_interval)} "
                f"(augmentez l'intervalle de mise à jour si cela se reproduit)."
            ) from err
        except InfoclimatParseError as err:
            raise UpdateFailed(self._explain(err)) from err

        self._resume()

        report = observation.report
        if report.warnings:
            _LOGGER.warning(
                "Infoclimat %s : relevé lu avec des réserves (%s)",
                self._station_id,
                " | ".join(report.warnings),
            )
        _LOGGER.debug(
            "Infoclimat %s : %s", self._station_id, report.details()
        )

        data = observation.data
        data["station_id"] = self._station_id
        data["station_url"] = self._url
        self._check_freshness(data)

        _LOGGER.debug("Infoclimat %s : %s", self._station_id, report.summary())
        return data

    async def _async_fetch(self) -> str:
        """Récupère le HTML de la page de la station.

        Le slug de l'URL est arbitraire : le site redirige en 302 vers le bon.
        """
        session = async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                response = await session.get(
                    self._url, headers={"User-Agent": USER_AGENT}
                )
                async with response:
                    response.raise_for_status()
                    # `response.text()` decode en strict et lève sur la
                    # page d'Infoclimat, qui annonce utf-8 sans l'être.
                    return decode_page(await response.read(), response.charset)
        except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeError) as err:
            raise UpdateFailed(
                f"Page Infoclimat injoignable pour la station "
                f"{self._station_id} : {err}"
            ) from err

    def _throttle(self) -> None:
        """Espace les requêtes après un blocage anti-robot."""
        if self._throttled:
            return
        self._throttled = True
        self.update_interval = max(self._configured_interval, ANTIBOT_BACKOFF)
        _LOGGER.warning(
            "Infoclimat %s : requêtes automatisées bloquées, intervalle porté "
            "de %s à %s",
            self._station_id,
            _format_age(self._configured_interval),
            _format_age(self.update_interval),
        )

    def _resume(self) -> None:
        """Rétablit la cadence configurée dès qu'un relevé passe."""
        if not self._throttled:
            return
        self._throttled = False
        self.update_interval = self._configured_interval
        _LOGGER.info(
            "Infoclimat %s : blocage anti-robot levé, retour à un intervalle "
            "de %s",
            self._station_id,
            _format_age(self._configured_interval),
        )

    def _explain(self, err: InfoclimatParseError) -> str:
        """Traduit une erreur de parsing en message lisible."""
        raison = "station fermée, hors-ligne ou identifiant inconnu"
        if isinstance(err, StationWithoutDataError) and err.last_report:
            raison = f"dernier relevé publié le {err.last_report}"

        for error_type, template in _ERROR_MESSAGES:
            if isinstance(err, error_type):
                return template.format(station=self._station_id, raison=raison)
        return f"Parsing impossible pour la station {self._station_id} : {err}"

    def _check_freshness(self, data: dict[str, Any]) -> None:
        """Signale une station qui n'a rien publié depuis longtemps.

        On ne fait pas échouer le cycle : un capteur figé mais daté reste
        plus utile qu'une entité « indisponible », l'horodatage étant exposé
        en attribut.
        """
        raw = data.get("obs_time_utc")
        if not raw:
            _LOGGER.warning(
                "Infoclimat %s : relevé sans horodatage d'émission",
                self._station_id,
            )
            return

        try:
            observed = datetime.fromisoformat(raw)
        except ValueError:
            return
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)

        age = datetime.now(timezone.utc) - observed
        data["age_releve_minutes"] = int(age.total_seconds() // 60)
        if age > self._stale_after:
            _LOGGER.warning(
                "Infoclimat %s : dernier relevé il y a %s (station en retard)",
                self._station_id,
                _format_age(age),
            )


def _format_age(age: timedelta) -> str:
    """Âge d'un relevé, en français lisible."""
    minutes = int(age.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h"
    return f"{hours // 24} j"
