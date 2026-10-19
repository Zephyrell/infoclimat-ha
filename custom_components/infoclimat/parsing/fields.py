"""Extracteurs de champs : une cellule → un ou plusieurs capteurs.

Chaque extracteur est une fonction pure ``cellule → dict``. Pour ajouter un
capteur, il suffit d'enregistrer une fonction avec :func:`extractor` et de
déclarer le rôle correspondant dans :mod:`parsing.columns`. Aucun autre
fichier n'a besoin d'être modifié.

Les extracteurs travaillent sur le **texte** du nœud et parcourent l'arbre
pour les attributs, jamais sur du HTML brut : un ``title="<table>…"`` ne
peut donc pas les tromper.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from .dom import Node, parse_html
from .tables import row_cells

__all__ = [
    "EXTRACTORS",
    "extractor",
    "extract_role",
    "numbers_in",
    "first_number",
    "parse_observation_time",
    "ObservationTime",
    "parse_rain_tooltip",
    "parse_rain_amount",
    "parse_rain_rate",
    "TIME_ROLE",
]

TIME_ROLE = "heure"

#: Nombre au format « 12 », « -0.4 », « 1,2 ». Le signe n'est capté que s'il
#: est collé au chiffre, pour ne pas transformer « 6h à 6h » en « -6 ».
_NUMBER_RE = re.compile(r"(?<![\d.,])[-+]?\d+(?:[.,]\d+)?(?![\d])")
_HOURS_RE = re.compile(r"(\d+)\s*h")
_WIND_DIRECTION_RE = re.compile(r"Vent de direction\s*([\d.]+)")
_RAIN_GUST_RE = re.compile(r"raf\.?\s*([-+]?\d+(?:[.,]\d+)?)")
_HPA_VARIATION_RE = re.compile(r"([-+]?\d+(?:[.,]\d+)?)\s*hPa")
#: Cumul sur l'intervalle de la ligne : « 0.4 mm/10mn », « 1.8 mm/1h ».
#: Le multiplicateur est obligatoire, sinon « 2.6mm/h » serait capté aussi.
_RAIN_AMOUNT_RE = re.compile(
    r"([-+]?\d+(?:[.,]\d+)?)\s*mm\s*/\s*(\d+)\s*(mn|min|h)", re.IGNORECASE
)
#: Intensité déjà calculée par le site : « 2.6mm/h ».
_RAIN_RATE_RE = re.compile(r"([-+]?\d+(?:[.,]\d+)?)\s*mm\s*/\s*h", re.IGNORECASE)

#: Rôle → fonction d'extraction.
EXTRACTORS: dict[str, Callable[[Node], dict[str, Any]]] = {}


def extractor(role: str):
    """Enregistre une fonction d'extraction pour un rôle de colonne."""

    def decorate(func: Callable[[Node], dict[str, Any]]):
        EXTRACTORS[role] = func
        return func

    return decorate


def numbers_in(text: str) -> list[float]:
    """Tous les nombres d'un texte, dans l'ordre."""
    return [float(m.group(0).replace(",", ".")) for m in _NUMBER_RE.finditer(text)]


def first_number(text: str) -> float | None:
    """Premier nombre d'un texte, ou ``None``."""
    values = numbers_in(text)
    return values[0] if values else None


def _cell_value(cell: Node) -> float | None:
    """Valeur numérique d'une cellule simple (vide → ``None``)."""
    text = cell.text()
    return first_number(text) if text else None


# ─────────────────────── Colonnes à valeur simple ───────────────────────


@extractor("temperature")
def _temperature(cell: Node) -> dict[str, Any]:
    return {"temperature": _cell_value(cell)}


@extractor("humidite")
def _humidity(cell: Node) -> dict[str, Any]:
    return {"humidite": _cell_value(cell)}


@extractor("bio_meteo")
def _bio_weather(cell: Node) -> dict[str, Any]:
    # Colonne sans unité (windchill / humidex). Peut aussi porter l'indice UV
    # et le rayonnement solaire sur les stations équipées.
    return {"bio_meteo": _cell_value(cell)}


@extractor("point_rosee")
def _dew_point(cell: Node) -> dict[str, Any]:
    return {"point_rosee": _cell_value(cell)}


