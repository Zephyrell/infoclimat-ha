"""Parsing des pages Infoclimat — architecture en couches.

    dom.py          tokenizer HTML → arbre           (aucune règle métier)
    tables.py       où sont les tableaux             (sélecteurs)
    columns.py      en-tête      → rôle logique      (alias)
    fields.py       cellule      → capteurs          (extracteurs)
    climatology.py  table « climatologie du jour »
    notices.py      popups / bandeaux
    report.py       traçabilité

Chaque couche est remplaçable indépendamment. Le contrat public est ici :
:func:`parse_station_page` renvoie un :class:`StationObservation` ou lève une
:class:`InfoclimatParseError` explicite.

Ajouter un capteur = un extracteur dans :mod:`parsing.fields` + un alias dans
:mod:`parsing.columns`. Aucun index ni nom de colonne n'est codé en dur
ailleurs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from .antibot import looks_like_antibot
from .climatology import parse_climatology
from .columns import ColumnResolution, resolve_table_columns
from .dom import Node, parse_html
from .encoding import decode_page
from .fields import (
    TIME_ROLE,
    ObservationTime,
    extract_role,
    parse_observation_time,
)
from .notices import find_notices, prune_notices
from .report import STATUS_ABSENT, STATUS_EMPTY, STATUS_OK, ParseReport
from .station import parse_station_info
from .tables import (
    body_rows,
    find_observation_table,
    observation_table_container,
    row_cells,
)

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "InfoclimatParseError",
    "AntiBotChallengeError",
    "StationWithoutDataError",
    "ObservationTableNotFoundError",
    "EmptyObservationError",
    "StationObservation",
    "parse_station_page",
    "decode_page",
    "EXPECTED_FIELDS",
    "CORE_FIELDS",
]

#: Champs suivis dans le rapport de parsing.
EXPECTED_FIELDS: tuple[str, ...] = (
    "temperature",
    "humidite",
    "vent_moyen",
    "vent_rafale",
    "vent_direction",
    "pluie_1h",
    "pluie_instantannee",
    "pluie_intensite_max_1h",
    "pluie_3h",
    "pluie_6h",
    "pluie_12h",
    "pluie_24h",
    "point_rosee",
    "bio_meteo",
    "pression",
    "pression_tendance",
    "pression_variation_3h",
    "temp_max_jour",
    "temp_min_jour",
    "rafale_max_jour",
    "pluie_max_1h",
    "pluie_cumul_jour",
    "dju_chauffe",
    "dju_froid",
)

#: Un relevé est considéré exploitable si au moins un de ces champs est lu.
CORE_FIELDS: tuple[str, ...] = ("temperature", "humidite", "pression", "vent_moyen")

#: Cumuls que le site ne publie que sur ses lignes horaires. Les relevés
#: déciminutés qui suivent n'en donnent que leurs incréments.
RAIN_WINDOWS: tuple[int, ...] = (3, 6, 12, 24)

#: Au-delà de ce délai, le cumul de la dernière heure fixe ne décrit plus la
#: fenêtre en cours : on ne l'étend pas avec les relevés déciminutés (les
#: trous de publication rendraient l'estimation fausse).
RAIN_BASE_MAX_AGE = timedelta(hours=1)


class InfoclimatParseError(Exception):
    """Le parsing de la page Infoclimat a échoué."""


class AntiBotChallengeError(InfoclimatParseError):
    """Infoclimat a renvoyé sa page anti-robot au lieu de la station.

    Ce n'est *pas* une panne de la station : le site a jugé les requêtes trop
    rapprochées. Il faut ralentir puis réessayer.
    """


class StationWithoutDataError(InfoclimatParseError):
    """La station ne publie aucune donnée temps réel (fermée, hors-ligne…).

    ``last_report`` porte la date du dernier relevé publié, quand la page la
    donne : c'est l'information qui distingue « station fermée » de
    « identifiant erroné ».
    """

    def __init__(self, message: str, last_report: str | None = None) -> None:
        super().__init__(message)
        self.last_report = last_report


class ObservationTableNotFoundError(InfoclimatParseError):
    """Le conteneur existe mais le tableau des relevés est introuvable."""


class EmptyObservationError(InfoclimatParseError):
    """Le tableau est présent mais aucune ligne exploitable n'en a été tirée."""


@dataclass
class StationObservation:
    """Relevé extrait d'une page de station."""

    data: dict[str, Any] = field(default_factory=dict)
    report: ParseReport = field(default_factory=ParseReport)


