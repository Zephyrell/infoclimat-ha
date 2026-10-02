"""Tests du moteur de parsing Infoclimat.

Chaque test couvre une façon dont la page peut *casser* un parseur naïf :
HTML imbriqué dans un attribut, colonnes réordonnées, colonnes absentes,
popups, tableaux dupliqués, station muette, pluviométrie à cadence lente.
"""

from __future__ import annotations

import re

import pytest

from conftest import load_fixture
from parsing import (
    AntiBotChallengeError,
    ObservationTableNotFoundError,
    StationWithoutDataError,
    parse_station_page,
)
from parsing.dom import parse_html

# ──────────────────────────────────────────────────────────────────────
# 1. Le bug d'origine : une table HTML imbriquée DANS un attribut
# ──────────────────────────────────────────────────────────────────────


def test_il_pleut_releve_le_plus_recent():
    """Quand il pleut, la cellule « Pluie » porte une infobulle dont le
    contenu est lui-même une table HTML. Elle ne doit pas casser le parsing.
    """
    obs = parse_station_page(load_fixture("station_pluie.html"))

    # Le relevé retenu est bien le plus récent, pas un relevé plus ancien
    assert obs.data["heure_locale"] == "11h30"
    assert obs.data["obs_time_utc"] == "2026-10-02T09:30+00:00"
    assert obs.data["temperature"] == 12.4

    # La mesure tombée du ciel, avec son unité collée
    assert obs.data["pluie_1h"] == 2.4

    # Et les cumuls, qui ne vivent QUE dans l'infobulle
    assert obs.data["pluie_3h"] == 3.6
    assert obs.data["pluie_24h"] == 12.4


def test_reste_des_champs_sur_la_ligne_pluvieuse():
    """La ligne pluvieuse ne doit pas être tronquée : les colonnes situées
    APRÈS la cellule Pluie doivent être lues normalement."""
    obs = parse_station_page(load_fixture("station_pluie.html")).data

    assert obs["vent_moyen"] == 23.0
    assert obs["vent_rafale"] == 47.5
    assert obs["vent_direction"] == 245.0
    assert obs["humidite"] == 94.0
    assert obs["bio_meteo"] == 11.2
    assert obs["point_rosee"] == 11.5
    assert obs["pression"] == 997.3
    assert obs["pression_tendance"] == "baisse"
    assert obs["pression_variation_3h"] == -1.4


def test_regression_l_ancien_parser_perdait_la_ligne_pluvieuse():
    """Archive du bug : l'ancien découpage `<tr[^>]*>(.*?)</tr>` s'arrête au
    premier `</tr>` rencontré, y compris celui qui dort à l'intérieur de
    l'attribut `title`. La ligne est alors coupée en morceaux, aucun
    fragment n'atteint 7 cellules, et le relevé le plus récent est écarté.
    """
    html = load_fixture("station_pluie.html")
    # Viser le tbody du VRAI tableau, pas celui du clone masqué
    tbody = re.search(
        r'<table[^>]*id="resptable-releves"[^>]*>.*?<tbody>(.*?)</tbody>',
        html,
        re.DOTALL,
    ).group(1)

    fragments = re.findall(r"<tr[^>]*>(.*?)</tr>", tbody, re.DOTALL)
    # 3 lignes réelles -> 7 fragments : la première est éclatée en 3
    assert len(fragments) == 7

    cellules = [
        len(re.findall(r"<(t[dh])[^>]*>(.*?)</\1>", f, re.DOTALL)) for f in fragments
    ]
    # Les fragments issus de la ligne pluvieuse sont tous sous le seuil de 7
    assert cellules[0] < 7 and cellules[1] < 7

    retenue = next((f for f in fragments if len(re.findall(r"<(t[dh])[^>]*>", f)) >= 7), None)
    assert retenue is not None
    # ...et la ligne « retenue » par l'ancien code est l'AVANT-dernière (11h20)
    assert "11h20" in retenue
    assert "12.6" in retenue  # température périmée servie à l'utilisateur


# ──────────────────────────────────────────────────────────────────────
# 2. Robustesse de la micro-DOM
# ──────────────────────────────────────────────────────────────────────


