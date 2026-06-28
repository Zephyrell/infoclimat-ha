"""Coordinator for Infoclimat data fetching."""

from __future__ import annotations

import asyncio
import logging
import re
import html as html_mod
from datetime import timedelta

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, URL_PATTERN, STATION_SLUGS

_LOGGER = logging.getLogger(__name__)


def _strip_tags(s: str) -> str:
    """Supprime les balises HTML et décode les entités."""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_mod.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_number(s: str) -> float | None:
    """Extrait le premier nombre flottant d'une chaîne."""
    nums = re.findall(r"[-+]?\d+\.?\d*", _strip_tags(s))
    return float(nums[0]) if nums else None


def _parse_wind(wind_html: str, obs: dict):
    """Extraction vent: vitesse moyenne, rafale, direction."""
    txt = _strip_tags(wind_html)
    obs["vent_moyen"] = _extract_number(wind_html)
    m = re.search(r"raf\s*[.:]?\s*([\d.]+)", txt)
    if m:
        obs["vent_rafale"] = float(m.group(1))
    m = re.search(r'title="Vent de direction\s*([\d.]+)[°&]', wind_html)
    if m:
        obs["vent_direction"] = float(m.group(1))


def _parse_pressure(press_html: str, obs: dict):
    """Extraction pression et tendance."""
    obs["pression"] = _extract_number(press_html)
    if "up.png" in press_html or "montee" in press_html:
        obs["pression_tendance"] = "hausse"
    elif "down.png" in press_html or "baisse" in press_html:
        obs["pression_tendance"] = "baisse"
    else:
        obs["pression_tendance"] = "stable"
    m = re.search(r'title="([+-]?[\d.]+)\s*hPa', press_html)
    if m:
        obs["pression_variation_3h"] = float(m.group(1))


def _parse_climato(text: str, obs: dict):
    """Extraction données climatologie du jour."""
    pairs = [
        ("temp_max_jour", r"Température maximale.*?<b>([\d.]+)</b>°C"),
        ("temp_min_jour", r"Température minimale.*?<b>([\d.]+)</b>°C"),
        ("rafale_max_jour", r"Rafale maximale.*?<b>([\d.]+)</b>\s*km/h"),
        ("pluie_max_1h", r"Cumul maxi en 1h.*?<b>([\d.]+)</b>\s*mm"),
        ("pluie_cumul_jour", r"Cumul du jour.*?<b>([\d.]+)</b>\s*mm"),
    ]
    for key, pattern in pairs:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            obs[key] = float(m.group(1))

    m = re.search(r"(\d+)\s*chauffe", text)
    if m:
        obs["dju_chauffe"] = int(m.group(1))
    m = re.search(r"(\d+)\s*froid", text)
    if m:
        obs["dju_froid"] = int(m.group(1))


def parse_observations(html_text: str) -> dict | None:
    """Parse la page Infoclimat et retourne les observations les plus récentes."""
    table = re.search(
        r'<table[^>]*id="resptable-releves"[^>]*>.*?<tbody>(.*?)</tbody>',
        html_text,
        re.DOTALL,
    )
    if not table:
        _LOGGER.error("Table #resptable-releves non trouvée dans la page")
        return None

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(1), re.DOTALL)
    if not rows:
        _LOGGER.error("Aucune ligne trouvée dans le tableau")
        return None

    # Première ligne = données les plus récentes
    tds = re.findall(r"<(t[dh])[^>]*>(.*?)</\1>", rows[0], re.DOTALL)
    if len(tds) < 8:
        _LOGGER.warning("Nombre de colonnes inattendu: %d (attendu: ≥8)", len(tds))
        return None

    obs: dict = {}

    # Heure locale
    m = re.search(r">(\d{1,2}h\d{2})</span>", tds[0][1])
    if m:
        obs["heure_locale"] = m.group(1)
    m = re.search(r"(\d{2})h(\d{2})\s*UTC", tds[0][1])
    if m:
        obs["heure_utc"] = f"{m.group(1)}:{m.group(2)}"
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", tds[0][1])
    if m:
        obs["date"] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

    # Colonnes de données
    obs["temperature"] = _extract_number(tds[1][1])
    r = _strip_tags(tds[2][1])
    rn = _extract_number(tds[2][1])
    if r and rn is not None:
        obs["pluie_1h"] = rn
    _parse_wind(tds[3][1], obs)
    obs["humidite"] = _extract_number(tds[4][1])
    obs["bio_meteo"] = _extract_number(tds[5][1])
    obs["point_rosee"] = _extract_number(tds[6][1])
    _parse_pressure(tds[7][1], obs)

    # Nom station
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.DOTALL)
    if m:
        obs["station"] = _strip_tags(m.group(1))

    # Climatologie du jour
    clim = re.search(
        r'<table[^>]*class="recap-clim-resp"[^>]*>(.*?)</table>',
        html_text,
        re.DOTALL,
    )
    if clim:
        _parse_climato(clim.group(1), obs)

    return obs


class InfoclimatCoordinator(DataUpdateCoordinator):
    """Coordinateur pour récupérer les données Infoclimat."""

    def __init__(
        self,
        hass: HomeAssistant,
        station_id: str,
        scan_interval: int,
    ) -> None:
        """Initialisation."""
        slug = STATION_SLUGS.get(station_id, station_id)
        self._url = URL_PATTERN.format(station_slug=slug, station_id=station_id)
        self._station_id = station_id

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}-{station_id}",
            update_interval=timedelta(minutes=scan_interval),
        )

    async def _async_update_data(self) -> dict:
        """Fetch latest data from Infoclimat."""
        session = async_get_clientsession(self.hass)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        }

        try:
            async with asyncio.timeout(15):
                resp = await session.get(self._url, headers=headers)
                resp.raise_for_status()
                html_text = await resp.text()

        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Erreur HTTP lors de la récupération: {err}") from err

        data = await self.hass.async_add_executor_job(parse_observations, html_text)
        if data is None:
            raise UpdateFailed("Impossible de parser les données Infoclimat")

        data["station_id"] = self._station_id
        return data
