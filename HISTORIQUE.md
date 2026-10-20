# Historique technique

Journal des décisions et des découvertes sur le site Infoclimat, en
complément du `git log`. Le *comment* est dans le code, le *pourquoi* est ici.

À tenir à jour : une entrée par changement notable, la plus récente en haut.
Toute affirmation sur le comportement du site doit avoir été vérifiée sur une
page réelle — le mentionner sinon.

---

## 2026-10-20 — Le « Cumul du jour » n'est pas le cumul 24 h (v1.4.1)

Signalé par Zephyrell : Home Assistant affichait **21 mm** de cumul 24 h quand
le site en annonçait **71**. Vérifié sur la page réelle de `000FU` à 20h09,
avec l'URL exacte utilisée par l'intégration : `pluie_24h` valait bien
**71.2 mm**, et chaque version publiée (1.3.0, 1.3.1, 1.3.2, 1.4.0) donne le
même résultat sur cette page. Le calcul ne « démarre » donc pas au relevé
courant et n'a rien perdu de la nuit.

Les 21 mm sont le **« Cumul du jour »** de la climatologie du site. Ce n'est
pas une fenêtre de 24 h : le site l'annote lui-même « **6h à 6h (J+1)** »,
« partiel » — la journée synoptique, en UTC (soit 8h–8h en heure d'été, 7h–7h
en heure d'hiver). À 20h09, ce cumul valait 21.0 mm, exactement comme
`Pluie/12h` : coïncidence de l'heure, pas un compteur qui repart au relevé.

Deux corrections pour que la confusion ne se reproduise pas :

- le capteur `pluie_cumul_jour` s'appelle désormais **« Pluie cumul jour
  (6h–6h UTC) »** ;
- le site publie dans sa climatologie un **« Cumul 24h glissantes » en direct**
  (71.2 mm sur `000FU`), que l'intégration reprend tel quel pour `pluie_24h`.
  Il est appliqué après la reconstitution et la remplace ; celle-ci reste le
  repli quand la section est absente (station sans pluviomètre, page
  incomplète).

## 2026-10-20 — Pluie : trois mesures, un seul capteur qui se figeait (v1.3.2 → v1.4.0)

### Le symptôme

Signalé par Zephyrell : les capteurs de pluie « ne semblent plus évoluer », et
le cumul 24 h n'apparaît que dans les cases des heures piles. Demande
explicite, par ailleurs : exposer la **pluie instantanée**.

### Ce que la cellule contient réellement

La cellule « Pluie » mêle **trois mesures** que 1.3.2 avait prises pour deux :

```html
<td>1 <span>mm/10mn</span>                      ← cumul des 10 dernières minutes
  <a title="<table>
      <tr><td>Intensité max/1h :</td><td>10.2mm/h</td></tr>   ← max de l'heure
      <tr><td>Intensité instantanée :</td><td>4.8mm/h</td></tr>
      <tr><td>Pluie/10mn :</td><td>1mm</td></tr>
    </table>">
  <span>10.2 <span>mm/h</span></span>            ← le même max, en clair
</td>
```

Vérifié sur la page réelle : le `mm/h` affiché en clair est **égal** à
« Intensité max/1h » de l'infobulle, à chaque ligne. Ce n'est ni un cumul
horaire ni un débit instantané.

### L'erreur de 1.3.2

`parse_rain_tooltip` cherchait les libellés avec `_HOURS_RE = (\d+)\s*h`,
c'est-à-dire « un nombre suivi de h », **n'importe où** dans le libellé.
« Intensité max/1h » correspondait donc, et devenait `pluie_1h`. Le capteur
« Pluie (1h) » de 1.3.2 publiait en réalité l'intensité maximale de l'heure :
une valeur qui ne bouge que lorsqu'un nouveau maximum tombe, d'où l'impression
d'un capteur figé. Sur la page du 20 octobre, elle est restée à 10.2 pendant
quarante minutes alors qu'il tombait 1 mm toutes les dix minutes.

### Les cumuls, eux, n'étaient publiés qu'à l'heure pile

`Pluie/3h`, `/6h`, `/12h` et `/24h` n'existent que sur les lignes horaires.
Quand la ligne retenue était déciminutée — c'est-à-dire presque toujours —
les capteurs de cumul disparaissaient, ou étaient reportés en bloc depuis la
ligne horaire par `_carry_slow_fields`.

Arithmétique vérifiée sur la page réelle :

- 05h00 (7.2) + 06h00 (3.8) + 07h00 (4.4) = 15.4 = `Pluie/3h` de 07h00 ;
- 06h10…06h50 = 4.0, plus `Pluie/10mn` de 07h00 (0.4) = 4.4 = `mm/1h` de 07h00.

Autrement dit : une ligne à l'heure `T` couvre `(T − 10 min, T]`, et la ligne
horaire couvre l'heure qui s'achève, `Pluie/10mn` en étant le dernier
dixième.

### Le correctif

L'extracteur ne calcule plus aucun total : il restitue séparément le cumul
d'intervalle, l'intensité max et l'intensité instantanée. Une nouvelle étape,
`_derive_rain_totals`, recompose les cumuls au niveau de la page :

- **cumul 3/6/12/24 h** = valeur de la dernière ligne horaire + somme des
  cumuls déciminutés postérieurs (la formule demandée) ;
- **cumul 1 h** = somme exacte des intervalles de 10 minutes de la fenêtre,
  la ligne horaire contribuant pour ses `Pluie/10mn` ;
- une cellule vide sur un relevé déciminuté vaut **0 mm** dès lors que la
  station possède un pluviomètre — c'est ainsi que le site représente l'absence
  de pluie, et c'est ce qui effaçait les cumuls auparavant ;
- au-delà d'une heure après la ligne horaire, aucune extension : des trous de
  publication rendraient l'estimation fausse (comportement conservé de la
  reprise, test `station_pluie_perimee.html`).