@extractor("neige")
def _snow(cell: Node) -> dict[str, Any]:
    return {"hauteur_neige": _cell_value(cell)}


# ───────────────────────────── Vent ─────────────────────────────


@extractor("vent")
def _wind(cell: Node) -> dict[str, Any]:
    """Vent moyen, rafale et direction.

    Cellule type : ``0 km/h | raf.9.7`` + un ``<div title="Vent de direction 12°">``.
    """
    text = cell.text()
    result: dict[str, Any] = {"vent_moyen": None, "vent_rafale": None, "vent_direction": None}

    if text and not text.lstrip().lower().startswith("raf"):
        result["vent_moyen"] = first_number(text)

    gust = _RAIN_GUST_RE.search(text)
    if gust:
        result["vent_rafale"] = float(gust.group(1).replace(",", "."))

    for node in cell.iter():
        direction = _WIND_DIRECTION_RE.search(node.get("title") or "")
        if direction:
            result["vent_direction"] = float(direction.group(1))
            break

    return result


# ──────────────────────────── Pression ────────────────────────────


@extractor("pression")
def _pressure(cell: Node) -> dict[str, Any]:
    """Pression, tendance et variation sur 3 h.

    La tendance vient de l'image ``up.png``/``down.png`` (alt *montee*/*baisse*) ;
    un simple ``=`` dans la cellule signale une pression stable.
    """
    result: dict[str, Any] = {
        "pression": _cell_value(cell),
        "pression_tendance": None,
        "pression_variation_3h": None,
    }

    for image in cell.find_all("img"):
        alt = (image.get("alt") or "").strip().lower()
        src = (image.get("src") or "").lower()
        if alt == "montee" or "up" in src:
            result["pression_tendance"] = "hausse"
        elif alt == "baisse" or "down" in src:
            result["pression_tendance"] = "baisse"

        variation = _HPA_VARIATION_RE.search(image.get("title") or "")
        if variation:
            result["pression_variation_3h"] = float(variation.group(1).replace(",", "."))

    if result["pression_variation_3h"] is not None and result["pression_tendance"] is None:
        value = result["pression_variation_3h"]
        result["pression_tendance"] = "hausse" if value > 0 else "baisse" if value < 0 else "stable"

    if result["pression_tendance"] is None and "=" in cell.text():
        result["pression_tendance"] = "stable"

    return result


# ───────────────────────────── Pluie ─────────────────────────────


def parse_rain_tooltip(title_html: str) -> dict[str, float]:
    """Cumuls pluviométriques cachés dans l'infobulle de la cellule Pluie.

    Le ``title`` contient un mini-tableau HTML (jusqu'à quatre cumuls) :

        <table><tr><td>Pluie/3h :</td><td>0mm</td></tr>…</table>

    C'est ce fragment qui faisait dérailler les parsers à base de regex.
    """
    result: dict[str, float] = {}
    for row in parse_html(title_html).find_all("tr"):
        cells = row_cells(row)
        if len(cells) < 2:
            continue
        hours = _HOURS_RE.search(cells[0].text())
        if not hours:
            continue
        value = first_number(cells[1].text())
        if value is not None:
            result.setdefault(f"pluie_{int(hours.group(1))}h", value)
    return result


def parse_rain_amount(text: str) -> tuple[float | None, int | None]:
    """Cumul de pluie de la cellule et intervalle, en minutes.

    Lit « 0.4 mm/10mn » → ``(0.4, 10)`` et « 1.8 mm/1h » → ``(1.8, 60)``.
    """
    match = _RAIN_AMOUNT_RE.search(text)
    if match is None:
        return None, None
    amount = float(match.group(1).replace(",", "."))
    count = int(match.group(2))
    minutes = count * 60 if match.group(3).lower() == "h" else count
    return amount, minutes


def parse_rain_rate(text: str) -> float | None:
    """Débit déjà exprimé en mm/h par le site : « 2.6mm/h » → ``2.6``."""
    match = _RAIN_RATE_RE.search(text)
    return float(match.group(1).replace(",", ".")) if match else None


