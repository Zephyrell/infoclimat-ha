"""Résolution des colonnes : libellé d'en-tête → rôle logique.

Principe : **jamais d'index codé en dur**. On lit la ligne d'en-tête, on
normalise chaque libellé, puis on associe chaque colonne à un rôle métier
via une table d'alias. Ajouter, retirer ou réordonner une colonne côté
Infoclimat ne décale plus rien : les colonnes inconnues sont simplement
ignorées, les colonnes absentes laissent leur champ à ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .dom import Node, normalize_label
from .tables import header_cells

__all__ = [
    "FIELD_ALIASES",
    "ColumnBinding",
    "ColumnResolution",
    "resolve_columns",
    "FALLBACK_LAYOUTS",
]

#: Rôles logiques et libellés d'en-tête acceptés.
#: L'ordre n'a pas d'importance : c'est la longueur de l'alias qui tranche
#: (un alias long est plus spécifique qu'un alias court).
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "heure": ("heure locale", "heure", "date heure", "date/heure"),
    "temperature": ("temperature", "tempe", "temp", "temp sous abri", "air"),
    "pluie_1h": ("pluie", "precipitations", "pluie 1h", "pluie/1h"),
    "vent": ("vent",),
    "humidite": ("humidite", "humidite relative", "hr"),
    "bio_meteo": (
        "bio meteo",
        "biometeo",
        "bio",
        "temperature ressentie",
        "ressentie",
        "humidex",
        "windchill",
    ),
    "point_rosee": ("pt de rosee", "point de rosee", "rosee", "td"),
    "pression": ("pression", "pression atmospherique", "pression mer"),
    "neige": ("neige", "hauteur de neige"),
    "uv": ("indice uv", "uv"),
    "radiation": ("radiation", "rayonnement", "w/m2"),
    "visibilite": ("visibilite",),
}

#: Plans de secours positionnels, utilisés **uniquement** si la ligne
#: d'en-tête est illisible. L'ordre des rôles reproduit celui observé sur
#: le site aux dates indiquées. Toute utilisation est signalée dans le
#: rapport de parsing (avertissement) pour ne pas masquer une régression.
FALLBACK_LAYOUTS: tuple[tuple[str, ...], ...] = (
    # 2026 : avec colonne Pluie
    ("heure", "temperature", "pluie_1h", "vent", "humidite", "bio_meteo",
     "point_rosee", "pression"),
    # 2024-2025 : colonne Pluie retirée par Infoclimat
    ("heure", "temperature", "vent", "humidite", "bio_meteo", "point_rosee",
     "pression"),
    # Variante minimale sans bio-météo
    ("heure", "temperature", "pluie_1h", "vent", "humidite", "point_rosee",
     "pression"),
)

_NORMALIZED_ALIASES: dict[str, tuple[tuple[str, str], ...]] = {
    role: tuple(
        (normalize_label(alias), normalize_label(alias).replace(" ", ""))
        for alias in aliases
    )
    for role, aliases in FIELD_ALIASES.items()
}

# Un libellé identique à un alias est sans ambiguïté ; une simple inclusion
# l'est beaucoup moins. L'écart de score doit être franc.
_EXACT_SCORE = 1000
_SUBSTRING_BASE = 10


@dataclass(frozen=True)
class ColumnBinding:
    """Association colonne (index) ↔ rôle logique."""

    role: str
    index: int
    label: str
    alias: str


@dataclass
class ColumnResolution:
    """Résultat de l'analyse de la ligne d'en-tête."""

    by_role: dict[str, int] = field(default_factory=dict)
    bindings: list[ColumnBinding] = field(default_factory=list)
    unknown: list[tuple[int, str]] = field(default_factory=list)
    used_fallback: bool = False

    def index_of(self, role: str) -> int | None:
        """Index de colonne d'un rôle, ou ``None`` s'il est absent."""
        return self.by_role.get(role)

    @property
    def labels(self) -> dict[str, str]:
        """Rôle → libellé d'origine (pour le rapport de parsing)."""
        return {b.role: b.label for b in self.bindings}


def _score(label_norm: str, label_compact: str, alias_norm: str, alias_compact: str) -> int:
    """Score d'association d'un alias à un libellé (0 = pas d'association)."""
    if not label_compact or not alias_compact:
        return 0
    if label_norm == alias_norm or label_compact == alias_compact:
        return _EXACT_SCORE
    if alias_compact in label_compact:
        return _SUBSTRING_BASE + len(alias_compact)
    return 0


def resolve_columns(cells: list[Node]) -> ColumnResolution:
    """Associe chaque colonne d'en-tête à un rôle logique.

    Chaque rôle ne peut être attribué qu'une fois ; chaque colonne ne reçoit
    qu'un seul rôle (le meilleur score encore libre). Les colonnes non
    reconnues sont conservées dans :attr:`ColumnResolution.unknown`.
    """
    resolution = ColumnResolution()
    labels = [(i, cell.text()) for i, cell in enumerate(cells)]

    if not cells:
        return resolution

    # scores[i] = liste (score, rôle) triée du meilleur au moins bon
    scores: dict[int, list[tuple[int, str]]] = {}
    for index, label in labels:
        norm = normalize_label(label)
        compact = norm.replace(" ", "")
        ranked: list[tuple[int, str]] = []
        for role, aliases in _NORMALIZED_ALIASES.items():
            best = max(_score(norm, compact, a, ac) for a, ac in aliases)
            if best:
                ranked.append((best, role))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        scores[index] = ranked

    claimed_roles: set[str] = set()
    for index, label in labels:
        for score, role in scores.get(index, []):
            if role in claimed_roles:
                continue
            claimed_roles.add(role)
            resolution.by_role[role] = index
            resolution.bindings.append(
                ColumnBinding(role=role, index=index, label=label, alias="")
            )
            break
        else:
            if label.strip():
                resolution.unknown.append((index, label))

    resolution.bindings.sort(key=lambda b: b.index)
    return resolution


def fallback_resolution(cell_count: int) -> ColumnResolution:
    """Plan de secours positionnel quand l'en-tête est illisible."""
    for layout in FALLBACK_LAYOUTS:
        if len(layout) == cell_count:
            return ColumnResolution(
                by_role={role: i for i, role in enumerate(layout)},
                bindings=[
                    ColumnBinding(role=role, index=i, label=f"(position {i})", alias="")
                    for i, role in enumerate(layout)
                ],
                used_fallback=True,
            )
    return ColumnResolution(used_fallback=True)


def resolve_table_columns(table: Node, sample_row: Node | None = None) -> ColumnResolution:
    """Résolution complète : en-tête réel, sinon plan de secours.

    :param sample_row: ligne de données servant à dimensionner le repli.
    """
    resolution = resolve_columns(header_cells(table))
    if resolution.by_role:
        return resolution

    if sample_row is not None:
        from .tables import row_cells

        return fallback_resolution(len(row_cells(sample_row)))
    return resolution
