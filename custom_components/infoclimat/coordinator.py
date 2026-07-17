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


def _build_column_map(headers_html: str) -> dict[str, int] | None:
    """Analyse la ligne d'en-tête et retourne un mapping nom→index.

    Reconnaît les colonnes par leur contenu textuel (strip_tags) afin
    d'être insensible à l'ordre et à la présence/absence de colonnes.
    Retourne None si les colonnes obligatoires (température) sont absentes.
    """
    headers = re.findall(r"<th[^>]*>(.*?)</th>", headers_html, re.DOTALL)
    col_map: dict[str, int] = {}

    for idx, html in enumerate(headers):
        txt = _strip_tags(html)

        if "ressentie" in txt.lower() or "bio" in txt.lower():
            col_map["bio_meteo"] = idx
        elif "tempé" in txt.lower() or "température" in txt.lower():
            col_map["temperature"] = idx
        elif txt.strip() == "Pluie":
            col_map["pluie_1h"] = idx
        elif txt.strip() == "Vent":
            col_map["vent"] = idx
        elif txt.strip() == "Humidité":
            col_map["humidite"] = idx
        elif "rosée" in txt.lower() or "pt." in txt.lower():
            col_map["point_rosee"] = idx
        elif "ressentie" in txt.lower() or "bio" in txt.lower():
            col_map["bio_meteo"] = idx
        elif txt.strip() == "Pression":
            col_map["pression"] = idx

    # Colonne obligatoire : température
    if "temperature" not in col_map:
        _LOGGER.error("Colonne 'Température' non trouvée dans les en-têtes")
        return None

    _LOGGER.debug("Colonnes détectées: %s", col_map)
    return col_map


def _parse_data_row_by_map(tds: list, col_map: dict[str, int], obs: dict):
    """Parse une ligne de données en utilisant le mapping colonne→index.

    N'extrait que les colonnes présentes dans col_map. Si une colonne
    est absente (pas dans col_map), le champ correspondant est ignoré
    (valeur None dans obs).
    """
    def _get(idx):
        return tds[idx][1] if idx < len(tds) else None

    # Température
    idx = col_map.get("temperature")
    if idx is not None:
        obs["temperature"] = _extract_number(tds[idx][1])

    # Pluie 1h (colonne optionnelle)
    idx = col_map.get("pluie_1h")
    if idx is not None:
        obs["pluie_1h"] = _extract_number(tds[idx][1])

    # Vent
    idx = col_map.get("vent")
    if idx is not None:
        _parse_wind(tds[idx][1], obs)

    # Humidité
    idx = col_map.get("humidite")
    if idx is not None:
        obs["humidite"] = _extract_number(tds[idx][1])

    # Bio-météo
    idx = col_map.get("bio_meteo")
    if idx is not None:
        obs["bio_meteo"] = _extract_number(tds[idx][1])

    # Point de rosée
    idx = col_map.get("point_rosee")
    if idx is not None:
        obs["point_rosee"] = _extract_number(tds[idx][1])

    # Pression
    idx = col_map.get("pression")
    if idx is not None:
        _parse_pressure(tds[idx][1], obs)


def _parse_time(td_html: str, obs: dict):
    """Extraction heure locale, UTC et date depuis la colonne heure."""
    m = re.search(r">(\d{1,2}h\d{2})</span>", td_html)
    if m:
        obs["heure_locale"] = m.group(1)
    m = re.search(r"(\d{2})h(\d{2})\s*UTC", td_html)
    if m:
        obs["heure_utc"] = f"{m.group(1)}:{m.group(2)}"
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", td_html)
    if m:
        obs["date"] = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"


def parse_observations(html_text: str) -> dict | None:
    """Parse la page Infoclimat et retourne les observations les plus récentes.

    Identifie les colonnes par leur en-tête (thead) plutôt que par leur
    position, ce qui rend le parsing immunisé contre les changements
    d'ordre ou d'index des colonnes.
    """
    # Extraction du tableau complet (thead + tbody)
    table = re.search(
        r"<table[^>]*id=\"resptable-releves\"[^>]*>"
        r".*?<thead>(.*?)</thead>"
        r".*?<tbody>(.*?)</tbody>",
        html_text,
        re.DOTALL,
    )
    if not table:
        _LOGGER.error("Table #resptable-releves non trouvée dans la page")
        return None

    # Construire le mapping colonne→index depuis les en-têtes
    col_map = _build_column_map(table.group(1))
    if not col_map:
        _LOGGER.error("Impossible de détecter les colonnes du tableau")
        return None

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(2), re.DOTALL)
    if not rows:
        _LOGGER.error("Aucune ligne trouvée dans le tbody")
        return None

    # Chercher la 1re ligne de données complète (≥ 7 colonnes).
    # Les lignes à 2 ou 4 colonnes sont des infos pluie supplémentaires.
    tds = None
    for row in rows:
        cells = re.findall(r"<(t[dh])[^>]*>(.*?)</\1>", row, re.DOTALL)
        if len(cells) >= 7:
            tds = cells
            break

    if not tds:
        _LOGGER.warning("Aucune ligne de données complète trouvée")
        return None

    obs: dict = {}

    # Heure locale (1re cellule, <th>)
    _parse_time(tds[0][1], obs)

    # Données via le mapping colonne→index
    _parse_data_row_by_map(tds, col_map, obs)

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
