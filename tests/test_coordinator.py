"""Tests du coordinateur : traduction des erreurs, ralentissement, fraîcheur.

Home Assistant n'est pas installé dans l'environnement de test : ses quelques
symboles sont bouchonnés par `stubs.install()` avant l'import du module.
"""

from __future__ import annotations

import asyncio
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

import stubs

stubs.install()

from conftest import load_fixture, load_fixture_bytes  # noqa: E402
from infoclimat import coordinator as coordinator_module  # noqa: E402
from infoclimat.coordinator import InfoclimatCoordinator, _format_age  # noqa: E402
from infoclimat.parsing import (  # noqa: E402
    EmptyObservationError,
    ObservationTableNotFoundError,
    StationWithoutDataError,
)
from stubs import UpdateFailed  # noqa: E402


class _Response:
    """Réponse aiohttp bouchonnée : awaitable et utilisable en `async with`.

    Elle rend des **octets**, comme aiohttp : c'est `read()` que le
    coordinateur appelle depuis que `text()` a été identifié comme la cause de
    l'échec de configuration (il décode en strict une page qui n'est pas de
    l'UTF-8 valide). Un bouchon qui rendrait directement du texte ne pourrait
    pas attraper cette classe de bug.
    """

    def __init__(self, html: str | bytes) -> None:
        self._raw = html.encode("utf-8") if isinstance(html, str) else html

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def raise_for_status(self) -> None:
        return None

    #: Le site annonce `charset=utf-8` — y compris quand c'est faux.
    charset = "utf-8"

    async def read(self) -> bytes:
        return self._raw


class _Session:
    """Session aiohttp bouchonnée servant toujours la même page."""

    def __init__(self, html: str | bytes) -> None:
        self._html = html

    async def get(self, url, headers=None):  # noqa: ARG002
        return _Response(self._html)


class _Hass:
    """Home Assistant bouchonné : session figée, executor synchrone."""

    def __init__(self, html: str | bytes) -> None:
        self.session = _Session(html)

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _make(html: str | bytes, station_id: str = "000FU", interval: int = 10):
    """Coordinateur prêt à l'emploi, sans planificateur."""
    hass = _Hass(html)
    coordinator = InfoclimatCoordinator(hass, station_id, interval)
    return coordinator, hass


def run(coro):
    """Exécute une coroutine sans plugin asyncio."""
    return asyncio.run(coro)


# ───────────────────────────── Chemin nominal ─────────────────────────────


def test_cycle_nominal_annote_la_station():
    coordinator, _ = _make(load_fixture("station_pluie.html"))
    data = run(coordinator._async_update_data())

    assert data["temperature"] == 12.4
    assert data["pluie_24h"] == 12.4

    # Le coordinateur ajoute l'identité et l'URL de la station
    assert data["station_id"] == "000FU"
    assert data["station_url"].endswith("/000FU/000FU.html")
    # ...et l'âge du relevé, calculé à partir de l'horodatage d'émission
    assert data["age_releve_minutes"] > 0


def test_url_n_embarque_qu_un_seul_identifiant():
    """Le slug de l'URL est arbitraire : le site redirige vers le bon."""
    coordinator, _ = _make("", station_id="00052")
    assert coordinator.station_url.endswith("/00052/00052.html")


# ──────────────────────── Traduction des erreurs ────────────────────────


@pytest.mark.parametrize(
    ("error", "attendu"),
    [
        (StationWithoutDataError("x"), "aucune donnée temps réel"),
        (ObservationTableNotFoundError("x"), "tableau des relevés est introuvable"),
        (EmptyObservationError("x"), "aucun relevé"),
    ],
)
def test_chaque_echec_est_explique(error, attendu):
    coordinator, _ = _make("")
    assert attendu in coordinator._explain(error)


def test_erreur_inconnue_reste_lisible():
    coordinator, _ = _make("")
    message = coordinator._explain(coordinator_module.InfoclimatParseError("bizarre"))
    assert "bizarre" in message


def test_station_muette_remonte_un_update_failed():
    coordinator, _ = _make(load_fixture("station_sans_donnees.html"))
    with pytest.raises(UpdateFailed, match="aucune donnée temps réel"):
        run(coordinator._async_update_data())


def test_le_message_d_erreur_dit_depuis_quand():
    """Le journal doit répondre à « pourquoi ma station est morte ? » sans
    qu'on ait à ouvrir la page soi-même."""
    coordinator, _ = _make(load_fixture("station_sans_donnees.html"))
    with pytest.raises(UpdateFailed, match=r"dernier relevé publié le 5 mai 2026"):
        run(coordinator._async_update_data())


def test_le_cycle_nominal_expose_l_etat_de_la_station():
    coordinator, _ = _make(load_fixture("station_pluie.html"))
    data = run(coordinator._async_update_data())
    assert data["station_status"] == "en ligne"
    assert data["station_last_report"] == "2 octobre 2026, 11h30"


# ──────────────────────── Blocage anti-robot ────────────────────────


def test_blocage_anti_robot_espace_les_requetes():
    """Le message doit dire ce qui se passe, et la cadence doit ralentir :
    insister ne ferait qu'aggraver le blocage."""
    coordinator, _ = _make(load_fixture("station_antibot.html"), interval=10)
    assert coordinator.update_interval == timedelta(minutes=10)

    with pytest.raises(UpdateFailed, match="anti-robot"):
        run(coordinator._async_update_data())

    assert coordinator.update_interval == coordinator_module.ANTIBOT_BACKOFF


