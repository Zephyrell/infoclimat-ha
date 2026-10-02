"""Micro-DOM sans dépendance externe, bâti sur ``html.parser`` (stdlib).

Pourquoi pas des expressions régulières ?
-----------------------------------------
Infoclimat imbrique du HTML *à l'intérieur de valeurs d'attributs* :

    <td>0 mm/1h
      <a title="<table><tr><td>Pluie/24h :</td><td>0.2mm</td></tr></table>">…</a>
    </td>

et même des balises *à l'intérieur* d'une balise ouvrante :

    <a title="Température sous abri,<br />relevée à 2m">Tempé<span>rature</span></a>

Tout regex appliqué au HTML brut voit ces fragments comme de vraies balises :
il coupe les lignes de tableau au milieu, décale les colonnes et fait échouer
le parsing dès qu'il pleut (le tooltip « Pluie/24h » apparaît alors).

Un tokenizer HTML, lui, ne regarde jamais l'intérieur d'une valeur d'attribut.
C'est la seule base saine pour parser cette page.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Iterator

__all__ = [
    "Node",
    "parse_html",
    "collapse_whitespace",
    "normalize_label",
    "SPACE_TAGS",
    "VOID_TAGS",
]

#: Balises sans contenu ni fermeture.
VOID_TAGS = frozenset(
    {
        "area", "base", "br", "col", "command", "embed", "hr", "img",
        "input", "keygen", "link", "meta", "param", "source", "track", "wbr",
    }
)

#: Balises considérées comme un séparateur de mots dans :meth:`Node.text`.
#: Sans cela ``<br />`` collerait « km/h » et « raf. » en « km/hraf. ».
SPACE_TAGS = frozenset(
    {
        "address", "article", "blockquote", "br", "dd", "div", "dl", "dt",
        "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
        "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol",
        "p", "pre", "section", "table", "tbody", "td", "tfoot", "th",
        "thead", "tr", "ul",
    }
)

#: Balises dont le contenu n'est jamais du texte visible.
SKIP_TEXT_TAGS = frozenset({"script", "style"})

_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^0-9a-z]+")
_ACCENTS = str.maketrans(
    "àâäáãåçéèêëíìîïñóòôöõúùûüýÿ°²",
    "aaaaaaceeeeiiiinooooouuuuyy  ",
)


class Node:
    """Nœud d'un arbre HTML minimaliste.

    Seules les opérations utiles au scraping sont exposées : pas de CSS
    selector engine, pas de sérialisation, pas de mutation complexe.
    """

    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs=None, parent: "Node | None" = None) -> None:
        self.tag = tag
        self.attrs: dict[str, str] = {
            (k or "").lower(): (v if v is not None else "") for k, v in (attrs or ())
        }
        self.children: list["Node | str"] = []
        self.parent = parent

    # ─────────────────────────── Navigation ───────────────────────────

    def iter(self, *tags: str) -> Iterator["Node"]:
        """Parcours préfixe de tous les descendants (filtre optionnel)."""
        for child in self.children:
            if isinstance(child, Node):
                if not tags or child.tag in tags:
                    yield child
                yield from child.iter(*tags)

    def find_all(self, *tags: str) -> list["Node"]:
        """Tous les descendants portant l'une des balises données."""
        return list(self.iter(*tags))

    def find(self, *tags: str) -> "Node | None":
        """Premier descendant portant l'une des balises données."""
        for node in self.iter(*tags):
            return node
        return None

    def walk(self) -> Iterator["Node"]:
        """Parcours de tous les descendants, sans filtre."""
        return self.iter()

    # ──────────────────────────── Contenu ────────────────────────────

    def text(self) -> str:
        """Texte visible du nœud, **hors attributs**.

        C'est le point clé : ``title="<table>…"`` ne pollue jamais le texte.
        """
        parts: list[str] = []
        self._collect_text(parts)
        return collapse_whitespace("".join(parts))

    def _collect_text(self, parts: list[str]) -> None:
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
                continue
            if child.tag in SKIP_TEXT_TAGS:
                continue
            if child.tag in SPACE_TAGS:
                parts.append(" ")
            child._collect_text(parts)
            if child.tag in SPACE_TAGS:
                parts.append(" ")

    def element_segments(self, tag: str) -> list[tuple["Node", str]]:
        """Associe chaque descendant ``tag`` au texte qui le suit.

        Sert aux cellules qui empilent plusieurs valeurs étiquetées, comme la
        ligne DJU : ``<b>0.1</b> chauffe … <b>1.2</b> froid``. Le contexte
        s'arrête au ``tag`` suivant.
        """
        segments: list[tuple[Node, str]] = []
        current: Node | None = None
        buffer: list[str] = []

        def flush() -> None:
            if current is not None:
                segments.append((current, collapse_whitespace("".join(buffer))))

        for item in self._flatten():
            if isinstance(item, Node):
                if item.tag == tag:
                    flush()
                    current = item
                    buffer = []
                elif item.tag in SPACE_TAGS:
                    buffer.append(" ")
            else:
                buffer.append(item)
        flush()
        return segments

    def _flatten(self):
        """Contenu du sous-arbre en ordre documentaire (chaînes et nœuds)."""
        for child in self.children:
            if isinstance(child, str):
                yield child
            else:
                yield child
                yield from child._flatten()

    def own_text(self) -> str:
        """Texte des enfants directs uniquement (sans descendre)."""
        return collapse_whitespace(
            "".join(c for c in self.children if isinstance(c, str))
        )

    def get(self, name: str, default: str | None = None) -> str | None:
        """Valeur d'un attribut (insensible à la casse)."""
        return self.attrs.get(name.lower(), default)

    def classes(self) -> set[str]:
        """Classes CSS du nœud."""
        return set((self.get("class") or "").split())

    def has_class(self, name: str) -> bool:
        """Le nœud porte-t-il cette classe CSS ?"""
        return name in self.classes()

    def attr_contains(self, name: str, needle: str) -> bool:
        """L'attribut contient-il cette sous-chaîne ?"""
        return needle in (self.get(name) or "")

    def is_element(self) -> bool:
        """True pour un nœud élément (par opposition au nœud racine)."""
        return self.tag != "#document"

    # ──────────────────────────── Mutation ───────────────────────────

    def detach(self) -> None:
        """Détache le nœud de son parent."""
        if self.parent is not None:
            try:
                self.parent.children.remove(self)
            except ValueError:
                pass
            self.parent = None

    def clone(self) -> "Node":
        """Copie profonde (les parents ne sont pas recopiés)."""
        copy = Node(self.tag, self.attrs.items())
        for child in self.children:
            if isinstance(child, str):
                copy.children.append(child)
            else:
                sub = child.clone()
                sub.parent = copy
                copy.children.append(sub)
        return copy

    def __repr__(self) -> str:  # pragma: no cover - aide au débogage
        attrs = " ".join(f"{k}={v[:24]!r}" for k, v in list(self.attrs.items())[:3])
        return f"<{self.tag} {attrs}>" if attrs else f"<{self.tag}>"


