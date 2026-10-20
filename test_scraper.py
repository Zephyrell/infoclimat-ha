#!/usr/bin/env python3
"""Outil de diagnostic en ligne du parsing Infoclimat.

Télécharge la page d'une station et affiche le relevé extrait **ainsi que le
rapport de parsing** : quel tableau a servi, quelles colonnes ont été
reconnues, quelle ligne a été retenue, quels champs manquent. C'est la
première chose à regarder quand l'intégration Home Assistant remonte une
erreur.

    python3 test_scraper.py                    # station par défaut (000FU)
    python3 test_scraper.py 00001 00052        # plusieurs stations
    python3 test_scraper.py --html page.html   # une page déjà téléchargée
"""

from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent / "custom_components" / "infoclimat"))

from parsing import (  # noqa: E402
    InfoclimatParseError,
    decode_page,
    parse_station_page,
)

DEFAULT_STATION = "000FU"
BASE_URL = "https://www.infoclimat.fr/observations-meteo/temps-reel/{0}/{0}.html"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

#: (libellé, clé, unité) — l'ordre suit celui de la page.
SENSORS = (
    ("Température", "temperature", "°C"),
    ("Humidité", "humidite", "%"),
    ("Vent moyen", "vent_moyen", "km/h"),
    ("Rafale", "vent_rafale", "km/h"),
    ("Direction du vent", "vent_direction", "°"),
    ("Pluie (1h)", "pluie_1h", "mm"),
    ("Pluie instantanée", "pluie_instantannee", "mm/h"),
    ("Intensité max (1h)", "pluie_intensite_max_1h", "mm/h"),
    ("Pluie (3h)", "pluie_3h", "mm"),
    ("Pluie (6h)", "pluie_6h", "mm"),
    ("Pluie (12h)", "pluie_12h", "mm"),
    ("Pluie (24h)", "pluie_24h", "mm"),
    ("Point de rosée", "point_rosee", "°C"),
    ("Bio-météo", "bio_meteo", ""),
    ("Pression", "pression", "hPa"),
    ("Tendance", "pression_tendance", ""),
    ("Variation 3h", "pression_variation_3h", "hPa"),
)

CLIMATOLOGY = (
    ("Max du jour", "temp_max_jour", "°C"),
    ("Min du jour", "temp_min_jour", "°C"),
    ("Rafale max", "rafale_max_jour", "km/h"),
    ("Pluie max/1h", "pluie_max_1h", "mm/h"),
    ("Cumul du jour", "pluie_cumul_jour", "mm"),
    ("DJU chauffage", "dju_chauffe", ""),
    ("DJU froid", "dju_froid", ""),
)


def fetch_page(station_id: str) -> str:
    """Télécharge la page d'une station (le slug est résolu par redirection)."""
    url = BASE_URL.format(station_id)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=25) as response:
        # Même décodeur que l'intégration : un diagnostic qui décode
        # autrement masque les bugs de décodage au lieu de les montrer.
        return decode_page(response.read(),
                           response.headers.get_content_charset())


def report_station(station_id: str, html: str) -> bool:
    """Analyse une page et affiche le résultat. Retourne True si exploitable."""
    print(f"\n{'═' * 68}\n  Station {station_id}\n{'═' * 68}")

    try:
        observation = parse_station_page(html)
    except InfoclimatParseError as err:
        print(f"  ✗ {type(err).__name__}")
        print(f"    {err}")
        if type(err).__name__ == "AntiBotChallengeError":
            print(
                "    → Le site limite les requêtes automatiques. Espacer les\n"
                "      interrogations, puis réessayer."
            )
        return False

    data = observation.data

    print(f"  {data.get('station', '?')}  ({data.get('station_id', station_id)})")
    print(
        f"  Relevé du {data.get('date', '?')} à {data.get('heure_locale', '?')} "
        f"(UTC {data.get('heure_utc', '?')}, émis {data.get('obs_time_utc', '?')})"
    )

    print("\n  ── Observations ──")
    _print_fields(data, SENSORS)

    print("\n  ── Climatologie du jour ──")
    _print_fields(data, CLIMATOLOGY)

    print("\n  ── Rapport de parsing ──")
    for line in observation.report.details().splitlines()[1:]:
        print(f"  {line}")

    print("\n  ── JSON ──")
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    return True


def _print_fields(data: dict, fields: tuple) -> None:
    for label, key, unit in fields:
        value = data.get(key)
        if value is None:
            continue
        print(f"    {label:<18} {value} {unit}".rstrip())


def main(argv: list[str]) -> int:
    """Point d'entrée."""
    if argv[:1] == ["--html"]:
        path = pathlib.Path(argv[1])
        return 0 if report_station(path.stem, path.read_text(encoding="utf-8")) else 1

    stations = argv or [DEFAULT_STATION]
    failures = 0

    for station_id in stations:
        print(f"Téléchargement de {station_id}…", flush=True)
        try:
            html = fetch_page(station_id)
        except (urllib.error.URLError, TimeoutError) as err:
            print(f"  ✗ Réseau : {err}")
            failures += 1
            continue
        if not report_station(station_id, html):
            failures += 1

    if len(stations) > 1:
        print(f"\n{len(stations) - failures}/{len(stations)} station(s) exploitables.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
