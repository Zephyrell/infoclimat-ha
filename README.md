# infoclimat-ha

Intégration Home Assistant pour récupérer les relevés météo en temps réel
des stations du réseau StatIC d'[Infoclimat](https://www.infoclimat.fr).

## Principe

Sans API, sans clé — l'intégration parse la page publique de la station
pour en extraire les données. Idéal pour les stations locales non
couvertes par la station synoptique Météo-France la plus proche.

Le parsing est **piloté par les en-têtes du tableau**, jamais par des
positions de colonnes : un changement d'ordre, l'apparition ou la
disparition d'une colonne ne cassent rien. Voir
[Architecture](#architecture).

## Capteurs

| Capteur | Device Class | Unité | Activé par défaut |
|---------|-------------|-------|-------------------|
| Température | `temperature` | °C | ✅ |
| Humidité | `humidity` | % | ✅ |
| Vent moyen | `wind_speed` | km/h | ✅ |
| Rafale de vent | — | km/h | ✅ |
| Direction du vent | — | ° | ✅ |
| Pluie (1h) | `precipitation` | mm/h | ✅ |
| Point de rosée | `temperature` | °C | ✅ |
| Bio-météo (ressentie) | — | — | ✅ |
| Pression | `pressure` | hPa | ✅ |
| Tendance pression | — | — | ✅ |
| Variation pression (3h) | `pressure` | hPa | 🔸 |
| Température max du jour | `temperature` | °C | 🔸 |
| Température min du jour | `temperature` | °C | 🔸 |
| Rafale max du jour | — | km/h | 🔸 |
| Pluie max/1h du jour | `precipitation` | mm/h | 🔸 |
| Pluie cumul jour | `precipitation` | mm | 🔸 |
| Pluie cumul (3h) | `precipitation` | mm | 🔸 |
| Pluie cumul (6h) | `precipitation` | mm | 🔸 |
| Pluie cumul (12h) | `precipitation` | mm | 🔸 |
| Pluie cumul (24h) | `precipitation` | mm | 🔸 |
| DJU chauffage | — | — | 🔸 |
| DJU froid | — | — | 🔸 |

🔸 = activable dans l'interface HA après installation

Chaque capteur expose en attributs l'horodatage réel du relevé
(`obs_time_utc`), son âge en minutes (`age_releve_minutes`), le nom de la
station et l'URL de sa page. Le capteur de température porte en plus les
extrêmes du jour.

## Installation

### Via HACS (recommandé)

1. Dans HACS, va dans **Intégrations → ⋮ → Dépôts personnalisés**
2. Ajoute `https://github.com/Zephyrell/infoclimat-ha` avec la catégorie **Intégration**
3. Clique sur **Télécharger** en bas à droite de la carte Infoclimat Scraper
4. **Redémarre** Home Assistant

### Installation manuelle

1. Copie le dossier `custom_components/infoclimat/` dans le dossier
   `/config/custom_components/` de ton Home Assistant
2. **Redémarre** Home Assistant

### Configuration

1. Va dans **Paramètres → Périphériques & Services → Ajouter une intégration**
2. Cherche **Infoclimat Scraper**
3. Saisis l'identifiant StatIC de la station (5 caractères, ex. `000FU`).
   L'URL complète de sa page Infoclimat fonctionne aussi — colle-la telle
   quelle, l'identifiant en sera extrait
4. Définis l'intervalle de mise à jour (5 à 60 min, 10 par défaut)
5. Les capteurs apparaissent automatiquement dans tes entités

L'identifiant se lit dans l'adresse de la page de la station :
`…/temps-reel/saint-paul-trois-chateaux/000FU.html` → `000FU`.

## Architecture

```
custom_components/infoclimat/
├── __init__.py          # Point d'entrée de l'intégration
├── config_flow.py       # Écran de configuration dans l'UI HA
├── const.py             # Constantes et définition des capteurs
├── coordinator.py       # Polling HTTP — aucune règle de parsing
├── sensor.py            # Entités capteurs Home Assistant
├── manifest.json        # Métadonnées
├── translations/        # Traductions (fr, en)
└── parsing/             # Moteur de parsing, en couches
    ├── dom.py           #   tokenizer HTML → arbre
    ├── tables.py        #   où sont les tableaux (sélecteurs)
    ├── columns.py       #   en-tête → rôle logique (alias)
    ├── fields.py        #   cellule → capteurs (extracteurs)
    ├── climatology.py   #   table « climatologie du jour »
    ├── antibot.py       #   détection de la page anti-robot
    ├── notices.py       #   popups et fenêtres d'information
    └── report.py        #   traçabilité de chaque cycle
```

Chaque couche est remplaçable indépendamment, et aucune ne connaît les
autres en dehors de la suivante.

- **`dom.py`** construit un arbre à partir du HTML avec le tokenizer de la
  bibliothèque standard. C'est ce qui rend le reste possible : un
  `title="<table>…</table>"` (voir [Dépannage](#dépannage)) n'est plus un
  piège pour une expression régulière, c'est simplement un attribut.
- **`tables.py`** localise le tableau des relevés par son `id`, puis par sa
  classe, puis dans son conteneur — avec repli documenté à chaque étage.
- **`columns.py`** associe chaque colonne à un **rôle** (`temperature`,
  `pluie_1h`, `vent`…) en comparant les en-têtes à un registre d'alias
  normalisés (accents et ponctuation ignorés). Une colonne inconnue est
  signalée, jamais devinée.
- **`fields.py`** contient un extracteur par rôle : une fonction pure qui
  reçoit une cellule et rend un dictionnaire de mesures.
- **`report.py`** produit un compte rendu à chaque cycle, journalisé par le
  coordinateur en `INFO` (résumé) et `DEBUG` (détail).

**Ajouter un capteur** = un extracteur dans `fields.py` + un alias dans
`columns.py` + une entrée dans `SENSOR_TYPES`. Aucun index, aucun libellé
de colonne n'est codé en dur ailleurs.

### Dépendances

**Aucune.** Uniquement la bibliothèque standard Python et les modules
embarqués dans Home Assistant (`aiohttp`, `voluptuous`).

## Dépannage

`test_scraper.py` interroge une station en direct et affiche le relevé
**avec son rapport de parsing** :

```bash
python3 test_scraper.py                 # station par défaut
python3 test_scraper.py 00001 00052     # plusieurs stations
python3 test_scraper.py --html page.html
```

Les tests se lancent avec `python3 -m pytest tests/`. Ils tournent hors
ligne, sur des pages figées dans `tests/fixtures/`, et couvrent une
situation par fixture.

### Pourquoi le parsing cassait quand il pleuvait

Quand il a plu dans les dernières 24 h, Infoclimat ajoute une infobulle à la
cellule « Pluie » — et le contenu de cette infobulle est **une table HTML**,
logée dans l'attribut `title` :

```html
<td>2.4 mm/1h<br />
  <a title="<table><tr><td><b>Pluie/24h :</b></td><td>12.4mm</td></tr></table>">
```

Un parseur à base d'expressions régulières découpe les lignes avec
`<tr…>(.*?)</tr>` : il s'arrête au premier `</tr>` rencontré, y compris
celui qui dort *à l'intérieur de l'attribut*. La ligne est tronquée en
morceaux qui n'atteignent plus le nombre de colonnes attendu, et le relevé
le plus récent est purement et simplement écarté. En vue horaire — où
chaque ligne porte une mesure de pluie — **plus aucune ligne n'était
exploitable et l'intégration tombait**. Le même mécanisme faisait fuir du
texte d'infobulle dans les en-têtes, et un `(\d+) chauffe` lisait `1` dans
`0.1 chauffe`.

Le test `test_regression_l_ancien_parser_perdait_la_ligne_pluvieuse`
conserve cet ancien découpage pour documenter le bug ; il échouerait si
l'on revenait à cette approche.

### Le capteur Pluie : mm/10mn ou mm/1h ?

La cellule « Pluie » du site **mélange deux mesures** : un cumul sur
l'intervalle de la ligne — `0.4 mm/10mn` sur les relevés déciminutés,
`1.8 mm/1h` sur les lignes horaires — et un débit déjà exprimé en `mm/h`.
Prendre le premier nombre pour un débit surestime la pluie d'un facteur six,
puisque l'unité change d'une ligne à l'autre.

Le capteur **Pluie (1h)** porte donc l'intensité en `mm/h` telle que le site la
calcule, à défaut le `Pluie/1h` de l'infobulle, à défaut le cumul converti.
Le cumul brut de l'intervalle reste consultable en attributs :
`pluie_cumul_intervalle` et `pluie_intervalle_min`.

### Toutes les entités indisponibles, et « Échec de la configuration »

Infoclimat annonce `charset=utf-8` dans ses en-têtes HTTP **et publie du
Latin-1 par endroits** — deux octets `0xe0` dans une phrase de prose de la page
de `000FU`, et aucun `<meta charset>` pour se rattraper. En `1.3.0` et avant,
l'intégration décodait la réponse en strict : l'exception qui en résultait
n'était ni une erreur réseau ni une erreur de parsing, elle traversait donc les
`except`, faisait échouer la configuration, et **toutes les entités restaient
indisponibles en boucle**, avec pour seul indice :

```
Échec de la configuration, nouvel essai:
'utf-8' codec can't decode byte 0xe0 in position 108369: invalid continuation byte
```

Corrigé en **1.3.1** par `parsing/encoding.py`, qui ne lève jamais : le jeu de
caractères annoncé d'abord, puis `utf-8`, toujours en décodage tolérant. Les
octets fautifs sont hors du tableau des relevés, les mesures sont numériques —
le remplacement ne coûte rien.

Si tu as ce message, mets à jour : c'est la seule cause connue qui mette
l'intégration entièrement hors service.

### Station muette

Quand une station ne publie plus, le site l'indique lui-même dans sa fiche
(« Dernier report : 5 mai 2026, 07h30 », voyant rouge). L'intégration lit
cette fiche et la reprend dans le message d'erreur, dans `station_status` et
`station_last_report` — de quoi distinguer une station fermée d'un
identifiant mal saisi, sans ouvrir le navigateur.

### Blocage anti-robot

Interrogé trop souvent, Infoclimat renvoie **une page valide, au même
titre, mais vide de tout relevé** — remplacée par un message et un
reCAPTCHA :

> Notre serveur a détecté que votre requête était potentiellement
> automatisée. (…) nos moyens limités ne nous permettent pas d'autoriser ce
> type d'utilisation.

L'intégration identifie cette page (`AntiBotChallengeError`), l'annonce
pour ce qu'elle est — et non comme une station hors service — puis espace
ses requêtes à 30 minutes avant de revenir à la cadence configurée dès
qu'un relevé passe. Si cela se reproduit souvent, augmentez l'intervalle.

Les relevés StatIC sont publiés toutes les 10 minutes : interroger plus
souvent n'apporte rien et vous expose au blocage.

## Licence

MIT
