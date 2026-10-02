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
    "EXPECTED_FIELDS",
    "CORE_FIELDS",
    "SLOW_ROLES",
]

#: Champs suivis dans le rapport de parsing.
EXPECTED_FIELDS: tuple[str, ...] = (
    "temperature",
    "humidite",
    "vent_moyen",
    "vent_rafale",
    "vent_direction",
    "pluie_1h",
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

#: Colonnes publiées moins souvent que la cadence des lignes.
#: La pluviométrie n'est renseignée que sur les relevés horaires alors que la
#: température l'est toutes les 10 minutes : sans report, le capteur
#: « Pluie (1h) » serait vide la plupart du temps, y compris sous la pluie.
SLOW_ROLES: tuple[str, ...] = ("pluie_1h",)

#: Au-delà de ce délai, un cumul **positif** n'est plus d'actualité. Un cumul
#: nul, lui, reste valable jusqu'à la prochaine averse.
SLOW_VALUE_MAX_AGE = timedelta(hours=1)


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

    # 7. Reporter les colonnes à cadence lente depuis les relevés précédents.
    _carry_slow_fields(rows, columns, index, moment, data, report)

    # 8. Horodatage et identité de la station.
    data["heure_locale"] = moment.local
    data["heure_utc"] = moment.utc
    data["date"] = moment.date
    if moment.moment_utc is not None:
        data["obs_time_utc"] = moment.moment_utc.isoformat(timespec="minutes")
    _attach_station_info(info, data)

    # 9. Climatologie du jour.
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


def _carry_slow_fields(
    rows: list[Node],
    columns: ColumnResolution,
    chosen_index: int,
    chosen_moment: ObservationTime,
    data: dict[str, Any],
    report: ParseReport,
) -> None:
    """Reporte les mesures à cadence lente depuis les relevés précédents.

    Exemple : à 11h30, la température est fraîche de quelques minutes mais la
    pluviométrie date de 11h00. Sans report, « Pluie (1h) » serait inconnu
    presque tout le temps.
    """
    for role in SLOW_ROLES:
        column = columns.index_of(role)
        if column is None or data.get(role) is not None:
            continue

        # Les lignes sont classées du plus récent au plus ancien : la
        # première qui porte une mesure est la dernière connue.
        for index in range(len(rows)):
            cells = row_cells(rows[index])
            if column >= len(cells):
                continue

            produced = extract_role(role, cells[column])
            value = produced.get(role)
            if value is None:
                continue

            if _is_carry_valid(value, rows[index], cells, columns, chosen_moment):
                data.update(produced)
                report.carried.append(role)
            break  # aucune ligne plus ancienne ne serait plus fraîche


def _is_carry_valid(
    value: float,
    row: Node,
    cells: list[Node],
    columns: ColumnResolution,
    chosen_moment: ObservationTime,
) -> bool:
    """Un cumul nul reste valable ; un cumul positif expire au bout d'une heure."""
    if value == 0:
        return True

    row_moment = _row_time(cells, columns)
    if not row_moment.is_complete or not chosen_moment.is_complete:
        return False
    age = chosen_moment.moment - row_moment.moment
    return timedelta(0) <= age <= SLOW_VALUE_MAX_AGE


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
