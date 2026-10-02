"""Détection de la page anti-robot d'Infoclimat.

Quand le site juge les requêtes trop rapides, il renvoie **une page valide, au
même titre, mais sans aucun tableau de relevés** — remplacée par un message
d'avertissement et un reCAPTCHA. Sans détection, cette page est indiscernable
d'une station hors service, et l'intégration annonce une panne qui n'existe
pas. Ce module nomme la situation pour ce qu'elle est.
"""

from __future__ import annotations

from .dom import Node, normalize_label

__all__ = ["looks_like_antibot", "CHALLENGE_MARKERS"]

#: Extraits du message d'Infoclimat, normalisés (minuscules, sans accents).
#: Plusieurs formulations sont conservées : le site les fait varier.
CHALLENGE_MARKERS: tuple[str, ...] = (
    "potentiellement automatisee",
    "confirmer que vous n etes pas un robot",
    "fait regulierement l objet de pillages",
    "pillages de donnees",
)

#: Indices techniques, présents même si le message change de texte.
CHALLENGE_TECH_MARKERS: tuple[str, ...] = (
    "g-recaptcha",
    "recaptcha-element",
    "recaptcha/api.js",
)


def looks_like_antibot(document: Node) -> str | None:
    """La page est-elle un défi anti-robot plutôt qu'une page de station ?

    :returns: le marqueur reconnu, ou ``None`` si la page est normale.
    """
    text = normalize_label(document.text())
    for marker in CHALLENGE_MARKERS:
        if marker in text:
            return marker

    # Le message peut être reformulé : on retombe alors sur la présence du
    # reCAPTCHA, jamais sur du texte de station.
    raw = _raw_attributes(document)
    for marker in CHALLENGE_TECH_MARKERS:
        if marker in raw:
            return marker
    return None


def _raw_attributes(document: Node) -> str:
    """Attributs `class`/`id`/`src` de la page, concaténés.

    Les indices techniques vivent dans le balisage et non dans le texte
    visible : le reCAPTCHA est monté par JavaScript depuis un `div` vide.
    """
    parts: list[str] = []
    for node in document.iter():
        for key in ("class", "id", "src", "data-sitekey"):
            value = node.get(key)
            if value:
                parts.append(value)
    return " ".join(parts)
