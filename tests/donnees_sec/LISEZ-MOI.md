# Comptes réels de la SEC pour les tests

Fichiers « companyfacts » de l'API XBRL de la SEC (data.sec.gov, données publiques), compressés :
Apple, Coca-Cola, Eli Lilly, General Dynamics, Cardinal Health, Phillips 66, APA, Incyte, NVR, DTE Energy.
Cas particuliers : Ferguson (changement de date de clôture), Waters (trimestres calendaires dans le
rapport annuel), Lennar (total de l'actif absent), Qnity (scission récente), BlackRock et ExxonMobil
(nouvelles holdings), Disney (signe d'une charge inversé), Extra Space Storage (foncière),
Nike (produits d'intérêts nets), Costco (trimestre de 16 semaines).

`tests/test_sec_reel.py` vérifie sur ces vrais dépôts que le moteur retrouve les chiffres publiés dans les
rapports annuels (chiffre d'affaires, résultat net), reconstitue correctement les douze mois glissants, et
gère les étiquettes inhabituelles (EBIT, intérêts, dette). Ces fichiers ne servent qu'aux tests.
