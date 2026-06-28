"""Constants for the Infoclimat integration."""

from __future__ import annotations

from homeassistant.const import (
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfVolumetricFlux,
    PERCENTAGE,
)

DOMAIN = "infoclimat"
DEFAULT_NAME = "Infoclimat"
DEFAULT_STATION_ID = "000FU"
DEFAULT_SCAN_INTERVAL = 10  # minutes
CONF_STATION_ID = "station_id"
CONF_SCAN_INTERVAL = "scan_interval"

# Base URL for scraping
URL_PATTERN = (
    "https://www.infoclimat.fr/observations-meteo/temps-reel"
    "/{station_slug}/{station_id}.html"
)

STATION_SLUGS = {
    "000FU": "saint-paul-trois-chateaux",
    # Future stations can be added here
}

# Sensor definitions: (key, name, device_class, unit, icon, enabled_by_default)
SENSOR_TYPES = {
    "temperature": {
        "name": "Température",
        "device_class": "temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "icon": None,
        "enabled": True,
    },
    "humidite": {
        "name": "Humidité",
        "device_class": "humidity",
        "unit": PERCENTAGE,
        "icon": None,
        "enabled": True,
    },
    "vent_moyen": {
        "name": "Vent moyen",
        "device_class": "wind_speed",
        "unit": UnitOfSpeed.KILOMETERS_PER_HOUR,
        "icon": None,
        "enabled": True,
    },
    "vent_rafale": {
        "name": "Rafale de vent",
        "device_class": None,
        "unit": UnitOfSpeed.KILOMETERS_PER_HOUR,
        "icon": "mdi:weather-windy",
        "enabled": True,
    },
    "vent_direction": {
        "name": "Direction du vent",
        "device_class": None,
        "unit": "°",
        "icon": "mdi:compass",
        "enabled": True,
    },
    "pluie_1h": {
        "name": "Pluie (1h)",
        "device_class": "precipitation",
        "unit": UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        "icon": None,
        "enabled": True,
    },
    "point_rosee": {
        "name": "Point de rosée",
        "device_class": "temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "icon": None,
        "enabled": True,
    },
    "bio_meteo": {
        "name": "Bio-météo (ressentie)",
        "device_class": None,
        "unit": None,
        "icon": "mdi:thermometer",
        "enabled": True,
    },
    "pression": {
        "name": "Pression",
        "device_class": "pressure",
        "unit": UnitOfPressure.HPA,
        "icon": None,
        "enabled": True,
    },
    "pression_tendance": {
        "name": "Tendance pression",
        "device_class": None,
        "unit": None,
        "icon": "mdi:trending-up",
        "enabled": True,
    },
    "pression_variation_3h": {
        "name": "Variation pression (3h)",
        "device_class": "pressure",
        "unit": UnitOfPressure.HPA,
        "icon": None,
        "enabled": False,
    },
    "temp_max_jour": {
        "name": "Température max du jour",
        "device_class": "temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "icon": None,
        "enabled": False,
    },
    "temp_min_jour": {
        "name": "Température min du jour",
        "device_class": "temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "icon": None,
        "enabled": False,
    },
    "rafale_max_jour": {
        "name": "Rafale max du jour",
        "device_class": None,
        "unit": UnitOfSpeed.KILOMETERS_PER_HOUR,
        "icon": "mdi:weather-windy",
        "enabled": False,
    },
    "pluie_max_1h": {
        "name": "Pluie max/1h du jour",
        "device_class": "precipitation",
        "unit": UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        "icon": None,
        "enabled": False,
    },
    "pluie_cumul_jour": {
        "name": "Pluie cumul jour",
        "device_class": "precipitation",
        "unit": "mm",
        "icon": None,
        "enabled": False,
    },
}
