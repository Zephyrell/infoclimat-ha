"""Décodage des octets reçus en texte.

Infoclimat annonce `charset=utf-8` dans ses en-têtes HTTP mais publie du
Latin-1 par endroits, et la page ne porte aucun `<meta charset>` pour se
rattraper. Décoder en strict lève alors `UnicodeDecodeError` :

    'utf-8' codec can't decode byte 0xe0 in position 108369

Cette exception n'est ni une `aiohttp.ClientError` ni une erreur de parsing :
elle traversait les `except` de l'intégration, faisait échouer
`async_config_entry_first_refresh`, et Home Assistant restait bloqué sur
« Échec de la configuration, nouvel essai » — **toutes les entités
indisponibles, indéfiniment**, sans que rien n'indique pourquoi.

Une page web n'est jamais une garantie : ce module est la seule frontière où
des octets deviennent du texte, et il ne lève jamais.
"""

from __future__ import annotations

__all__ = ["decode_page"]


#: Jeux de caractères essayés, dans l'ordre, quand l'en-tête ne dit rien.
_FALLBACK_ENCODINGS: tuple[str, ...] = ("utf-8",)


def decode_page(raw: bytes, charset: str | None = None) -> str:
    """Décode le corps d'une réponse HTTP en texte.

    Les octets invalides sont remplacés (`errors="replace"`) plutôt que de
    faire échouer l'appel : sur la page de Saint-Paul-Trois-Châteaux, les deux
    seuls octets fautifs sont dans une phrase de prose, hors du tableau des
    relevés — les mesures, elles, sont numériques et traversent le décodage
    sans être touchées.

    :param raw: corps de la réponse, tel que reçu.
    :param charset: jeu de caractères annoncé par le serveur, s'il y en a un.
    """
    for encoding in (charset, *_FALLBACK_ENCODINGS):
        if not encoding:
            continue
        try:
            return raw.decode(encoding, errors="replace")
        except LookupError:
            # Jeu de caractères inconnu de Python : on essaie le suivant.
            continue
    return raw.decode("utf-8", errors="replace")
