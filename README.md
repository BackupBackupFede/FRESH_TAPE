# FRESH TAPE — IPO et spin-offs US qui tiennent après 6 mois

Repère les IPO et spin-offs américaines qui ont passé 6 mois de cotation (fin habituelle du lock-up et des
ventes forcées) et qui restent au-dessus de leur prix de référence.

Mise à jour **à la demande** sur GitHub Actions : onglet Actions → Fresh Tape → **Run workflow**
(aussi dans l'appli GitHub mobile). Le rapport est régénéré et commité en une minute environ.

**Page interactive : https://backupbackupfede.github.io/FRESH_TAPE/** (filtres, tri, mini-graphiques,
fiche par titre ; les filtres se retrouvent dans l'adresse, à mettre en favori).

| Fichier | Contenu |
|---|---|
| [`index.html`](index.html) | Page interactive publiée sur GitHub Pages (générée, ne pas modifier à la main) |
| [`page_template.html`](page_template.html) | Gabarit de la page : mise en forme et filtres |
| [`fresh_tape.md`](fresh_tape.md) | Rapport : entrées depuis le dernier passage, tous les candidats, backtest |
| [`fresh_tape.csv`](fresh_tape.csv) | Tout l'univers (séparateur `;`, décimale `,`) |
| [`freshtape.py`](freshtape.py) | Le script |
| [`spinoff_overrides.json`](spinoff_overrides.json) | Corrections à la main : maisons mères, faux spin-offs |
| [`REPRISE.md`](REPRISE.md) | Historique du projet (v1 figée au 24/09/2026, reprise du 30/10/2026) |

## Sources

- IPO : calendrier public Nasdaq, toutes bourses US. SPAC écartées (nom, unités à 10 $, « Shell Companies » sur Yahoo).
- Spin-offs : formulaires 10-12B d'EDGAR + liste de la v1. Référence = première clôture.
- Cours, secteurs, capitalisations : Yahoo Finance (yfinance).
- EDGAR exige une adresse de contact : secret `SEC_CONTACT` (ou `sec_contact.txt` en local, non versionné).

En local : `pip install -r requirements.txt` puis `python freshtape.py` (options : `--months`, `--start`,
`--min-price`, `--hold`, `--no-info`). La page sort dans `index.html`.

## Limites

- Backtest sur petit échantillon, biais du survivant : indicatif.
- Liste des spin-offs incomplète (seulement celles enregistrées par 10-12B).
- Petites capitalisations peu liquides en tête de liste : vérifier les volumes.

*Travail d'analyse quantitative, sans valeur de conseil en investissement.*