def parse_station_page(html: str) -> StationObservation:
    """Extrait le relevé le plus récent d'une page de station Infoclimat.

    :param html: contenu brut de la page.
    :raises AntiBotChallengeError: le site a servi sa page anti-robot.
    :raises StationWithoutDataError: station sans données temps réel.
    :raises ObservationTableNotFoundError: tableau des relevés introuvable.
    :raises EmptyObservationError: aucune ligne exploitable.
    """
    document = parse_html(html)

    # 1. Recenser puis neutraliser les fenêtres surgissantes : elles ne
    #    doivent jamais interférer avec les recherches à l'échelle de la page.
    report = ParseReport(notices=find_notices(document))
    scope = prune_notices(document)

    # 2. Lire la fiche d'identité : elle sert à la fois à nommer la station
    #    et à expliquer, le cas échéant, pourquoi elle est muette.
    info = parse_station_info(scope)

    # 3. Localiser le tableau des relevés.
    match = find_observation_table(scope)
    if match is None:
        container = observation_table_container(scope)
        if container is None:
            # Page sans tableau : le site a-t-il servi son mur anti-robot ?
            # Le message est explicite, on le distingue d'une station muette.
            marker = looks_like_antibot(scope)
            if marker is not None:
                raise AntiBotChallengeError(
                    "Infoclimat a renvoyé sa page anti-robot "
                    f"(déclencheur : {marker!r})"
                )
            raise StationWithoutDataError(
                "la station ne publie aucune donnée temps réel", info.last_report
            )
        raise ObservationTableNotFoundError(
            "tableau des relevés introuvable (structure de page modifiée ?)"
        )
    report.table_selector = match.selector
    report.table_fallback = match.fallback
    if match.fallback:
        report.warn(f"sélecteur de repli utilisé ({match.selector})")

    # 4. Résoudre les colonnes par leur en-tête.
    rows = body_rows(match.node)
    report.rows_total = len(rows)
    columns = resolve_table_columns(match.node, sample_row=rows[0] if rows else None)
    report.columns = columns.labels
    report.unknown_columns = [label for _, label in columns.unknown]
    report.header_fallback = columns.used_fallback
    if columns.used_fallback:
        report.warn("en-tête illisible : plan de colonnes positionnel utilisé")
    if "temperature" not in columns.by_role:
        report.warn("colonne Température non identifiée")
    if not rows:
        raise EmptyObservationError("tableau des relevés vide")

    # 5. Retenir le relevé le plus récent, par horodatage.
    index, cells, moment = _select_latest_row(rows, columns)
    if index is None:
        raise EmptyObservationError("aucune ligne de relevé exploitable")
    report.row_index = index
    report.row_time = moment.local or moment.utc

    # 6. Extraire les champs de la ligne retenue.
    data = _extract_row(cells, columns, report)

    # 7. Reconstituer les cumuls de pluie jusqu'au relevé choisi.
    _derive_rain_totals(rows, columns, index, moment, data, report)

    # 8. Horodatage et identité de la station.
    data["heure_locale"] = moment.local
    data["heure_utc"] = moment.utc
    data["date"] = moment.date
    if moment.moment_utc is not None:
        data["obs_time_utc"] = moment.moment_utc.isoformat(timespec="minutes")
    _attach_station_info(info, data)

    # 9. Climatologie du jour. Appliquée après la recomposition : elle porte
    #    le « Cumul 24h glissantes » publié en direct par le site, qui doit
    #    primer sur notre estimation (plus frais et exact).
    data.update(parse_climatology(scope))

    # 10. Vérifier qu'il reste quelque chose d'exploitable.
    report.fields = _field_status(data)
    if not any(data.get(name) is not None for name in CORE_FIELDS):
        raise EmptyObservationError(
            "aucun champ principal lu (température, humidité, pression, vent)"
        )

    return StationObservation(data=data, report=report)


# ─────────────────────── Sélection de la ligne ───────────────────────


def _row_time(cells: list[Node], columns: ColumnResolution) -> ObservationTime:
    """Horodatage d'une ligne, si la colonne Heure a été identifiée."""
    time_index = columns.index_of(TIME_ROLE)
    if time_index is None or time_index >= len(cells):
        return ObservationTime()
    return parse_observation_time(cells[time_index])


def _row_has_value(cells: list[Node], columns: ColumnResolution) -> bool:
    """La ligne porte-t-elle au moins une valeur dans une colonne connue ?"""
    for role, index in columns.by_role.items():
        if role == TIME_ROLE:
            continue
        if index < len(cells) and cells[index].text():
            return True
    return False


