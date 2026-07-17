#!/usr/bin/env python3
"""
Script de test pour scraper les données météo d'Infoclimat
Station: Saint-Paul-Trois-Châteaux (000FU)
"""

import re
import json
import html
from datetime import datetime
from urllib.request import urlopen, Request

URL = "https://www.infoclimat.fr/observations-meteo/temps-reel/saint-paul-trois-chateaux/000FU.html"


# ──── Helpers ────

def strip_tags(s: str) -> str:
    """Supprime les balises HTML et décode les entités HTML."""
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def extract_number(s: str) -> float | None:
    """Extrait le premier nombre d'une chaîne HTML."""
    nums = re.findall(r'[-+]?\d+\.?\d*', strip_tags(s))
    return float(nums[0]) if nums else None


# ──── Parsing ────

def _parse_wind(wind_html: str, obs: dict):
    """Extract wind speed, gust, direction."""
    txt = strip_tags(wind_html)
    # Wind speed (first number)
    obs["vent_moyen"] = extract_number(wind_html)
    # Gust after "raf."
    ref_match = re.search(r'raf\s*[.:]?\s*([\d.]+)', txt)
    if ref_match:
        obs["vent_rafale"] = float(ref_match.group(1))
    # Direction from title attribute
    dir_match = re.search(r'title="Vent de direction\s*([\d.]+)[°&]', wind_html)
    if dir_match:
        obs["vent_direction"] = float(dir_match.group(1))


def _parse_pressure(press_html: str, obs: dict):
    """Extract pressure and trend."""
    obs["pression"] = extract_number(press_html)
    if 'up.png' in press_html or 'montee' in press_html:
        obs["pression_tendance"] = "hausse"
    elif 'down.png' in press_html or 'baisse' in press_html:
        obs["pression_tendance"] = "baisse"
    else:
        obs["pression_tendance"] = "stable"
    # Variation 3h
    var_match = re.search(r'title="([+-]?[\d.]+)\s*hPa', press_html)
    if var_match:
        obs["pression_variation_3h"] = float(var_match.group(1))


def _parse_climato(html_text: str, obs: dict):
    """Extraire les données de la climatologie du jour."""
    clim = re.search(
        r'<table[^>]*class="recap-clim-resp"[^>]*>(.*?)</table>',
        html_text, re.DOTALL,
    )
    if not clim:
        return
    text = clim.group(1)

    # Température maximale
    m = re.search(r'Température maximale.*?<b>([\d.]+)</b>°C', text, re.DOTALL)
    if m:
        obs["temp_max_jour"] = float(m.group(1))

    # Température minimale
    m = re.search(r'Température minimale.*?<b>([\d.]+)</b>°C', text, re.DOTALL)
    if m:
        obs["temp_min_jour"] = float(m.group(1))

    # Rafale maximale
    m = re.search(r'Rafale maximale.*?<b>([\d.]+)</b>\s*km/h', text, re.DOTALL)
    if m:
        obs["rafale_max_jour"] = float(m.group(1))

    # Cumul pluie maxi 1h
    m = re.search(r'Cumul maxi en 1h.*?<b>([\d.]+)</b>\s*mm', text, re.DOTALL)
    if m:
        obs["pluie_max_1h"] = float(m.group(1))

    # Cumul pluie du jour
    m = re.search(r'Cumul du jour.*?<b>([\d.]+)</b>\s*mm', text, re.DOTALL)
    if m:
        obs["pluie_cumul_jour"] = float(m.group(1))

    # DJU
    m = re.search(r'(\d+)\s*chauffe', text)
    if m:
        obs["dju_chauffe"] = int(m.group(1))
    m = re.search(r'(\d+)\s*froid', text)
    if m:
        obs["dju_froid"] = int(m.group(1))


def _build_column_map(thead_html: str) -> dict[str, int] | None:
    """Analyse les en-têtes et retourne un mapping nom→index de colonne."""
    headers = re.findall(r'<th[^>]*>(.*?)</th>', thead_html, re.DOTALL)
    col_map: dict[str, int] = {}

    for idx, html in enumerate(headers):
        txt = strip_tags(html)

        if 'ressentie' in txt.lower() or 'bio' in txt.lower():
            col_map['bio_meteo'] = idx
        elif 'tempé' in txt.lower() or 'température' in txt.lower():
            col_map['temperature'] = idx
        elif txt.strip() == 'Pluie':
            col_map['pluie_1h'] = idx
        elif txt.strip() == 'Vent':
            col_map['vent'] = idx
        elif txt.strip() == 'Humidité':
            col_map['humidite'] = idx
        elif 'rosée' in txt.lower() or 'pt.' in txt.lower():
            col_map['point_rosee'] = idx
        elif txt.strip() == 'Pression':
            col_map['pression'] = idx

    if 'temperature' not in col_map:
        print("ERREUR: colonne Température non trouvée")
        return None

    print(f"Mapping colonnes: {col_map}")
    return col_map