Les cumuls 3/6/12/24 h débordent de moins d'une heure : l'incrément sortant
par le haut de la fenêtre n'est pas publié. C'est documenté dans le README.

### Changement cassant

**« Pluie (1h) » passe de `mm/h` à `mm`**, parce que c'est un cumul et non une
intensité. L'`unique_id` ne change pas : l'entité survit à la mise à jour, mais
son unité et ses statistiques long terme changent. Deux nouveaux capteurs :
« Pluie instantanée » (`precipitation_intensity`, mm/h, actif) et
« Intensité max (1h) » (mm/h, inactif par défaut). `pluie_max_1h` de la
climatologie passe aussi en `precipitation_intensity`, son unité `mm/h` étant
invalide pour `precipitation`.

### État vérifié

- 52 tests, dont deux nouvelles fixtures au format réel du site
  (`station_pluie_deciminutee.html`, `station_pluie_seche.html`).
- Page réelle `000FU` à 07h50 : `pluie_1h = 4.4 mm`, `pluie_24h = 67.8 mm`
  (63.8 à 07h00 + 4.0 depuis), `pluie_instantannee = 4.8 mm/h`,
  `pluie_intensite_max_1h = 10.2 mm/h`.
- Page réelle `00001`, sèche : `pluie_1h = 0.0`, `pluie_24h = 0.2`,
  instantanée `0.0`.

---

## 2026-10-16 — Le capteur « Pluie » surestimait d'un facteur 6 (v1.3.1 → v1.3.2)

### Le symptôme

Signalé par Zephyrell après la remise en service : Home Assistant affiche
`0.4 mm/h` alors que le site affiche `0.4 mm/10min`. L'échelle du site change
selon les relevés.

### La cause

La cellule « Pluie » contient **deux mesures distinctes** :

```html
<td>
  0.4 <span class="tab-units-v">mm/10mn</span>   ← cumul sur l'intervalle de la ligne
  <br>
  <a class="button-rr-pluvio" title="<table…>…</table>">  ← cumuls 3/6/12/24 h
  <span>2.6 <span class="tab-units-v">mm/h</span></span>   ← débit calculé par le site
</td>
```

Le premier nombre est un cumul dont **l'unité dépend de la ligne** : `mm/10mn`
sur les relevés déciminutés, `mm/1h` sur les lignes horaires. L'extracteur
prenait ce premier nombre et l'étiquetait `mm/h` : à 0,4 mm par 10 minutes, la
pluie réelle est de 2,4 mm/h, six fois plus.

Second défaut dans la même fonction : `parse_rain_tooltip` lit un `Pluie/1h`
**juste** (2,6 mm sur la dernière heure), mais `result.setdefault(...)` ne
l'écrasait pas — la bonne valeur était donc lue puis jetée, au profit du
cumul déciminuté.

Vérifié sur la page réelle : le `mm/h` affiché par le site est **toujours
égal** au `Pluie/1h` de l'infobulle quand celle-ci est présente. C'est bien une
intensité horaire, pas une accumulation à l'instant.

### Le correctif

`_rain` lit la cellule en deux temps, au lieu de prendre son premier nombre :

1. le débit explicite `Xmm/h` → `pluie_1h` ;
2. à défaut, le `Pluie/1h` de l'infobulle ;
3. à défaut, le cumul converti : `cumul × 60 / intervalle_en_minutes`.

Les deux formes de la cellule sont conservées : `pluie_cumul_intervalle` et
`pluie_intervalle_min` deviennent des attributs du capteur « Pluie (1h) »,
donc rien n'est perdu et l'unité variable reste visible.

### État vérifié

- 52 tests. Six formes de cellule couvertes : `mm/10mn` + débit, `mm/1h` +
  débit, débit seul (`4.8mm/h`), cumul seul (`0.2 mm/10mn` → 1,2 mm/h),
  `0 mm/1h`, cellule vide.
- Site réel : `000FU` à 19h50 affiche `0.4 mm/10mn 2.6mm/h` → `pluie_1h=2.6`,
  cumul `0.4 mm sur 10 min`. `00001`, sec, → `0.0` avec les cumuls d'infobulle.

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