def _select_latest_row(rows: list[Node], columns: ColumnResolution):
    """Ligne de relevé la plus récente.

    Le site liste les relevés du plus récent au plus ancien, mais la première
    ligne n'est pas nécessairement la bonne : certaines lignes sont des
    intercalaires. On trie donc sur l'horodatage réel — c'est précisément ce
    qui manquait quand l'apparition de la pluie faisait disparaître la
    première ligne complète.
    """
    ranked: list[tuple] = []
    undated: list[tuple] = []

    for index, row in enumerate(rows):
        cells = row_cells(row)
        if not cells or not _row_has_value(cells, columns):
            continue

        moment = _row_time(cells, columns)
        if moment.is_complete:
            ranked.append((moment.moment, -index, index, cells, moment))
        else:
            undated.append((index, cells, moment))

    if ranked:
        _, _, index, cells, moment = max(ranked)
        return index, cells, moment
    if undated:
        index, cells, moment = undated[0]
        return index, cells, moment
    return None, None, ObservationTime()


def _extract_row(
    cells: list[Node], columns: ColumnResolution, report: ParseReport
) -> dict[str, Any]:
    """Applique chaque extracteur de colonne à la ligne retenue."""
    data: dict[str, Any] = {}
    for role, index in columns.by_role.items():
        if role == TIME_ROLE:
            continue
        if index >= len(cells):
            report.warn(f"colonne « {role} » hors limites de la ligne")
            continue
        data.update(extract_role(role, cells[index]))
    return data


def _derive_rain_totals(
    rows: list[Node],
    columns: ColumnResolution,
    chosen_index: int,
    chosen_moment: ObservationTime,
    data: dict[str, Any],
    report: ParseReport,
) -> None:
    """Reconstitue les cumuls de pluie jusqu'au relevé choisi.

    Le site ne publie les cumuls 3/6/12/24 h que sur les lignes horaires
    (``… mm/1h`` et son infobulle). Les lignes déciminutées, elles, ne portent
    que le cumul de leurs dix dernières minutes. Sans recomposition, les
    capteurs de cumul restent figés sur la dernière heure pile — ou
    disparaissent dès que le relevé retenu n'est pas horaire.

    Cumul sur N heures = valeur de la dernière ligne horaire + tous les
    cumuls déciminutés postérieurs. La fenêtre déborde donc de moins d'une
    heure ; c'est l'approximation retenue, faute de connaître l'incrément
    sortant par le haut.

    Pour l'heure écoulée en revanche, le calcul est exact : on additionne les
    intervalles de dix minutes de la fenêtre, la ligne horaire contribuant
    pour ses dix dernières minutes (lues dans l'infobulle, ``Pluie/10mn``).

    Le site publie par ailleurs un « Cumul 24h glissantes » en direct dans sa
    climatologie. Appliqué après cette fonction, il remplace le 24 h
    reconstitué : c'est la valeur de référence quand la section existe.
    """
    column = columns.index_of("pluie_1h")
    if column is None:
        return

    cells_by_row = [row_cells(row) for row in rows]
    moments = [_row_time(cells, columns) for cells in cells_by_row]
    produced = [
        extract_role("pluie_1h", cells[column]) if column < len(cells) else {}
        for cells in cells_by_row
    ]

    # Une cellule vide signifie « pas de pluie sur l'intervalle » — mais
    # seulement si la station a un pluviomètre. Une station sans capteur
    # laisse toutes ses cellules vides, y compris celles des heures piles.
    gauge = any(
        item.get("pluie_cumul_intervalle") is not None
        or any(f"pluie_{hours}h" in item for hours in RAIN_WINDOWS)
        for item in produced
    )
    if not gauge:
        return

    chosen = produced[chosen_index] if chosen_index < len(produced) else {}
    chosen_amount = chosen.get("pluie_cumul_intervalle")
    if chosen_amount is None:
        # Ligne déciminutée sèche : le site laisse la cellule vide.
        data["pluie_cumul_intervalle"] = 0.0

    # Intensité instantanée : celle de la ligne retenue, ou zéro si la
    # cellule est vide (il ne pleut pas).
    if "pluie_instantannee" in chosen:
        data["pluie_instantannee"] = chosen["pluie_instantannee"]
    elif chosen_amount in (None, 0.0):
        data["pluie_instantannee"] = 0.0

    # Dernière ligne horaire — celle qui porte réellement un cumul sur 1 h.
    hourly_index = None
    for index in range(chosen_index, len(produced)):
        item = produced[index]
        if (
            item.get("pluie_intervalle_min") == 60
            and item.get("pluie_cumul_intervalle") is not None
        ):
            hourly_index = index
            break

    if hourly_index is not None:
        _extend_from_hourly(
            produced, moments, chosen_index, chosen_moment, hourly_index, data, report
        )
        return

    # Aucune ligne horaire dans la page (station récente, page tronquée) :
    # on peut encore sommer les intervalles de dix minutes de l'heure.
    if chosen_moment.is_complete:
        rolling = _sum_window(produced, moments, chosen_index, chosen_moment, 60)
        if rolling is not None:
            data["pluie_1h"] = rolling


