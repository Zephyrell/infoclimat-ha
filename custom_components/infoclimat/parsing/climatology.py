"""Tableau « climatologie du jour » (``table.recap-clim-resp``).

Structure observée : une succession de sections introduites par une ligne
portant un libellé (« Température maximale », « Cumul du jour »…), suivies
d'une ou plusieurs lignes de valeurs. La valeur du jour est le premier
``<b>`` de la section ; les records qui suivent n'utilisent pas ``<b>``.

Le repérage se fait donc par **libellé**, jamais par position : l'ordre des
sections peut changer sans casser le parsing.
"""

from __future__ import annotations

from typing import Any

from .dom import Node, normalize_label
from .fields import first_number
from .tables import body_rows, find_table_by_class, row_cells

__all__ = ["CLIMATOLOGY_TABLE_CLASS", "parse_climatology"]

CLIMATOLOGY_TABLE_CLASS = "recap-clim-resp"

#: Libellé normalisé → champ produit.
CLIMATOLOGY_LABELS: dict[str, str] = {
    "temperature maximale": "temp_max_jour",
    "temperature minimale": "temp_min_jour",
    "rafale maximale": "rafale_max_jour",
    "cumul maxi en 1h": "pluie_max_1h",
    # Fenêtre synoptique 6h–6h UTC, pas 24 h glissantes : « partiel » veut
    # dire que la journée est en cours. Le site publie le vrai 24 h glissant
    # dans une section distincte, reprise ci-dessous.
    "cumul du jour": "pluie_cumul_jour",
    # Valeur « en direct » publiée par le site : elle prime sur la
    # reconstitution de :func:`parsing._derive_rain_totals` (appliquée avant
    # la climatologie dans :func:`parse_station_page`).
    "cumul 24h glissantes": "pluie_24h",
}

#: Repères de la ligne « Degrés Jour Unifiés ».
_DJU_LABELS = {"chauffe": "dju_chauffe", "froid": "dju_froid"}


def parse_climatology(document: Node) -> dict[str, Any]:
    """Extrait les données climatologiques du jour.

    :param document: arbre de la page, fenêtres surgissantes retirées.
    """
    table = find_table_by_class(document, CLIMATOLOGY_TABLE_CLASS)
    if table is None:
        return {}

    result: dict[str, Any] = {}
    current_field: str | None = None

    for row in body_rows(table):
        label = _label_of(row)
        if label is not None:
            current_field = label

        for cell in row_cells(row):
            # Le contexte de chaque <b> est pris séparément : la ligne DJU
            # empile « <b>0.1</b> chauffe » et « <b>1.2</b> froid » dans une
            # même cellule, un libellé par cellule les confondrait.
            for bold, context in cell.element_segments("b"):
                value = first_number(bold.text())
                if value is None:
                    continue
                dju_field = _dju_field(normalize_label(context))
                if dju_field is not None:
                    result.setdefault(dju_field, value)
                elif current_field is not None:
                    result.setdefault(current_field, value)

    return result


def _label_of(row: Node) -> str | None:
    """Champ introduit par cette ligne, s'il s'agit d'une ligne de libellé."""
    for cell in row_cells(row):
        label = normalize_label(cell.text())
        for known, field in CLIMATOLOGY_LABELS.items():
            if label.startswith(known):
                return field
    return None


def _dju_field(cell_label: str) -> str | None:
    for marker, field in _DJU_LABELS.items():
        if marker in cell_label:
            return field
    return None