def test_attribut_contenant_du_html_ne_rompt_pas_le_texte():
    """`<br />` à l'intérieur d'un attribut ne doit pas dévorer la suite."""
    doc = parse_html(
        '<th><a title="Température sous abri,<br />relevée à 2m du sol">'
        "Tempé<span>rature</span></a></th>"
    )
    assert doc.text() == "Température"


def test_br_devient_un_separateur_de_mots():
    """Un `<br />` sépare bien deux mots, sans les coller."""
    doc = parse_html("<td>11.5<br />hPa/3h</td>")
    assert doc.text() == "11.5 hPa/3h"


def test_script_et_style_exclus_du_texte():
    doc = parse_html("<div>Visible<script>var x = '<td>faux</td>';</script></div>")
    assert doc.text() == "Visible"


# ──────────────────────────────────────────────────────────────────────
# 3. Les popups et le bruit de page
# ──────────────────────────────────────────────────────────────────────


def test_popups_ne_polluent_pas_les_donnees():
    """Les modales d'information contiennent des chiffres crédibles pour un
    parseur naïf (99.9 mm, 48.7 °C) : ils ne doivent jamais ressortir."""
    obs = parse_station_page(load_fixture("station_pluie.html"))

    assert 48.7 not in obs.data.values()
    assert 99.9 not in obs.data.values()
    assert obs.data["temp_max_jour"] == 13.9

    # Les modales sont bien détectées et signalées, sans être parsées
    assert len(obs.report.notices) == 2
    assert all(n.identifier for n in obs.report.notices)


def test_tableau_duplique_ignore():
    """Le clone `#duplicate-resptable` (en-tête figé) ne doit pas être lu."""
    obs = parse_station_page(load_fixture("station_pluie.html"))
    assert -99.0 not in obs.data.values()
    assert obs.report.table_selector == "table#resptable-releves"


# ──────────────────────────────────────────────────────────────────────
# 4. Colonnes : ordre, absence, inconnues
# ──────────────────────────────────────────────────────────────────────


def test_colonnes_reordonnees_et_inconnues():
    """L'ordre des colonnes change et une colonne inconnue apparaît : les
    valeurs doivent rester rattachées au bon rôle."""
    obs = parse_station_page(load_fixture("station_colonnes_reordonnees.html"))

    assert obs.data["temperature"] == 27.8
    assert obs.data["humidite"] == 41.0
    assert obs.data["point_rosee"] == 13.2
    assert obs.data["pression"] == 1013.2
    assert obs.data["pression_tendance"] == "stable"
    assert obs.data["vent_moyen"] == 8.0
    assert obs.data["vent_rafale"] == 19.4
    assert obs.data["vent_direction"] == 80.0

    # La colonne « Pluie » est absente : le champ reste vide, sans erreur
    assert obs.data.get("pluie_1h") is None
    # La colonne inconnue est signalée mais n'empêche rien
    # Le libellé est conservé tel que le site l'écrit, pour le diagnostic
    assert list(obs.report.unknown_columns) == ["Colonne inconnue"]
    # Les colonnes ont été reconnues par leur en-tête, pas par leur position
    assert not obs.report.header_fallback
    assert not obs.report.table_fallback


# ──────────────────────────────────────────────────────────────────────
# 5. Climatologie du jour
# ──────────────────────────────────────────────────────────────────────


def test_climatologie_et_dju_decimaux():
    """Les DJU sont deux valeurs dans une seule cellule : `5.4 chauffe` et
    `0.0 froid`. Un `(\\d+) chauffe` naïf lirait `4` et `0`."""
    obs = parse_station_page(load_fixture("station_pluie.html")).data

    assert obs["temp_max_jour"] == 13.9
    assert obs["temp_min_jour"] == 11.1
    assert obs["rafale_max_jour"] == 55.4
    assert obs["pluie_max_1h"] == 2.4
    assert obs["pluie_cumul_jour"] == 12.4
    assert obs["dju_chauffe"] == 5.4
    assert obs["dju_froid"] == 0.0


# ──────────────────────────────────────────────────────────────────────
# 6. Cadences différentes : la pluviométrie est horaire, la température
#    est déciminutéenne
# ──────────────────────────────────────────────────────────────────────


