# Historique technique

Journal des décisions et des découvertes sur le site Infoclimat, en
complément du `git log`. Le *comment* est dans le code, le *pourquoi* est ici.

À tenir à jour : une entrée par changement notable, la plus récente en haut.
Toute affirmation sur le comportement du site doit avoir été vérifiée sur une
page réelle — le mentionner sinon.

---

## 2026-10-16 — Toutes les entités indisponibles (v1.3.0 → v1.3.1)

### Le symptôme

Signalé par Zephyrell : **toutes les entités indisponibles**, avant comme après
la mise à jour en `1.3.0`. Le message affiché par Home Assistant :

```
Échec de la configuration, nouvel essai:
'utf-8' codec can't decode byte 0xe0 in position 108369: invalid continuation byte
```

### La cause

**Le site annonce `charset=utf-8` et publie du Latin-1.** Vérifié sur la page
réelle de `000FU` : l'en-tête dit `content-type: text/html; charset=utf-8`,
il n'y a aucun `<meta charset>` pour se rattraper, et deux octets `0xe0`
(« à ») traînent dans la phrase « une bruine faible et continue à la station ».
`cp1252` et `iso-8859-1` décodent la page entière sans broncher.

Or `aiohttp` fait confiance à l'en-tête : `response.text()` décode en
**strict** et lève `UnicodeDecodeError`.

Le bug tenait à cette exception, et à ce qu'elle n'est **ni** une
`aiohttp.ClientError` **ni** une erreur de parsing. Les `except` de
`_async_fetch` la laissaient donc passer. Elle remontait jusqu'à
`async_config_entry_first_refresh()`, qui la transformait en échec de
configuration : l'intégration n'était jamais configurée, aucune entité n'était
créée, et Home Assistant se contentait de réessayer indéfiniment. D'où le
tableau : **panne totale, permanente, sans indice sur la cause**, identique
dans toutes les versions.

### Pourquoi personne ne l'avait vu

`test_scraper.py` décodait ainsi :

```python
return response.read().decode("utf-8", errors="replace")
```

`errors="replace"` — le diagnostic **réparait la page en silence** et
l'intégration levait. Le même jour, le même site, la même page : l'un
fonctionnait, l'autre non, et j'ai pendant des heures conclu de l'un que
l'autre allait bien. C'est la vraie leçon de cette panne : **un outil de
diagnostic qui ne décode pas comme le code testé ne diagnostique rien.**
`test_scraper.py` utilise désormais `decode_page`, comme l'intégration.

### Le correctif

`parsing/encoding.py` — `decode_page(raw, charset)`, la seule frontière où des
octets deviennent du texte, et elle ne lève jamais : jeu de caractères annoncé
d'abord, puis `utf-8`, toujours en `errors="replace"`. Les deux octets fautifs
sont hors du tableau des relevés (vérifié : 0 octet invalide dans le tableau),
et les mesures sont numériques — le remplacement ne coûte rien.

Le champ de configuration (`config_flow.py`) souffrait du même défaut, au même
endroit : c'est lui qui bloquait l'ajout de la station.

### Ce qui a été essayé avant, et qui était faux

À consigner pour ne pas refaire le chemin :

- **Le tag `1.0.0` et l'absence de release GitHub** → vrai problème, corrigé,
  mais sans rapport avec cette panne : `parsing/` était bien présent sur le
  serveur.
- **Un faux `User-Agent` (Chrome) sur une pile TLS Python, filtré par
  Cloudflare** (`188.114.96.2`) → testé depuis le serveur avec l'UA exact de
  l'intégration : `HTTP 200`, page complète. Faux.
- **Le réseau / DNS de la VM** → `curl` y répondait `200` avec 297 Ko.
- **La lenteur du parseur** → 0,04 s mesuré sur les 297 Ko, très loin du délai
  de 15 s.

Le fil rouge de ces fausses pistes : tout était testé **depuis le Mac**, jamais
depuis la VM, et avec un décodeur plus permissif que celui de l'intégration.