def _parse_data_row_by_map(tds: list, col_map: dict[str, int], obs: dict):
    """Parse une ligne via le mapping colonne→index."""
    # Température
    idx = col_map.get('temperature')
    if idx is not None:
        obs['temperature'] = extract_number(tds[idx][1])

    # Pluie 1h (optionnelle)
    idx = col_map.get('pluie_1h')
    if idx is not None:
        obs['pluie_1h'] = extract_number(tds[idx][1])

    # Vent
    idx = col_map.get('vent')
    if idx is not None:
        _parse_wind(tds[idx][1], obs)

    # Humidité
    idx = col_map.get('humidite')
    if idx is not None:
        obs['humidite'] = extract_number(tds[idx][1])

    # Bio-météo
    idx = col_map.get('bio_meteo')
    if idx is not None:
        obs['bio_meteo'] = extract_number(tds[idx][1])

    # Point de rosée
    idx = col_map.get('point_rosee')
    if idx is not None:
        obs['point_rosee'] = extract_number(tds[idx][1])

    # Pression
    idx = col_map.get('pression')
    if idx is not None:
        _parse_pressure(tds[idx][1], obs)


def parse_observations(html_text: str) -> dict | None:
    """Parse la table HTML #resptable-releves en identifiant les colonnes
    par leur en-tête (thead) plutôt que par leur position.

    Immunisé contre les changements d'ordre/d'index.
    """
    # 1. Extraire le tableau complet (thead + tbody) pour éviter les <table> imbriqués
    m = re.search(
        r'<table[^>]*id="resptable-releves"[^>]*>'
        r'.*?<thead>(.*?)</thead>'
        r'.*?<tbody>(.*?)</tbody>',
        html_text, re.DOTALL,
    )
    if not m:
        print("ERREUR: table #resptable-releves non trouvée")
        return None

    # 2. Construire le mapping colonne→index depuis les en-têtes
    col_map = _build_column_map(m.group(1))
    if not col_map:
        return None

    tbody = m.group(2)

    # 3. Trouver toutes les lignes <tr>
    trs = re.findall(r'<tr[^>]*>(.*?)</tr>', tbody, re.DOTALL)
    if not trs:
        print("ERREUR: aucune ligne dans le tableau")
        return None

    # 4. Chercher la 1re ligne de données complète (≥ 7 colonnes)
    tds = None
    for tr in trs:
        cells = re.findall(r'<(t[dh])[^>]*>(.*?)</\1>', tr, re.DOTALL)
        if len(cells) >= 7:
            tds = cells
            break

    if not tds:
        print("ATTENTION: aucune ligne de données complète trouvée")
        return None

    obs = {}

    # --- Heure locale ---
    time_span = re.search(r'>(\d{1,2}h\d{2})</span>', tds[0][1])
    if time_span:
        obs['heure_locale'] = time_span.group(1)
    utc_match = re.search(r'(\d{2})h(\d{2})\s*UTC', tds[0][1])
    if utc_match:
        obs['heure_utc'] = f"{utc_match.group(1)}:{utc_match.group(2)}"
    date_match = re.search(r'(\d{2})/(\d{2})/(\d{4})', tds[0][1])
    if date_match:
        obs['date'] = f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"

    # Données via le mapping colonne→index
    _parse_data_row_by_map(tds, col_map, obs)

    # --- Informations station ---
    h1 = re.search(r'<h1[^>]*>(.*?)</h1>', html_text, re.DOTALL)
    if h1:
        obs['station'] = strip_tags(h1.group(1))

    obs['station_id'] = '000FU'

    # --- Climatologie du jour ---
    _parse_climato(html_text, obs)

    return obs


def fetch_page(url: str) -> str:
    """Télécharge la page HTML."""
    req = Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
    })
    with urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")


# ──── Main ────

if __name__ == "__main__":
    print("🔍 Téléchargement de la page Infoclimat...")
    html_page = fetch_page(URL)
    print(f"✓ Page téléchargée ({len(html_page):,} octets)")

    print("\n📊 Parsing des observations...")
    data = parse_observations(html_page)

    if data:
        print(f"\n✅ Station: {data.get('station', '?')} ({data.get('station_id', '?')})")
        print(f"   Relevé du: {data.get('date', '?')} à {data.get('heure_locale', '?')} (UTC: {data.get('heure_utc', '?')})")
        print()
        print("── Capteurs ──")
        fields = [
            ("🌡️  Température", "temperature", "°C"),
            ("💧 Humidité", "humidite", "%"),
            ("💨 Vent moyen", "vent_moyen", "km/h"),
            ("🌬️  Rafale", "vent_rafale", "km/h"),
            ("🧭 Direction vent", "vent_direction", "°"),
            ("🌧️  Pluie 1h", "pluie_1h", "mm"),
            ("🌡️  Point de rosée", "point_rosee", "°C"),
            ("🔥 Bio-météo", "bio_meteo", ""),
            ("🔽 Pression", "pression", "hPa"),
            ("📈 Tendance pression", "pression_tendance", ""),
            ("📊 Variation 3h", "pression_variation_3h", "hPa"),
        ]
        for label, key, unit in fields:
            if key in data and data[key] is not None:
                print(f"   {label}: {data[key]} {unit}".strip())

        print()
        print("── Climatologie du jour ──")
        clim_fields = [
            ("🌡️  Max du jour", "temp_max_jour", "°C"),
            ("🌡️  Min du jour", "temp_min_jour", "°C"),
            ("💨 Rafale max", "rafale_max_jour", "km/h"),
            ("🌧️  Pluie max/1h", "pluie_max_1h", "mm"),
            ("🌧️  Cumul jour", "pluie_cumul_jour", "mm"),
            ("🔥 DJU chauffe", "dju_chauffe", ""),
            ("❄️  DJU froid", "dju_froid", ""),
        ]
        for label, key, unit in clim_fields:
            if key in data and data[key] is not None:
                print(f"   {label}: {data[key]} {unit}".strip())

        print(f"\n📦 JSON complet:")
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print("❌ Échec du parsing")
