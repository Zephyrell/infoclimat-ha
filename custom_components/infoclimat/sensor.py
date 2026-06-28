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
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN, SENSOR_TYPES

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Infoclimat sensors from a config entry."""
    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    sensors = []
    for sensor_key, sensor_config in SENSOR_TYPES.items():
        sensors.append(InfoclimatSensor(coordinator, entry, sensor_key, sensor_config))

    async_add_entities(sensors)


class InfoclimatSensor(CoordinatorEntity, SensorEntity):
    """Représente un capteur météo Infoclimat."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
        sensor_key: str,
        sensor_config: dict,
    ) -> None:
        """Initialisation."""
        super().__init__(coordinator)
        self._sensor_key = sensor_key
        self._sensor_config = sensor_config

        station_id = entry.data.get("station_id", "000FU")

        self._attr_unique_id = f"{DOMAIN}_{station_id}_{sensor_key}"
        self._attr_entity_registry_enabled_default = sensor_config["enabled"]

        # Device info
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, station_id)},
            name=f"Station Infoclimat {station_id}",
            manufacturer="Infoclimat",
            model="StatIC",
            configuration_url=(
                "https://www.infoclimat.fr/observations-meteo/temps-reel"
                f"/{station_id}.html"
            ),
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
        return SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> Any:
        """Valeur actuelle."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._sensor_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Attributs additionnels."""
        if self._sensor_key != "temperature" or self.coordinator.data is None:
            return None
        attrs = {}
        for key in ("temp_max_jour", "temp_min_jour"):
            if key in self.coordinator.data:
                attrs[key] = self.coordinator.data[key]
        # Add station metadata
        for key in ("station", "station_id", "date", "heure_locale", "heure_utc"):
            if key in self.coordinator.data:
                attrs[key] = self.coordinator.data[key]
        return attrs if attrs else None
