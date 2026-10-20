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

# Page publique d'une station. Le premier segment d'URL est un « slug »
# lisible (« saint-paul-trois-chateaux ») ; Infoclimat redirige en 302 vers
# le bon slug quel que soit celui qu'on demande, on peut donc y placer
# l'identifiant de la station. Aucune table de correspondance à maintenir.
URL_PATTERN = (
    "https://www.infoclimat.fr/observations-meteo/temps-reel"
    "/{station_id}/{station_id}.html"
)

#: Au-delà de ce délai sans nouveau relevé, la station est signalée en retard.
STALE_AFTER_MINUTES = 90

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
        "unit": "mm",
        "icon": None,
        "enabled": True,
    },
    "pluie_instantannee": {
        "name": "Pluie instantanée",
        "device_class": "precipitation_intensity",
        "unit": UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        "icon": "mdi:weather-pouring",
        "enabled": True,
    },
    "pluie_intensite_max_1h": {
        "name": "Intensité max (1h)",
        "device_class": "precipitation_intensity",
        "unit": UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        "icon": "mdi:weather-pouring",
        "enabled": False,
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
        "device_class": "precipitation_intensity",
        "unit": UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        "icon": None,
        "enabled": False,
    },
    "pluie_cumul_jour": {
        "name": "Pluie cumul jour (6h–6h UTC)",
        "device_class": "precipitation",
        "unit": "mm",
        "icon": None,
        "enabled": False,
    },
    "pluie_3h": {
        "name": "Pluie cumul (3h)",
        "device_class": "precipitation",
        "unit": "mm",
        "icon": None,
        "enabled": False,
    },
    "pluie_6h": {
        "name": "Pluie cumul (6h)",
        "device_class": "precipitation",
        "unit": "mm",
        "icon": None,
        "enabled": False,
    },
    "pluie_12h": {
        "name": "Pluie cumul (12h)",
        "device_class": "precipitation",
        "unit": "mm",
        "icon": None,
        "enabled": False,
    },
    "pluie_24h": {
        "name": "Pluie cumul (24h)",
        "device_class": "precipitation",
        "unit": "mm",
        "icon": None,
        "enabled": False,
    },
    "dju_chauffe": {
        "name": "DJU chauffage",
        "device_class": None,
        "unit": None,
        "icon": "mdi:radiator",
        "enabled": False,
    },
    "dju_froid": {
        "name": "DJU froid",
        "device_class": None,
        "unit": None,
        "icon": "mdi:snowflake",
        "enabled": False,
    },
}