def test_cadence_restauree_des_qu_un_releve_passe():
    coordinator, hass = _make(load_fixture("station_antibot.html"), interval=10)
    with pytest.raises(UpdateFailed):
        run(coordinator._async_update_data())

    # La station redevient lisible
    hass.session = _Session(load_fixture("station_pluie.html"))
    data = run(coordinator._async_update_data())

    assert data["temperature"] == 12.4
    assert coordinator.update_interval == timedelta(minutes=10)


def test_un_intervalle_long_n_est_pas_raccourci():
    """Un utilisateur ayant déjà configuré 45 min ne doit pas se retrouver
    avec un intervalle plus court après un blocage."""
    coordinator, _ = _make(load_fixture("station_antibot.html"), interval=45)
    with pytest.raises(UpdateFailed):
        run(coordinator._async_update_data())
    assert coordinator.update_interval == timedelta(minutes=45)


# ─────────────────────── Décodage de la page reçue ───────────────────────


def _page_en_latin1() -> bytes:
    """La page telle que le site la publie vraiment.

    Infoclimat annonce `charset=utf-8` dans ses en-têtes et sert malgré tout
    des octets Latin-1 : sur la vraie page, `0xe0` (« à ») apparaît deux fois.
    On reproduit fidèlement ce mélange en remplaçant un « é » UTF-8 par son
    équivalent Latin-1.
    """
    brut = load_fixture_bytes("station_pluie.html")
    assert b"\xc3\xa9" in brut, "la fixture doit contenir un caractère accentué"
    return brut.replace(b"\xc3\xa9", b"\xe9", 1)


def test_page_latin1_ne_bloque_plus_le_cycle():
    """Régression : `response.text()` levait `UnicodeDecodeError` sur cette
    page. L'exception n'était ni une `aiohttp.ClientError` ni une erreur de
    parsing, donc elle traversait les `except`, faisait échouer la
    configuration, et **toutes les entités restaient indisponibles** — sans
    rien dans le message qui permette de comprendre."""
    coordinator, _ = _make(_page_en_latin1())
    data = run(coordinator._async_update_data())

    assert data["temperature"] == 12.4
    assert data["pluie_24h"] == 12.4


class _ReponseIllisible:
    """Réponse dont la lecture lève une erreur d'encodage."""

    charset = "utf-8"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def raise_for_status(self) -> None:
        return None

    async def read(self) -> bytes:
        raise UnicodeDecodeError("utf-8", b"\xe0", 0, 1, "invalid continuation byte")


class _SessionIllisible:
    async def get(self, url, headers=None):  # noqa: ARG002
        return _ReponseIllisible()


def test_erreur_d_encodage_devient_un_message_lisible():
    """Ceinture et bretelles : si un décodage échouait malgré tout, l'échec
    doit ressortir en `UpdateFailed` expliqué. C'est précisément ce qui
    manquait — l'exception brute traversait les `except` et faisait échouer la
    configuration, laissant toutes les entités indisponibles sans explication."""
    coordinator, hass = _make("")
    hass.session = _SessionIllisible()
    with pytest.raises(UpdateFailed, match="injoignable"):
        run(coordinator._async_update_data())


# ──────────────────────── Fraîcheur du relevé ────────────────────────


def test_releve_frais_est_age():
    coordinator, _ = _make("")
    data = {"obs_time_utc": datetime.now(timezone.utc).isoformat(timespec="minutes")}
    coordinator._check_freshness(data)
    assert data["age_releve_minutes"] == 0


def test_releve_ancien_signale_mais_servi(caplog):
    """Un relevé figé reste servi : l'âge est exposé, l'alerte est écrite,
    mais l'entité ne disparaît pas — une station peut publier par à-coups."""
    coordinator, _ = _make("")
    old = datetime.now(timezone.utc) - timedelta(hours=5)
    data = {"obs_time_utc": old.isoformat(timespec="minutes")}

    with caplog.at_level("WARNING"):
        coordinator._check_freshness(data)

    assert data["age_releve_minutes"] == 300
    assert "station en retard" in caplog.text


def test_releve_sans_horodatage_signale():
    coordinator, _ = _make("")
    data: dict = {}
    coordinator._check_freshness(data)
    assert "age_releve_minutes" not in data


def test_horodatage_sans_fuseau_suppose_utc():
    coordinator, _ = _make("")
    old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=30)
    data = {"obs_time_utc": old.isoformat(timespec="minutes")}
    coordinator._check_freshness(data)
    assert data["age_releve_minutes"] == 30


# ──────────────────────── Formatage de l'âge ────────────────────────


@pytest.mark.parametrize(
    ("delta", "attendu"),
    [
        (timedelta(minutes=25), "25 min"),
        (timedelta(hours=3), "3 h"),
        (timedelta(days=2), "2 j"),
    ],
)
def test_format_age(delta, attendu):
    assert _format_age(delta) == attendu


def test_le_module_ne_contient_plus_de_parsing():
    """Garde-fou : toute règle de parsing doit vivre dans le paquet dédié."""
    source = pathlib.Path(coordinator_module.__file__).read_text(encoding="utf-8")
    for interdit in ("re.findall", "re.search", "re.compile", "<tr", "strip_tags"):
        assert interdit not in source, f"du parsing a fui dans coordinator.py : {interdit}"
