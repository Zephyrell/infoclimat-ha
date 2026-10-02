"""Localisation des tableaux et itération lignes / cellules.

Toute la connaissance « où se trouve quoi » est isolée ici. Si Infoclimat
renomme son tableau, c'est le seul fichier à toucher.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dom import Node

__all__ = [
    "CELL_TAGS",
    "TableMatch",
    "find_table",
    "find_observation_table",
    "observation_table_container",
    "body_rows",
    "header_cells",
    "row_cells",
    "dump_rows",
]

CELL_TAGS = ("td", "th")

#: Identifiant du tableau des relevés temps réel.
OBSERVATION_TABLE_ID = "resptable-releves"

#: Classes de repli si l'identifiant change.
OBSERVATION_TABLE_CLASS = "resptable"

#: Conteneur englobant le tableau (sert à distinguer « station sans données »).
OBSERVATION_CONTAINER_CLASS = "resptable-container"

#: Préfixe des copies techniques (en-tête figé au défilement) à ignorer.
_DUPLICATE_PREFIX = "duplicate"


@dataclass(frozen=True)
class TableMatch:
    """Tableau trouvé, avec le sélecteur qui a permis de le trouver."""

    node: Node
    selector: str
    fallback: bool = False


def find_table(root: Node, table_id: str) -> Node | None:
    """Tableau portant exactement cet identifiant."""
    for table in root.find_all("table"):
        if table.get("id") == table_id:
            return table
    return None


def find_table_by_class(root: Node, class_name: str) -> Node | None:
    """Premier tableau portant cette classe, hors copies techniques."""
    for table in root.find_all("table"):
        if (table.get("id") or "").startswith(_DUPLICATE_PREFIX):
            continue
        if table.has_class(class_name):
            return table
    return None


def find_observation_table(root: Node) -> TableMatch | None:
    """Tableau des relevés temps réel.

    Cherche d'abord l'identifiant exact, puis se rabat sur la classe en
    écartant ``#duplicate-resptable`` (copie masquée pour l'en-tête figé,
    présente *avant* le vrai tableau dans le flux HTML).
    """
    table = find_table(root, OBSERVATION_TABLE_ID)
    if table is not None:
        return TableMatch(table, f"table#{OBSERVATION_TABLE_ID}")

    table = find_table_by_class(root, OBSERVATION_TABLE_CLASS)
    if table is not None:
        return TableMatch(table, f"table.{OBSERVATION_TABLE_CLASS}", fallback=True)

    return None


def observation_table_container(root: Node) -> Node | None:
    """Conteneur ``.resptable-container`` s'il existe.

    Son absence signifie que la station ne publie aucune donnée temps réel
    (station fermée, hors-ligne, ou identifiant inconnu) — un état normal
    qu'il faut distinguer d'une panne de parsing.
    """
    for node in root.iter():
        if node.has_class(OBSERVATION_CONTAINER_CLASS):
            return node
    return None


def _owned_by(node: Node, ancestor: Node) -> bool:
    """Le nœud appartient-il à ce tableau (et non à un tableau imbriqué) ?"""
    parent = node.parent
    while parent is not None:
        if parent is ancestor:
            return True
        if parent.tag == "table":
            return False
        parent = parent.parent
    return False


def body_rows(table: Node) -> list[Node]:
    """Lignes de données du tableau, en-tête et tableaux imbriqués exclus."""
    tbody = table.find("tbody")
    scope = tbody if tbody is not None else table
    rows = [tr for tr in scope.find_all("tr") if _owned_by(tr, scope)]
    if tbody is not None:
        return rows
    # Pas de <tbody> : on écarte les lignes situées dans le <thead>.
    thead = table.find("thead")
    if thead is None:
        return rows
    return [tr for tr in rows if not _owned_by(tr, thead)]


def header_cells(table: Node) -> list[Node]:
    """Cellules de la dernière ligne d'en-tête (``<thead>``)."""
    thead = table.find("thead")
    if thead is None:
        return []
    candidates: list[list[Node]] = []
    for tr in thead.find_all("tr"):
        cells = row_cells(tr)
        if any(cell.tag == "th" for cell in cells):
            candidates.append(cells)
    return candidates[-1] if candidates else []


def row_cells(row: Node) -> list[Node]:
    """Cellules (``<td>``/``<th>``) filles directes d'une ligne."""
    return [c for c in row.children if isinstance(c, Node) and c.tag in CELL_TAGS]


def dump_rows(table: Node) -> list[list[str]]:
    """Rend le tableau sous forme de listes de textes (diagnostic/tests)."""
    return [[cell.text() for cell in row_cells(row)] for row in body_rows(table)]