def _extend_from_hourly(
    produced: list[dict[str, Any]],
    moments: list[ObservationTime],
    chosen_index: int,
    chosen_moment: ObservationTime,
    hourly_index: int,
    data: dict[str, Any],
    report: ParseReport,
) -> None:
    """Étend les cumuls de la dernière ligne horaire avec les 10 min suivantes."""
    base = produced[hourly_index]
    base_moment = moments[hourly_index]

    if not chosen_moment.is_complete or not base_moment.is_complete:
        return
    age = chosen_moment.moment - base_moment.moment
    if not timedelta(0) <= age <= RAIN_BASE_MAX_AGE:
        # Trop ancien : les trous de publication rendraient le total faux.
        return

    increment = 0.0
    for index in range(chosen_index, hourly_index):
        amount = produced[index].get("pluie_cumul_intervalle")
        if amount is not None:
            increment += amount
    increment = round(increment, 2)

    for hours in RAIN_WINDOWS:
        base_value = base.get(f"pluie_{hours}h")
        if base_value is not None:
            data[f"pluie_{hours}h"] = round(base_value + increment, 2)

    data["pluie_heure_fixe"] = base_moment.local or base_moment.utc
    data["pluie_depuis_heure_fixe"] = increment

    if hourly_index != chosen_index:
        report.carried.append("pluie_1h")

    rolling = _rolling_hour(produced, moments, chosen_index, chosen_moment, hourly_index)
    if rolling is not None:
        data["pluie_1h"] = rolling


def _rolling_hour(
    produced: list[dict[str, Any]],
    moments: list[ObservationTime],
    chosen_index: int,
    chosen_moment: ObservationTime,
    hourly_index: int,
) -> float | None:
    """Cumul exact des soixante dernières minutes, si les données suffisent."""
    if hourly_index == chosen_index:
        # Le relevé retenu est la ligne horaire : son cumul est par définition
        # l'heure écoulée.
        return produced[hourly_index].get("pluie_cumul_intervalle")

    # Station qui ne publie la pluie qu'à l'heure : aucun incrément
    # déciminuté à ajouter, on reprend le cumul horaire tel quel.
    deciminute = any(
        produced[index].get("pluie_intervalle_min") == 10
        and produced[index].get("pluie_cumul_intervalle") is not None
        for index in range(hourly_index)
    )
    if not deciminute:
        return produced[hourly_index].get("pluie_cumul_intervalle")

    return _sum_window(produced, moments, chosen_index, chosen_moment, 60, hourly_index)


def _sum_window(
    produced: list[dict[str, Any]],
    moments: list[ObservationTime],
    chosen_index: int,
    chosen_moment: ObservationTime,
    minutes: int,
    hourly_index: int | None = None,
) -> float | None:
    """Somme des cumuls d'intervalle sur les ``minutes`` précédant le relevé.

    La ligne horaire ne contribue que pour ses dix dernières minutes
    (``Pluie/10mn``) : le reste de son heure sort de la fenêtre ou est
    déjà couvert par les lignes déciminutées.
    """
    start = chosen_moment.moment - timedelta(minutes=minutes)
    total = 0.0
    seen = False

    for index in range(chosen_index, len(produced)):
        moment = moments[index]
        if not moment.is_complete:
            # Ligne intercalaire sans horodatage : elle ne porte pas de pluie.
            continue
        if moment.moment <= start:
            break
        seen = True
        if index == hourly_index:
            chunk = produced[index].get("pluie_10mn")
            if chunk is not None:
                total += chunk
        else:
            amount = produced[index].get("pluie_cumul_intervalle")
            if amount is not None:
                total += amount

    return round(total, 2) if seen else None


# ──────────────────────────── Annexes ────────────────────────────


def _attach_station_info(info, data: dict[str, Any]) -> None:
    """Nom et état de la station, recopiés dans le relevé."""
    if info.name:
        data["station"] = info.name
    if info.last_report:
        data["station_last_report"] = info.last_report
    if info.status != "inconnu":
        data["station_status"] = info.status


def _field_status(data: dict[str, Any]) -> dict[str, str]:
    status: dict[str, str] = {}
    for name in EXPECTED_FIELDS:
        if name not in data:
            status[name] = STATUS_ABSENT
        elif data[name] is None:
            status[name] = STATUS_EMPTY
        else:
            status[name] = STATUS_OK
    return status