### État vérifié

- 45 tests (39 + 6). Les 6 nouveaux **échouent si l'on réintroduit le décodage
  strict** — vérifié en le réintroduisant : 4 échecs avec `UnicodeDecodeError`.
- Vrai coordinateur, octets bruts du serveur, deux stations : `000FU` → 17,4 °C ;
  `00001` → 12,3 °C avec `pluie_1h`, `pluie_3h`, `pluie_6h`, `pluie_12h` et
  `pluie_24h` tous lus (le cas de l'infobulle).

---

## 2026-10-02 — Refonte du parsing (v1.2.0 → v1.3.0)

### Le symptôme

L'intégration tombait en panne dès qu'il pleuvait. Le tableau « semblait
changer de structure en fonction de la météo ».

### La cause racine

Le tableau ne change pas de structure : c'est **son contenu qui contient du
HTML**. Quand il a plu dans les 24 h, Infoclimat ajoute une infobulle à la
cellule « Pluie », et le contenu de cette infobulle est une table HTML logée
dans l'attribut `title` du lien :

```html
<td>2.4 mm/1h<br />
  <a title="<table class='minitable-details'>
              <tr><td><b>Pluie/3h :</b></td><td>3.6mm</td></tr>
              <tr><td><b>Pluie/24h :</b></td><td>12.4mm</td></tr>
            </table>">
```

Le parseur découpait les lignes avec `<tr[^>]*>(.*?)</tr>`. Cette expression
s'arrête au **premier `</tr>` rencontré**, y compris celui qui dort à
l'intérieur de l'attribut. La ligne est alors coupée en fragments qui
n'atteignent plus les 7 cellules exigées par le garde `len(cells) >= 7`, et le
relevé le plus récent est écarté.

En vue horaire — où chaque ligne porte une mesure de pluie — **plus aucune
ligne n'était exploitable** : c'était la panne totale. En vue 10 minutes, seules
les lignes horaires disparaissaient, ce qui servait silencieusement des valeurs
plus anciennes.

Reproduit sur la fixture `station_pluie.html` : l'ancien code retient la ligne de
**11h20** (`temperature=12.6`, `pluie_1h=None`) au lieu de celle de 11h30
(`12.4`, `2.4`). Le test
`test_regression_l_ancien_parser_perdait_la_ligne_pluvieuse` conserve cet ancien
découpage pour documenter le bug.

### Deux causes secondaires, découvertes en route

- **`_strip_tags` fuyait.** `re.sub(r"<[^>]+>", …)` s'arrête au `>` d'un
  `<br />` situé dans un attribut : le texte des infobulles se déversait dans
  les libellés de colonnes, et `Bio-météo` absorbait la description de deux
  autres colonnes.
- **Les DJU étaient tronqués.** `(\d+)\s*chauffe` lisait `1` dans
  `0.1 chauffe`, et `(\d+)\s*froid` lisait `2` dans `1.2 froid` — deux valeurs
  qui cohabitent dans une seule cellule.

### Une troisième cause, trouvée en testant

En interrogeant le site en rafale pendant la mise au point, une **page
anti-robot** est apparue : même `<title>`, page valide, **aucun tableau**,
remplacé par un reCAPTCHA et le message « votre requête était potentiellement
automatisée ». Elle était indiscernable d'une station hors service. C'est très
probablement la seconde raison des coupures observées en production.

### Ce qui a été construit

Le parsing est un paquet en couches, `custom_components/infoclimat/parsing/` :

| Module | Responsabilité |
|---|---|
| `dom.py` | tokenizer HTML (stdlib) → arbre de nœuds |
| `tables.py` | localiser le tableau : `id`, puis classe, puis conteneur |
| `columns.py` | en-tête → **rôle logique**, via registre d'alias normalisés |
| `fields.py` | un extracteur pur par rôle |
| `climatology.py` | table « climatologie du jour » |
| `station.py` | fiche d'identité et état de la station |
| `notices.py` | popups et fenêtres d'information |
| `antibot.py` | détection de la page anti-robot |
| `report.py` | traçabilité de chaque cycle |

`coordinator.py` ne contient plus une seule règle de parsing (un test le
vérifie), et délègue au paquet. Les échecs remontent en exceptions nommées
(`AntiBotChallengeError`, `StationWithoutDataError`,
`ObservationTableNotFoundError`, `EmptyObservationError`) traduites en messages
explicites pour l'utilisateur.

### Décisions

- **Tokenizer maison plutôt qu'une dépendance.** `beautifulsoup4`/`lxml`
  auraient réglé le problème en trois lignes, mais l'intégration revendique
  « aucune dépendance » et HACS pénalise les dépendances inutiles. Le
  `HTMLParser` de la bibliothèque standard suffit pour lire un arbre.
- **Rôles plutôt qu'index de colonnes.** `_build_column_map` existait déjà et
  lisait les en-têtes — la bonne idée, mais elle s'appuyait sur un
  `_strip_tags` cassé et les extracteurs restaient positionnels. Le registre
  d'alias normalise accents et ponctuation, et une colonne inconnue est
  signalée, jamais devinée.
- **Ligne choisie sur son horodatage réel**, plus sur sa position ni sur un
  « nombre de cellules suffisant ». C'est l'erreur de conception qui rendait le
  bug possible.
- **Report des mesures à cadence lente.** La pluviométrie est horaire, la
  température déciminutéenne : la valeur la plus récente connue est reprise du
  relevé précédent, avec péremption au bout d'une heure (un cumul nul reste
  valable indéfiniment).
