# Infoclimat HA

Intégration Home Assistant pour récupérer les relevés météo en temps réel
des stations du réseau StatIC d'[Infoclimat](https://www.infoclimat.fr).

## Principe

Sans API, sans clé — l'intégration parse la page publique de la station
pour en extraire les données. Idéal pour les stations locales non
couvertes par la station synoptique Météo-France la plus proche.

## Capteurs

| Capteur | Device Class | Unité | Activé par défaut |
|---------|-------------|-------|-------------------|
| Température | `temperature` | °C | ✅ |
| Humidité | `humidity` | % | ✅ |
| Vent moyen | `wind_speed` | km/h | ✅ |
| Rafale de vent | — | km/h | ✅ |
| Direction du vent | — | ° | ✅ |
| Pluie (1h) | `precipitation` | mm/h | ✅ |
| Point de rosée | `temperature` | °C | ✅ |
| Bio-météo (ressentie) | — | — | ✅ |
| Pression | `pressure` | hPa | ✅ |
| Tendance pression | — | — | ✅ |
| Variation pression (3h) | `pressure` | hPa | 🔸 |
| Température max du jour | `temperature` | °C | 🔸 |
| Température min du jour | `temperature` | °C | 🔸 |
| Rafale max du jour | — | km/h | 🔸 |
| Pluie max/1h du jour | `precipitation` | mm/h | 🔸 |
| Pluie cumul jour | `precipitation` | mm | 🔸 |

🔸 = activable dans l'interface HA après installation

## Stations disponibles

| ID | Station | Département |
|----|---------|-------------|
| 000FU | Saint-Paul-Trois-Châteaux | Drôme (26) |

> Pour ajouter une station : fais une PR en ajoutant son ID et son slug
> dans le dictionnaire `STATION_SLUGS` du fichier `const.py`.

## Installation

### Via HACS (recommandé)

1. Dans HACS, va dans **Intégrations → ⋮ → Dépôts personnalisés**
2. Ajoute `https://github.com/<TON_PSEUDO>/infoclimat-ha` avec la catégorie **Intégration**
3. Clique sur **Télécharger** en bas à droite de la carte Infoclimat Scraper
4. **Redémarre** Home Assistant

### Installation manuelle

1. Copie le dossier `custom_components/infoclimat/` dans le dossier
   `/config/custom_components/` de ton Home Assistant
2. **Redémarre** Home Assistant

### Configuration

1. Va dans **Paramètres → Périphériques & Services → Ajouter une intégration**
2. Cherche **Infoclimat Scraper**
3. Sélectionne ta station dans la liste
4. Définis l'intervalle de mise à jour (5 à 60 min, 10 par défaut)
5. Les capteurs apparaissent automatiquement dans tes entités

## Architecture

```
custom_components/infoclimat/
├── __init__.py        # Point d'entrée de l'intégration
├── config_flow.py     # Écran de configuration dans l'UI HA
├── const.py           # Constantes et définition des capteurs
├── coordinator.py     # Polling HTTP + parsing HTML
├── sensor.py          # Entités capteurs Home Assistant
├── manifest.json      # Métadonnées
└── translations/      # Traductions (fr, en)
```

### Dépendances

**Aucune.** Uniquement la bibliothèque standard Python et les modules
embarqués dans Home Assistant (`aiohttp`, `voluptuous`).

## Licence

MIT
