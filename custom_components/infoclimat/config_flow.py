"""Config flow for Infoclimat integration."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STATION_ID,
    DOMAIN,
    URL_PATTERN,
)
from .coordinator import REQUEST_TIMEOUT, USER_AGENT
from .parsing import (
    AntiBotChallengeError,
    InfoclimatParseError,
    StationWithoutDataError,
    decode_page,
    parse_station_page,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_STATION_ID, default=DEFAULT_STATION_ID): str,
        vol.Required(
            CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
        ): vol.All(vol.Coerce(int), vol.Range(min=5, max=60)),
    }
)

#: Un identifiant StatIC : 5 caractères, lettres et chiffres (000FU, 00001…).
_STATION_ID_RE = re.compile(r"^[0-9A-Za-z]{5}$")
_URL_STATION_RE = re.compile(r"/temps-reel/[^/]+/([0-9A-Za-z]{5})\.html")


def normalize_station_id(raw: str) -> str:
    """Extrait l'identifiant d'une saisie libre.

    Accepte aussi bien ``000FU`` que l'URL complète de la page de la station,
    que les gens collent naturellement depuis leur navigateur.
    """
    value = (raw or "").strip()
    from_url = _URL_STATION_RE.search(value)
    if from_url:
        return from_url.group(1).upper()
    return value.upper()


async def validate_input(hass: HomeAssistant, station_id: str) -> str:
    """Vérifie que la station existe et publie des relevés.

    :returns: le nom de la station, tel qu'affiché par Infoclimat.
    :raises StationWithoutDataError: station muette ou identifiant inconnu.
    :raises aiohttp.ClientError: site injoignable.
    """
    session = async_get_clientsession(hass)
    url = URL_PATTERN.format(station_id=station_id)

    async with asyncio.timeout(REQUEST_TIMEOUT):
        response = await session.get(url, headers={"User-Agent": USER_AGENT})
        async with response:
            response.raise_for_status()
            html = decode_page(await response.read(), response.charset)

    observation = await hass.async_add_executor_job(parse_station_page, html)
    data = observation.data
    return data.get("station") or station_id


class InfoclimatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Infoclimat."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            station_id = normalize_station_id(user_input[CONF_STATION_ID])
            user_input[CONF_STATION_ID] = station_id

            if not _STATION_ID_RE.match(station_id):
                errors["base"] = "invalid_station_id"
            else:
                await self.async_set_unique_id(station_id)
                self._abort_if_unique_id_configured()

                try:
                    station_name = await validate_input(self.hass, station_id)
                except AntiBotChallengeError:
                    errors["base"] = "rate_limited"
                except StationWithoutDataError:
                    errors["base"] = "station_without_data"
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    errors["base"] = "cannot_connect"
                except InfoclimatParseError:
                    errors["base"] = "cannot_parse"
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.exception("Erreur inattendue à la configuration")
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(
                        title=station_name, data=user_input
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )
