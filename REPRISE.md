# Reprise Fresh Tape — état au 30/10/2026

À lire en entier avant toute action. Le projet n'a **jamais eu de dépôt** : il n'existe que
sous la forme d'une page publiée, et la conversation qui l'a produite est perdue avec la
réinitialisation du PC du 27/10/2026. Ce dossier part donc de la page elle-même.

## En une phrase

Fresh Tape est une page de filtrage des IPO et spin-offs américaines qui ont passé le cap des
7 mois (fin habituelle du lock-up des initiés) et qui performent toujours depuis leur
introduction. C'est un **snapshot figé au 24/09/2026**, avec des données saisies à la main dans
la page. La reprise consiste à la remettre à jour, puis à décider si on l'automatise.

## Où sont les choses

| Élément | Emplacement |
|---|---|
| Page publiée (privée) | https://claude.ai/artifact/6YA2SJvtdUoZKfLh21CYCC (id `2cd74fd7-4c06-415f-b6fa-130d4365cabd`). **Republier au même url.** |
| Copie de la page, telle que publiée | [_page_v1/index.html](_page_v1/index.html) (130 Ko, un seul fichier, sans dépendance hors Google Fonts) |
| Données extraites de la page | [freshtape_v1_data.json](freshtape_v1_data.json) : 400 lignes |
| Code de collecte | **Aucun.** Les données ont été recopiées pendant la conversation depuis stockanalysis.com (voir « Comment la v1 a été faite ») |

## Ce que contient la page

- **Données** : un bloc `<script id="ipo-data" type="application/json">`, soit 382 IPO
  (du 01/07/2025 au 18/09/2026) et 18 spin-offs (depuis février 2025). Champs : `ticker`,
  `name`, `date`, `refPrice`, `price`, `ret` (%), `type` (`ipo`|`spinoff`), `spac`, `sector`,
  `industry`, `exch`, `mc` (M$), `parent`.
- **Filtres** : recherche, perf. minimale, ancienneté minimale (7 mois par défaut), secteur,
  type, SPAC exclues par défaut, perf. positive uniquement. Tri par colonne.
- **Thème** clair/sombre, mémorisé dans `localStorage` (`freshtape_theme`).
- Au 30/10, avec les réglages par défaut et « perf. positive », 65 titres passent le filtre
  (contre 60 au 24/09). Mais les prix datent du 24/09.

## Comment la v1 a été faite (reconstitué le 30/10/2026)

La conversation d'origine est perdue. Ce qui suit est déduit des données de la page,
comparées le 30/10 aux pages publiques de stockanalysis.com. C'est une reconstitution,
pas un témoignage.

| Champ(s) | Origine | Indice |
|---|---|---|
| `date`, `ticker`, `name`, `refPrice`, `price`, `ret` des IPO | Tableaux [stockanalysis.com/ipos/2025/](https://stockanalysis.com/ipos/2025/) et [/ipos/2026/](https://stockanalysis.com/ipos/2026/), colonnes `IPO Date · Symbol · Company Name · IPO Price · Current · Return` | Les noms sont identiques au caractère près (« American Savings Bank, National Association », « Neutron Holdings, Inc. »), ainsi que les dates et prix d'IPO. Ces six colonnes sont **tout** ce que le tableau fournit |
| `ret` | Colonne `Return` recopiée telle quelle, **pas recalculée** | Pour 183 des 382 IPO, `ret` ne vaut pas `price / refPrice − 1`, par exemple ETRA à −7,2 % alors que 13,31 / 15 donne −11,3 %. Les deux colonnes ont été relevées à des moments différents, ou bien `Return` ne part pas du prix d'IPO. Le site ne le précise pas |
| Spin-offs : `ticker`, `date`, `parent` | Pages [stockanalysis.com/actions/spinoffs/](https://stockanalysis.com/actions/spinoffs/) (par année) | Mêmes dates (SOLS au 30/10/2025, Q au 03/11/2025, VSNT au 05/01/2026). Noms de maison mère au format du site (« Gpgi », « People Inc »). Ce sont 18 lignes choisies, pas la liste complète |
| `spac` | **Jugement de Claude, ligne par ligne**, sans règle | Le site ne marque pas les SPAC. Le marquage ne suit aucune expression régulière : des sponsors connus sont marqués (Gores, Research Alliance, Cantor CEPS), d'autres du même sponsor ne le sont pas (Cantor CEPF, CEPV), et SpaceX est marquée à tort |
| `sector`, `industry` | Connaissances de Claude, pour les valeurs connues | Libellés français écrits à la main (« Biotech (CRISPR) », « Gestion d'actifs (Ackman) »). Le site n'a pas de colonne secteur. Les SPAC reçoivent un libellé SPAC automatique, et 126 lignes restent « Autre / Non classé » |
| `mc` | Recherche ponctuelle, 61 lignes | Uniquement pour les valeurs notables |
| `exch` | « Nasdaq » par défaut | Le pied de page l'avoue. 18 lignes seulement sont en NYSE |
| `TODAY` dans le code | Date du jour de génération (24/09/2026) | Les cours sont ceux de ce jour-là |

**Trou dans les données : aucune IPO de janvier 2026**, alors que le tableau 2026 de
stockanalysis commence au 06/01/2026. Mars 2026 est aussi anormalement maigre (14 lignes
contre 25 à 38 pour les autres mois). Recopier un tableau de plusieurs centaines de lignes
en conversation a perdu des morceaux. La v2 ne doit donc pas se fier à la v1 comme liste
de référence.

**Ce que ça veut dire pour une v2 automatisée** : les six colonnes IPO et la liste des
spin-offs se lisent sur deux ou trois pages publiques. Le pied de page de stockanalysis
indique que ses données d'IPO sont relevées à la main depuis les dépôts SEC. Tout le reste
(SPAC, secteur, capitalisation, bourse) n'a jamais eu de source et devra en trouver une :
EDGAR pour les SPAC (code SIC 6770) et la bourse, une API de cours pour la capitalisation.
Vérifier les conditions d'utilisation de stockanalysis avant d'automatiser sa lecture.

## Défauts constatés dans la v1

1. **La date du jour est figée dans le code** : `var TODAY = new Date("2026-09-24"…)`. Le pied
   de page affirme pourtant que l'ancienneté est « calculée dynamiquement depuis la date du
   jour ». Soit on passe à `new Date()`, soit on corrige le texte. Mais des prix du 24/09 avec
   une ancienneté calculée au jour J donnent une page incohérente.
2. **Les SPAC sont détectées par le nom, et l'heuristique se trompe dans les deux sens.**
   - Faux positif grave : **SPCX (Space Exploration Technologies, SpaceX)** est marquée SPAC,
     donc **masquée par défaut**. Même doute pour AADX, SHOT et CAES : ce sont peut-être des
     de-SPAC, à vérifier une par une.
   - Faux négatifs : CCCT, CGCF, YICC, IPVV, LTGR, XFLH, CEPF, TLNC, PXED, DYOR, CEPV, PARK, KBON,
     CCXI, SCPQ ont des noms de blank check (`Capital Corp`, `Growth Corp`, `Acquisition`…) et
     ne sont pas marquées.
   - À remplacer par une source fiable (code SIC 6770 sur EDGAR) plutôt que par le nom.
3. **Spin-offs sans prix de référence** : 17 sur 18 ont `refPrice` et `ret` à `null`. Seul
   SNDK est renseigné, à **+4 960 %**, un chiffre à revérifier avant de s'y fier.
4. **Données incomplètes** : 126 lignes sur 400 en secteur « Autre », capitalisation renseignée
   pour seulement 61 lignes, bourse « supposée Nasdaq » pour la majorité.

## Décisions à prendre avec Florian, avant de coder

- **Mise à jour ponctuelle ou automatique ?** La deuxième option voudrait dire un script dans ce
  dossier (liste des IPO, cours, détection SPAC), un dépôt GitHub, et une GitHub Action ou une
  routine qui régénère le JSON et republie la page, comme ses autres bots (ROTATION, AMF…).
- **Source des cours** : stockanalysis.com comme en v1, ou yfinance, déjà utilisé dans ROTATION
  et dans les listes Russell1000/Euronext ? Vérifier les conditions d'utilisation avant de
  scraper.
- **Les spin-offs restent-elles ?** Sans prix de référence fiable, elles n'apportent rien au
  filtre de performance.
- Le lien éventuel avec le « Tracker situations spéciales US », un cahier des charges du 17/09
  (https://claude.ai/artifact/VtazUke76dq6oiENJdUp48) qui suit des dépôts SEC et n'a jamais été
  codé. Les deux projets visent les situations spéciales US et pourraient partager la détection
  SPAC et la source EDGAR.

## Règles à garder

- Ne jamais présenter la page comme un conseil d'investissement : la mention actuelle du pied de
  page reste.
- Toujours afficher la date du snapshot et dire clairement que les prix ne bougent pas seuls.
- Une valeur inconnue s'affiche « n/d », jamais une estimation : c'est le choix de la v1 pour
  les spin-offs, et il est bon.

## Environnement

Python 3.12 : `C:\Users\FLO\AppData\Local\Programs\Python\Python312\python.exe` (pas dans le
PATH). Git et GitHub CLI sont installés (compte `BackupBackupFede`). Ce dossier n'est **pas**
encore un dépôt git.

## v2 locale (30/10/2026)

Choix de Florian : mise à jour ponctuelle, en local, seuil à 6 mois. Script [freshtape.py](freshtape.py) :
liste des IPO depuis le calendrier Nasdaq (`api.nasdaq.com/api/ipo/calendar`, mis en cache dans `cache/`),
cours, secteurs et capitalisations via yfinance, SPAC repérées par le nom, les unités à 10 $ et l'industrie
Yahoo « Shell Companies ». Sorties dans `output/` (CSV + page HTML locale), avec un backtest rapide.
Spin-offs ajoutées : formulaires 10-12B des index trimestriels EDGAR + les 18 de la v1, référence = première
clôture Yahoo ; les titres qui cotaient déjà avant leur 10-12B sont écartés. Corrections à la main dans
[spinoff_overrides.json](spinoff_overrides.json). Adresse de contact SEC dans `sec_contact.txt` (envoyée seulement à sec.gov).
Étiquette « conversion mutualiste » : banque introduite à 10 $ avec code SIC 6035/6036.
La page publiée n'a pas été republiée.