def test_pluie_reprise_depuis_un_releve_anterieur():
    """Le relevé de 11h30 n'a pas de mesure de pluie, mais celui de 11h00 si
    (30 min plus tôt) : la valeur est reprise et signalée comme reportée."""
    obs = parse_station_page(load_fixture("station_pluie_reportee.html"))

    assert obs.data["temperature"] == 12.4  # bien le relevé de 11h30
    assert obs.data["heure_locale"] == "11h30"
    assert obs.data["pluie_1h"] == 2.4  # repris de 11h00
    assert obs.data["pluie_3h"] == 3.6

    assert "pluie_1h" in obs.report.carried


def test_pluie_trop_ancienne_non_reprise():
    """Au-delà d'une heure, la valeur reportée n'a plus de sens : on
    préfère ne rien publier plutôt que publier une mesure périmée."""
    obs = parse_station_page(load_fixture("station_pluie_perimee.html"))

    assert obs.data["heure_locale"] == "11h30"
    # La seule mesure du tableau date de 09h00, soit 2h30 avant : refusée
    assert obs.data.get("pluie_1h") is None
    assert obs.data.get("pluie_3h") is None
    assert "pluie_1h" not in obs.report.carried


# ──────────────────────────────────────────────────────────────────────
# 7. Stations muettes
# ──────────────────────────────────────────────────────────────────────


def test_station_sans_donnees_leve_une_exception_explicite():
    """Une station hors service doit produire une erreur *nommée*, pas un
    `None` silencieux qui remonte en `UpdateFailed` générique."""
    with pytest.raises(StationWithoutDataError):
        parse_station_page(load_fixture("station_sans_donnees.html"))


def test_station_muette_dit_depuis_quand():
    """« Plus de données » ne suffit pas à diagnostiquer : la page publie la
    date du dernier report, on la remonte jusqu'à l'utilisateur."""
    with pytest.raises(StationWithoutDataError) as excinfo:
        parse_station_page(load_fixture("station_sans_donnees.html"))
    assert excinfo.value.last_report == "5 mai 2026, 07h30"


def test_station_vivante_expose_son_etat():
    """Le voyant de la page est repris tel quel : vert = en ligne."""
    obs = parse_station_page(load_fixture("station_pluie.html"))
    assert obs.data["station_status"] == "en ligne"
    assert obs.data["station_last_report"] == "2 octobre 2026, 11h30"


def test_page_anti_robot_reconnue_comme_telle():
    """Quand le site bloque les requêtes automatisées, il renvoie une page au
    même titre, sans tableau. Sans détection dédiée elle passerait pour une
    station hors service — une panne annoncée qui n'existe pas."""
    with pytest.raises(AntiBotChallengeError) as excinfo:
        parse_station_page(load_fixture("station_antibot.html"))
    assert "automatisee" in str(excinfo.value)


def test_une_station_muette_n_est_pas_prise_pour_un_blocage():
    """Inversement, une vraie station sans données ne doit pas être signalée
    comme un blocage anti-robot : les deux erreurs restent distinctes."""
    with pytest.raises(StationWithoutDataError) as excinfo:
        parse_station_page(load_fixture("station_sans_donnees.html"))
    assert not isinstance(excinfo.value, AntiBotChallengeError)


def test_page_sans_tableau_leve_une_exception_distincte():
    """Le conteneur est bien présent mais le tableau a disparu (refonte du
    site) : l'erreur doit désigner le tableau, pas la station."""
    with pytest.raises(ObservationTableNotFoundError):
        parse_station_page(
            '<html><body><div class="resptable-container">'
            "<p>Tableau momentanément indisponible</p></div></body></html>"
        )


# ──────────────────────────────────────────────────────────────────────
# 8. Le rapport de diagnostic
# ──────────────────────────────────────────────────────────────────────


def test_rapport_decrit_ce_qui_s_est_passe():
    obs = parse_station_page(load_fixture("station_pluie.html"))
    resume = obs.report.summary()

    assert "resptable-releves" in resume
    assert "colonnes=8" in resume
    assert "relevé=11h30" in resume
    # Les champs absents sont énumérés, pas cachés
    assert "pluie_6h" in resume
