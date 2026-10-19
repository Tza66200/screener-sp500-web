# Comptes réels de la SEC pour les tests

Fichiers « companyfacts » de l'API XBRL de la SEC (data.sec.gov, données publiques), compressés :
Apple, Coca-Cola, Eli Lilly, General Dynamics, Cardinal Health, Phillips 66, APA, Incyte, NVR, DTE Energy.

`tests/test_sec_reel.py` vérifie sur ces vrais dépôts que le moteur retrouve les chiffres publiés dans les
rapports annuels (chiffre d'affaires, résultat net), reconstitue correctement les douze mois glissants, et
gère les étiquettes inhabituelles (EBIT, intérêts, dette). Ces fichiers ne servent qu'aux tests.