- **Exceptions explicites plutôt que `None`.** Un scraping qui casse en silence
  est pire qu'un scraping qui échoue. Chaque cycle produit un rapport
  (`INFO` : résumé, `DEBUG` : détail).
- **Station libre.** `/…/temps-reel/<slug>/<ID>.html` redirige en 302 vers le bon
  slug : la table `STATION_SLUGS` et sa PR obligatoire pour ajouter une station
  disparaissent. Le champ de configuration accepte aussi une URL collée.
- **Ralentissement plutôt que répétition** face au blocage anti-robot. Traiter
  la cause (la cadence) et pas seulement le symptôme.

### État vérifié

- 39 tests hors ligne (`python3 -m pytest tests/`), un par situation, sur
  fixtures dans `tests/fixtures/`.
- Pages réelles parsées : `000FU`, `00001` (infobulle pluvio présente),
  `00052` (station muette, dernier report 5 mai 2026).
- Bout-en-bout du vrai coordinateur contre le site, session aiohttp remplacée
  par urllib.

### Questions ouvertes

- **Tags et releases — résolu.** Le dépôt n'avait qu'un tag `1.0.0`,
  pointant sur le code d'avant la refonte, et **aucune release GitHub**. HACS
  peuple son sélecteur de version avec les releases : dans cet état, une
  réinstallation pouvait remettre le parseur regex cassé en place, ce qui
  ressemble trait pour trait à « l'intégration ne marche plus ». Corrigé par
  la release `1.3.0` du 16 octobre 2026. À refaire à chaque changement
  visible : tag **et** release sur `main`.
- **Portée du blocage anti-robot.** Le blocage est apparu sur une URL alors
  qu'une autre répondait normalement dans la même minute — le déclenchement
  semble lié au volume de requêtes récentes plus qu'à un quota global. À
  préciser si ça se reproduit.
- **Stations au format de tableau différent.** Le repli positionnel
  (`FALLBACK_LAYOUTS`) n'a jamais servi sur données réelles. À surveiller dans
  le rapport : `alertes=en-tête illisible : plan de colonnes positionnel
  utilisé`.

### Où regarder

- `README.md`, section « Dépannage » — les pièges du site, expliqués.
- `test_scraper.py` — diagnostic en ligne, affiche le relevé **et** son rapport.
- `tests/fixtures/` — une page figée par situation.
