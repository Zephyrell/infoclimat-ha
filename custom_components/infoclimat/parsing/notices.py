"""Modales, popups et bandeaux d'information.

Infoclimat affiche régulièrement des fenêtres à fermer (appel aux dons,
vigilance canicule, maintenance…). Elles sont construites côté client avec
Materialize et ne touchent pas au tableau des relevés — mais elles polluent
toute recherche menée à l'échelle de la page (leur texte contient des
nombres, des dates, parfois des tableaux).

On les recense pour l'affichage/diagnostic, et on les retire de l'arbre
avant les recherches globales (nom de station, climatologie).
"""

from __future__ import annotations

from dataclasses import dataclass

from .dom import Node

__all__ = ["Notice", "find_notices", "prune_notices", "is_notice"]

#: Fragments d'identifiant ou de classe signalant une fenêtre surgissante.
#: Volontairement restrictif : un faux positif ferait disparaître du contenu
#: légitime, alors qu'un bandeau oublié est sans conséquence (le parsing est
#: de toute façon cantonné au tableau des relevés).
NOTICE_HINTS = ("modal", "popup")

#: Valeurs d'attribut ``role`` signalant une fenêtre surgissante.
NOTICE_ROLES = ("dialog", "alertdialog")

_MAX_TEXT = 180


@dataclass(frozen=True)
class Notice:
    """Fenêtre d'information détectée dans la page."""

    identifier: str
    text: str

    def __str__(self) -> str:  # pragma: no cover - confort d'affichage
        return f"{self.identifier}: {self.text}"


def is_notice(node: Node) -> bool:
    """Ce nœud est-il une fenêtre surgissante / un bandeau ?"""
    if not node.is_element():
        return False
    if (node.get("role") or "").lower() in NOTICE_ROLES:
        return True
    haystack = " ".join((node.get("id") or "", node.get("class") or "")).lower()
    return any(hint in haystack for hint in NOTICE_HINTS)


def find_notices(root: Node) -> list[Notice]:
    """Recense les fenêtres d'information, sans descendre dans les imbriquées."""
    notices: list[Notice] = []
    for node in root.iter():
        if not is_notice(node):
            continue
        parent = node.parent
        while parent is not None and not is_notice(parent):
            parent = parent.parent
        if parent is not None:
            continue  # déjà couvert par une fenêtre parente

        text = node.text()
        if not text:
            continue
        notices.append(
            Notice(
                identifier=node.get("id") or node.get("class") or node.tag,
                text=text[:_MAX_TEXT],
            )
        )
    return notices


def prune_notices(root: Node) -> Node:
    """Copie de l'arbre débarrassée des fenêtres surgissantes."""
    clone = root.clone()
    for node in list(clone.iter()):
        if is_notice(node):
            node.detach()
    return clone
