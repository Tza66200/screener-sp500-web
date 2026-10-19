# Screener S&P 500 — application web

Classe chaque soir les quelque 500 actions du S&P 500, élimine les plus fragiles et donne pour chacune un signal
**ACHETER, GARDER, SURVEILLER ou VENDRE**, avec un portefeuille proposé de 25 lignes et un backtest depuis 2011.
Le tout est publié sur une page web à ton adresse, mise à jour automatiquement même quand ton ordinateur est
éteint. Coût : zéro.

Outil d'aide à la décision, pas un conseil en investissement. Aucun score ne garantit qu'une action ne baissera pas.

## Ce que fait le site

| Page | Contenu |
|---|---|
| Tableau de bord | Les 500 actions placées sur l'échelle des scores, le portefeuille proposé, les changements de signal depuis la veille, le backtest en bref |
| Classement | Toutes les actions, filtrables par signal et secteur, triables, avec quatre jeux de colonnes et l'export CSV |
| Fiche d'une action | Score et signal expliqués, détail des filtres de sécurité, cours sur deux ans, historique du score depuis 2011, chiffres clés |
| Portefeuille | Tes positions (gardées dans ton navigateur) : ce qu'il faut garder, vendre et acheter, et le montant par ligne |
| Backtest | Courbes, pertes maximales, rendements annuels, indicateurs par période, pouvoir prédictif du score, journal des décisions |
| Méthode | Règles, réglages en vigueur, état des sources, téléchargements Excel et HTML |

## Comment ça marche

```
GitHub Actions (planificateur gratuit, chaque soir de bourse à 23 h 20 UTC + samedi pour le backtest)
  ├─ composition de l'indice   Wikipédia, historique : github.com/fja05680/sp500
  ├─ cours                     Yahoo Finance (secours facultatif : API officielle d'Alpaca)
  ├─ comptes des sociétés      SEC EDGAR, API officielle (data.sec.gov)
  ├─ taux sans risque          Réserve fédérale de Saint-Louis (FRED)
  ├─ contrôles de qualité      cours à jour, couverture des données ; sinon le site garde les données précédentes
  ├─ historique des signaux    enregistré dans le dossier historique/ du dépôt
  └─ site statique             publié sur GitHub Pages, en HTTPS
```

Les données téléchargées sont gardées d'un passage à l'autre dans le cache de GitHub Actions. Le backtest est
recalculé chaque samedi, et aussitôt que tu modifies un réglage.

## Mise en place (une dizaine de minutes)

1. **Compte GitHub.** Crée-en un gratuitement sur <https://github.com> si tu n'en as pas.
2. **Dépôt.** Bouton **New repository** : choisis un nom (par exemple `screener-sp500-web`), coche **Public**, ne
   coche rien d'autre, puis **Create repository**.