@extractor("pluie_1h")
def _rain(cell: Node) -> dict[str, Any]:
    """Intensité de pluie (mm/h), plus les cumuls 3/6/12/24 h.

    La cellule mêle **deux mesures** :

        0.4 <span>mm/10mn</span> … 2.6 <span>mm/h</span>

    La première est un cumul dont l'unité change d'une ligne à l'autre — par
    10 minutes sur les relevés déciminutés, par heure sur les lignes horaires.
    La prendre telle quelle pour un capteur en mm/h surestime la pluie d'un
    facteur 6. La seconde est le débit calculé par le site, et c'est lui que
    porte le capteur « Pluie (1h) ».

    Quand le débit n'est pas affiché, on le reconstitue à partir du cumul et
    de l'intervalle ; à défaut, on reprend le « Pluie/1h » de l'infobulle.
    Les deux formes de la cellule sont conservées : le cumul et son intervalle
    deviennent des attributs, rien n'est perdu.
    """
    text = cell.text()
    tooltip: dict[str, float] = {}
    for link in cell.find_all("a"):
        title = link.get("title") or ""
        if "minitable" in title or "Pluie/" in title:
            tooltip = parse_rain_tooltip(title)
            break

    rate = parse_rain_rate(text)
    amount, minutes = parse_rain_amount(text)

    result: dict[str, Any] = {}
    if rate is not None:
        result["pluie_1h"] = rate
    elif "pluie_1h" in tooltip:
        result["pluie_1h"] = tooltip["pluie_1h"]
    elif amount is not None and minutes:
        # Repli : un cumul sur 10 min vaut six fois plus en débit horaire.
        result["pluie_1h"] = round(amount * 60 / minutes, 2)
    else:
        result["pluie_1h"] = None

    if amount is not None:
        result["pluie_cumul_intervalle"] = amount
        result["pluie_intervalle_min"] = minutes

    for key, value in tooltip.items():
        if key != "pluie_1h":
            result[key] = value
    return result


# ─────────────────────── Horodatage d'un relevé ───────────────────────


@dataclass(frozen=True)
class ObservationTime:
    """Horodatage d'une ligne de relevé.

    ``moment`` est la clé de tri (naïve) ; ``moment_utc`` n'est renseigné que
    lorsque la page a fourni l'heure d'émission réelle, et porte alors le
    fuseau UTC — c'est lui qui sert à juger de la fraîcheur d'un relevé.
    """

    local: str | None = None
    utc: str | None = None
    date: str | None = None
    moment: datetime | None = None
    moment_utc: datetime | None = None

    @property
    def is_complete(self) -> bool:
        """Un horodatage exploitable pour trier les lignes."""
        return self.moment is not None


def parse_observation_time(cell: Node) -> ObservationTime:
    """Extrait l'heure locale, l'heure UTC et la date de la colonne Heure.

    L'heure d'émission est dans un attribut ``title`` du type :
    ``Heure réelle d'émission :<br />02/10/2026<br /><b>09h30 UTC</b>``.
    """
    local = cell.text() or None
    raw_title = ""

    for node in cell.iter():
        title = node.get("title") or ""
        if "mission" in title or "UTC" in title:
            raw_title = title
            break

    title_text = parse_html(raw_title).text() if raw_title else ""

    utc = None
    date = None
    match = re.search(r"(\d{1,2})h(\d{2})\s*UTC", title_text)
    if match:
        utc = f"{int(match.group(1)):02d}:{match.group(2)}"

    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", title_text)
    if match:
        date = f"{match.group(3)}-{match.group(2)}-{match.group(1)}"

    moment = _build_moment(date, utc) or _build_moment(date, _local_to_hhmm(local))
    moment_utc = _build_moment(date, utc, tz=timezone.utc) if utc else None
    return ObservationTime(
        local=local, utc=utc, date=date, moment=moment, moment_utc=moment_utc
    )


def _local_to_hhmm(local: str | None) -> str | None:
    if not local:
        return None
    match = re.search(r"(\d{1,2})\s*h\s*(\d{2})", local)
    if not match:
        return None
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _build_moment(
    date: str | None, time: str | None, tz: timezone | None = None
) -> datetime | None:
    if not date or not time:
        return None
    try:
        moment = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return moment.replace(tzinfo=tz) if tz else moment


def extract_role(role: str, cell: Node) -> dict[str, Any]:
    """Applique l'extracteur d'un rôle, ou renvoie un dictionnaire vide."""
    func = EXTRACTORS.get(role)
    return func(cell) if func else {}
