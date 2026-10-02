"""Fiche d'identité de la station, telle que la page la publie.

Quand une station tombe, Home Assistant doit pouvoir dire *depuis quand*
plutôt que « plus de données ». Infoclimat affiche cette information dans le
tableau de métadonnées (« Dernier report : 5 mai 2026, 07h30 »), avec une
pastille de couleur. Ce module la lit.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dom import Node, normalize_label

__all__ = ["StationInfo", "parse_station_info", "STATUS_ONLINE", "STATUS_OFFLINE"]


STATUS_ONLINE = "en ligne"
STATUS_OFFLINE = "hors ligne"
STATUS_UNKNOWN = "inconnu"

#: Libellés du tableau de métadonnées → nom de champ.
INFO_LABELS: dict[str, str] = {
    "debut des archives": "archives_start",
    "dernier report": "last_report",
    "altitude": "altitude",
    "departement": "department",
    "coordonnees": "coordinates",
}

#: Pastilles d'état du site. La classe CSS porte la couleur du voyant.
STATUS_CLASSES: tuple[tuple[str, str], ...] = (
    ("led-rouge", STATUS_OFFLINE),
    ("led-verte", STATUS_ONLINE),
    ("led-orange", STATUS_UNKNOWN),
)


@dataclass
class StationInfo:
    """Métadonnées de la station lues sur sa page."""

    name: str | None = None
    status: str = STATUS_UNKNOWN
    last_report: str | None = None
    extra: dict[str, str] | None = None

    @property
    def is_offline(self) -> bool:
        """La station est-elle signalée hors ligne ?"""
        return self.status == STATUS_OFFLINE


def parse_station_info(document: Node) -> StationInfo:
    """Extrait la fiche d'identité de la station."""
    info = StationInfo(extra={})
    info.name = _station_name(document)

    for row in document.find_all("tr"):
        heading = row.find("th")
        if heading is None:
            continue
        label = normalize_label(heading.text())
        field_name = INFO_LABELS.get(label)
        if field_name is None:
            continue

        value_cell = row.find("td")
        if value_cell is None:
            continue

        if field_name == "last_report":
            info.last_report = value_cell.text().removeprefix("Dernier report").strip()
        info.extra[field_name] = value_cell.text()

        status = _status_of(value_cell)
        if status != STATUS_UNKNOWN and field_name == "last_report":
            info.status = status

    return info


def _station_name(document: Node) -> str | None:
    """Nom de la station : le titre de niveau 1, sinon la fiche descriptive."""
    heading = document.find("h1")
    if heading is not None and heading.text():
        return heading.text()

    for node in document.iter():
        text = node.text()
        if text.startswith("Station météorologique de "):
            return text.removeprefix("Station météorologique de ").strip()
    return None


def _status_of(cell: Node) -> str:
    """Couleur du voyant d'état, lue dans les classes CSS de la cellule."""
    for node in cell.iter():
        classes = node.get("class") or ""
        for css_class, status in STATUS_CLASSES:
            if css_class in classes:
                return status
    return STATUS_UNKNOWN
