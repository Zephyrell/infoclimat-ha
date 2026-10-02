"""Sensor platform for Infoclimat."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SENSOR_TYPES
from .coordinator import InfoclimatCoordinator

_LOGGER = logging.getLogger(__name__)

#: Capteurs dont l'état est un texte : pas de statistiques à en tirer.
_TEXT_SENSORS = frozenset({"pression_tendance"})

#: Métadonnées recopiées sur chaque capteur : de quoi juger la fraîcheur et
#: l'origine de la mesure sans ouvrir le journal.
_METADATA_KEYS = (
    "station",
    "station_id",
    "station_status",
    "station_last_report",
    "obs_time_utc",
    "age_releve_minutes",
    "station_url",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Infoclimat sensors from a config entry."""
    coordinator: InfoclimatCoordinator = hass.data[DOMAIN][entry.entry_id]

    sensors = []
    for sensor_key, sensor_config in SENSOR_TYPES.items():
        sensors.append(InfoclimatSensor(coordinator, entry, sensor_key, sensor_config))

    async_add_entities(sensors)


class InfoclimatSensor(CoordinatorEntity, SensorEntity):
    """Représente un capteur météo Infoclimat."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: InfoclimatCoordinator,
        entry: ConfigEntry,
        sensor_key: str,
        sensor_config: dict,
    ) -> None:
        """Initialisation."""
        super().__init__(coordinator)
        self._sensor_key = sensor_key
        self._sensor_config = sensor_config

        station_id = coordinator.station_id
        # Le premier rafraîchissement a déjà eu lieu : le nom de la station
        # est connu, on peut l'utiliser comme nom d'appareil.
        station_name = (coordinator.data or {}).get("station") or station_id

        self._attr_unique_id = f"{DOMAIN}_{station_id}_{sensor_key}"
        self._attr_entity_registry_enabled_default = sensor_config["enabled"]

        # Device info
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, station_id)},
            name=station_name,
            manufacturer="Infoclimat",
            model="StatIC",
            configuration_url=coordinator.station_url,
        )

    @property
    def name(self) -> str:
        """Nom lisible du capteur."""
        return self._sensor_config["name"]

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Device class."""
        dc = self._sensor_config.get("device_class")
        return SensorDeviceClass(dc) if dc else None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Unité de mesure."""
        return self._sensor_config.get("unit")

    @property
    def icon(self) -> str | None:
        """Icône."""
        return self._sensor_config.get("icon")

    @property
    def state_class(self) -> SensorStateClass | None:
        """State class."""
        if self._sensor_key in _TEXT_SENSORS:
            return None
        return SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> Any:
        """Valeur actuelle."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._sensor_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Attributs additionnels.

        L'horodatage du relevé et son âge sont exposés partout : un scraper
        peut servir une mesure figée sans que l'état change, et une
        automatisation doit pouvoir s'en rendre compte.
        """
        data = self.coordinator.data
        if data is None:
            return None

        attrs: dict[str, Any] = {}
        for key in _METADATA_KEYS:
            if key in data:
                attrs[key] = data[key]

        # Extrêmes du jour, regroupés sur le capteur de température
        if self._sensor_key == "temperature":
            for key in (
                "temp_max_jour",
                "temp_min_jour",
                "date",
                "heure_locale",
                "heure_utc",
            ):
                if key in data:
                    attrs[key] = data[key]

        return attrs or None
