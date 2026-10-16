"""Configuration pytest commune.

Le paquet ``parsing`` est autonome (aucun import de Home Assistant) : on
l'ajoute directement au ``sys.path`` pour pouvoir le tester sans avoir HA
installé dans l'environnement de test.
"""

from __future__ import annotations

import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]
PARSING_PARENT = ROOT / "custom_components" / "infoclimat"

# `parsing` est importable seul — c'est le point clé : le moteur de parsing
# ne dépend pas de Home Assistant et se teste donc sans lui.
if str(PARSING_PARENT) not in sys.path:
    sys.path.insert(0, str(PARSING_PARENT))

# La couche intégration (`infoclimat.*`) s'importe, elle, avec les bouchons
# Home Assistant installés par `stubs.install()`.
if str(ROOT / "custom_components") not in sys.path:
    sys.path.insert(0, str(ROOT / "custom_components"))


def load_fixture(name: str) -> str:
    """Renvoie le HTML d'une fixture de ``tests/fixtures``."""
    return (FIXTURES / name).read_text(encoding="utf-8")


def load_fixture_bytes(name: str) -> bytes:
    """Renvoie les octets bruts d'une fixture, sans décodage."""
    return (FIXTURES / name).read_bytes()