class _DomBuilder(HTMLParser):
    """Construit un :class:`Node` racine à partir d'un flux HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self._stack: list[Node] = [self.root]

    def handle_starttag(self, tag, attrs) -> None:
        node = Node(tag, attrs, self._stack[-1])
        self._stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs) -> None:
        self._stack[-1].children.append(Node(tag, attrs, self._stack[-1]))

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(data)

    def handle_endtag(self, tag) -> None:
        if tag in VOID_TAGS:
            return
        for depth in range(len(self._stack) - 1, 0, -1):
            if self._stack[depth].tag == tag:
                del self._stack[depth:]
                return
        # Balise fermante orpheline : ignorée (le HTML réel en est truffé).


def parse_html(html: str) -> Node:
    """Transforme une chaîne HTML en arbre de :class:`Node`.

    Tolérant par construction : les balises non fermées ou orphelines ne
    lèvent jamais d'exception.
    """
    builder = _DomBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


def collapse_whitespace(value: str) -> str:
    """Réduit toute suite d'espaces (y compris insécables) à une espace."""
    return _WHITESPACE_RE.sub(" ", value).strip()


def normalize_label(value: str) -> str:
    """Normalise un libellé pour la comparaison : minuscules, sans accents.

    ``"Pt. de rosée"`` → ``"pt de rosee"`` ; ``"Bio-météo"`` → ``"bio meteo"``.
    """
    value = value.lower().translate(_ACCENTS)
    value = _NON_WORD_RE.sub(" ", value)
    return collapse_whitespace(value)
