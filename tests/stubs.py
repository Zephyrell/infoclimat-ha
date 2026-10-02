"""Bouchons minimalistes pour tester la couche Home Assistant hors de HA.

Le coordinateur ne dépend de Home Assistant que par quelques symboles :
`DataUpdateCoordinator`, `UpdateFailed`, la session aiohttp et les classes
d'unités de `homeassistant.const`. On installe ces bouchons dans
`sys.modules` avant d'importer le module, ce qui permet de tester sa
logique — traduction des erreurs, ralentissement, fraîcheur — sans
installer Home Assistant.
"""

from __future__ import annotations

import sys
import types


class UpdateFailed(Exception):
    """Équivalent de `homeassistant.helpers.update_coordinator.UpdateFailed`."""


class DataUpdateCoordinator:
    """Équivalent minimal, sans le planificateur de Home Assistant."""

    def __init__(self, hass, logger, *, name=None, update_interval=None) -> None:
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None
        self.last_update_success = True


class _Units:
    """Porte les constantes d'unité, qui ne sont que des chaînes."""

    def __init__(self, **values: str) -> None:
        self.__dict__.update(values)


def _module(name: str, **attributes) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def install() -> None:
    """Installe les bouchons dans `sys.modules`. Idempotent."""
    if "homeassistant" in sys.modules:
        return

    definitions = [
        ("aiohttp", {"ClientError": OSError}),
        ("homeassistant", {}),
        ("homeassistant.core", {"HomeAssistant": object}),
        ("homeassistant.config_entries", {"ConfigEntry": object}),
        (
            "homeassistant.const",
            {
                "Platform": _Units(SENSOR="sensor"),
                "UnitOfPressure": _Units(HPA="hPa"),
                "UnitOfSpeed": _Units(KILOMETERS_PER_HOUR="km/h"),
                "UnitOfTemperature": _Units(CELSIUS="°C"),
                "UnitOfVolumetricFlux": _Units(MILLIMETERS_PER_HOUR="mm/h"),
                "PERCENTAGE": "%",
            },
        ),
        ("homeassistant.helpers", {}),
        (
            "homeassistant.helpers.aiohttp_client",
            {"async_get_clientsession": lambda hass: getattr(hass, "session", None)},
        ),
        (
            "homeassistant.helpers.update_coordinator",
            {
                "DataUpdateCoordinator": DataUpdateCoordinator,
                "UpdateFailed": UpdateFailed,
            },
        ),
    ]

    for name, attributes in definitions:
        module = sys.modules.get(name) or _module(name, **attributes)
        sys.modules[name] = module
        parent_name, _, child = name.rpartition(".")
        if parent_name in sys.modules:
            setattr(sys.modules[parent_name], child, module)