3. **Fichiers.** Sur la page du dépôt vide, clique **uploading an existing file** et glisse **tout le contenu** de
   ce dossier, y compris le dossier `.github` (sur Mac, il est caché : appuie sur Cmd + Maj + point dans le Finder
   pour l'afficher). Puis **Commit changes**.
4. **Secret pour la SEC.** Dans le dépôt : **Settings → Secrets and variables → Actions → New repository secret**.
   Nom : `SEC_EMAIL` ; valeur : ton adresse e-mail. La SEC exige une adresse de contact dans chaque requête ; ce
   secret est chiffré par GitHub et n'apparaît ni sur le site ni dans les fichiers.
5. **Site.** **Settings → Pages → Build and deployment → Source : GitHub Actions**.
6. **Premier calcul.** Onglet **Actions** (accepte l'activation des workflows si GitHub la demande), puis
   **Actualisation → Run workflow**, coche « Recalculer aussi le backtest », et **Run workflow**. Le premier passage
   prend 30 à 45 minutes ; les suivants, une vingtaine.
7. **Adresse du site.** Elle s'affiche dans **Settings → Pages** et à la fin de l'exécution :
   `https://<ton-pseudo>.github.io/<nom-du-depot>/`. Ajoute-la à tes favoris ou à l'écran d'accueil de ton téléphone.

Ensuite, il n'y a plus rien à faire : le site se met à jour chaque soir de bourse.

## Changer les réglages

Ouvre `reglages.json` sur GitHub, clique sur le crayon, modifie une valeur, puis **Commit changes**. Le site se
recalcule tout seul, backtest compris. Le bouton « Modifier les réglages sur GitHub » de la page Méthode y mène
directement.

| Réglage | Par défaut | Rôle |
|---|---|---|
| `n_positions` | 25 | nombre de lignes du portefeuille |
| `max_par_secteur` | 0.25 | part maximale des lignes dans un même secteur |
| `seuil_achat` / `seuil_garder` / `seuil_vente` | 90 / 60 / 50 | seuils de score des signaux |
| `robustesse_min_achat` | 50 | robustesse minimale pour ACHETER |
| `poids_potentiel` | 0.5 | poids du potentiel dans le score (le reste va à la robustesse) |
| `fscore_min` | 6 | F-score de Piotroski minimum (sur 9) |
| `couverture_min` | 3.0 | bénéfice d'exploitation minimum, en multiple des intérêts |
| `exclusion_levier_secteur` | 0.10 | part des plus endettés de chaque secteur exclus |
| `exclusion_accruals_secteur` | 0.10 | part des pires accruals de chaque secteur exclus, seulement s'ils sont positifs (bénéfice supérieur au cash-flow) |
| `exclusion_volatilite` | 0.10 | part des actions les plus volatiles de l'indice exclues |
| `beneish_exclut` | false | `true` : un M-score de Beneish suspect devient éliminatoire |
| `debut_backtest` / `debut_validation` | 2011-01-01 / 2019-01-01 | période du backtest et début de la période de validation |
| `frais` | 0.001 | frais par transaction dans le backtest (0,10 %) |
| `rebalancement` | trimestriel | ou `mensuel` |
| `backtest_prix_depuis_2001` | false | `true` : ajoute un backtest « cours seulement » depuis 2001 (crise de 2008 incluse) |
| `revisions_analystes` | true | révisions des prévisions de bénéfices (Yahoo) dans le classement du jour |

**Règle d'or** : choisis tes réglages avant de regarder le backtest. Les ajuster jusqu'à obtenir une belle courbe
rend le backtest trompeur ; la période de validation ne doit jamais servir à régler.

## Source de cours de secours (facultatif)

Yahoo Finance est gratuit mais non officiel. Pour fiabiliser les cours, ouvre un compte gratuit chez Alpaca
(<https://alpaca.markets> ; un compte de simulation, dit « paper trading », suffit), crée une clé d'API, puis ajoute deux secrets
au dépôt : `ALPACA_API_KEY_ID` et `ALPACA_API_SECRET_KEY`. Toute action absente de Yahoo est alors complétée par
l'API officielle d'Alpaca (historique depuis 2016), et le site l'indique dans la page Méthode.

## Sécurité et confidentialité

- **Pas de serveur** : le site est un ensemble de fichiers statiques servis en HTTPS par GitHub Pages. Rien à
  pirater, pas de base de données, pas de compte.
- **Aucun script externe ni traceur** dans la page, polices comprises ; une politique de sécurité du contenu (CSP)
  interdit tout le reste.
- **Tes positions** restent dans ton navigateur (stockage local) et ne sont envoyées nulle part. Exporte-les pour
  les retrouver sur un autre appareil.
- **Secrets** : l'adresse e-mail et les clés éventuelles sont des secrets GitHub chiffrés, transmis uniquement à
  l'étape de calcul.
- **Chaîne d'outils** : versions et empreintes de toutes les dépendances vérifiées à l'installation, actions GitHub
  épinglées à une version précise, droits minimaux pour chaque étape (seule l'étape qui enregistre l'historique peut
  écrire dans le dépôt, et elle n'installe rien).
- **Visibilité** : le site est public pour qui connaît son adresse, et non référencé par les moteurs de recherche.
  Il ne contient que des données de marché publiques.

## Coût et limites

- **Gratuit** avec un dépôt public : GitHub Actions et GitHub Pages ne facturent rien aux dépôts publics. Un dépôt
  privé est possible avec GitHub Pro (environ 4 $ par mois), mais le site reste alors public.
- GitHub suspend les tâches planifiées d'un dépôt public inactif depuis 60 jours ; l'enregistrement quotidien de
  l'historique compte comme une activité, donc cela n'arrive pas tant que les actualisations réussissent.
- Les horaires des tâches planifiées de GitHub peuvent glisser de quelques dizaines de minutes aux heures chargées.
- **Yahoo Finance** peut limiter les requêtes : l'actualisation échoue alors proprement, le site garde les données
  de la veille et affiche le message ; le passage suivant reprend normalement.
- **Backtest** : les sociétés disparues manquent chez Yahoo (biais favorable), les impôts ne sont pas déduits, et la
  première année repose sur un peu moins de comptes (le XBRL de la SEC commence en 2009-2010).

## En cas de problème

| Ce que tu vois | Ce qu'il faut faire |
|---|---|
| E-mail de GitHub « Run failed » | Ouvre l'exécution dans l'onglet Actions : le résumé donne la cause. Le site garde les données précédentes. Le compte rendu complet du dernier calcul est aussi dans la branche `journal` du dépôt (fichier `journal.txt`). |
| « Le secret SEC_EMAIL est absent ou invalide » | Ajoute ou corrige le secret (étape 4 de la mise en place). |
| « Comptes SEC exploitables pour seulement… » | La SEC a refusé les requêtes : vérifie l'adresse du secret, ou attends le passage suivant. |
| « Cours manquants… » ou « cours pas à jour » | Yahoo limite les requêtes : relance plus tard, ou ajoute la source de secours Alpaca. |
| La page affiche « Les données ne sont pas encore disponibles » | Le premier calcul n'est pas terminé, ou Pages n'est pas réglé sur GitHub Actions (étape 5). |
| « Les données ont plus de quatre jours » | Les actualisations se sont arrêtées : onglet Actions, réactive le workflow s'il est désactivé, puis Run workflow. |
| Une action reste « DONNÉES INSUFFISANTES » ou un indicateur manque | Le motif affiché donne la cause. Pour l'examiner : Run workflow avec la case « Joindre au journal les comptes SEC bruts » cochée (c'est automatique après chaque modification du programme) ; la branche `journal` contient alors, dans `diagnostic/`, les comptes bruts de la SEC des sociétés concernées. |
| Erreur après une modification de `reglages.json` | Le message dit quel réglage est en cause (virgule, guillemet, valeur hors limites). Corrige le fichier. |

## Fichiers du dépôt

| Fichier | Rôle |
|---|---|
| `screener_sp500.py` | Le moteur : données, filtres, scores, signaux, portefeuille, backtest, rapports Excel et HTML. Il fonctionne aussi seul en ligne de commande. |
| `site_web.py` | Lance le moteur, contrôle la qualité des données et construit le site. |
| `reglages.json` | Tes réglages. |
| `web/` | L'application (HTML, CSS, JavaScript, polices), sans aucune dépendance. |
| `historique/` | Un instantané des signaux par séance, enregistré automatiquement. |
| `tests/` | Tests sur données simulées et sur de vrais comptes de la SEC, lancés avant chaque actualisation. |
| `.github/workflows/actualisation.yml` | La planification sur GitHub Actions. |
| `requirements.txt` | Dépendances Python, versions et empreintes figées (tiré de `requirements.in` par `pip-compile`). |

## Essayer en local

```
pip install --require-hashes --no-deps -r requirements.txt
python site_web.py --demo --sortie _site          # aperçu avec des données simulées, sans réseau
python -m http.server --directory _site 8000      # puis ouvre http://localhost:8000
```

Avec de vraies données : `SEC_EMAIL=ton@adresse.fr python site_web.py`. Le moteur seul :
`python screener_sp500.py --email ton@adresse.fr --reglages reglages.json --backtest`.
