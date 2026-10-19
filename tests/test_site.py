"""Application web : réglages, construction du site sur données simulées, historique, secours en cas d'échec,
contrôles de qualité, absence de fuite de l'adresse e-mail, et logique JavaScript identique au moteur Python."""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import zipfile

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(ICI)
sys.path.insert(0, RACINE)
sys.path.insert(0, ICI)

import pandas as pd  # noqa: E402

import demo  # noqa: E402
import screener_sp500 as sc  # noqa: E402
import site_web as sw  # noqa: E402

OK, KO = [], []


def verifier(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("  OK  " if cond else "  ÉCHEC ") + nom + (f"  ({detail})" if detail else ""))


def refuser_nan(x):
    raise ValueError(f"valeur non JSON : {x}")


def lire(chemin):
    with open(chemin, encoding="utf-8") as fh:
        return json.load(fh, parse_constant=refuser_nan)


TMP = tempfile.mkdtemp(prefix="test_site_")
CANARI = "canari-secret@domaine-test.org"        # fausse adresse : ne doit apparaître dans aucun fichier publié
os.environ["SEC_EMAIL"] = CANARI
for k in ("GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY", "GITHUB_REPOSITORY", "GITHUB_ACTIONS"):  # pas d'annotations pendant les tests
    os.environ.pop(k, None)
D = demo.installer(sc, n=60)
VRAI_SCREENER = sc.lancer_screener


def args(**k):
    base = dict(sortie=os.path.join(TMP, "_site"), donnees=os.path.join(TMP, "donnees"),
                historique=os.path.join(TMP, "historique"), reglages=os.path.join(RACINE, "reglages.json"),
                web=os.path.join(RACINE, "web"), backtest="auto", demo=False)
    base.update(k)
    return types.SimpleNamespace(**base)


def argv(a):
    return ["--sortie", a.sortie, "--donnees", a.donnees, "--historique", a.historique, "--reglages", a.reglages,
            "--web", a.web, "--backtest", a.backtest]


# ---------------------------------------------------------------------------
print("\n1. Réglages (reglages.json)")
plat, options = sw.lire_reglages(os.path.join(RACINE, "reglages.json"))
cfg = sw.config_web(plat, os.path.join(TMP, "x"), CANARI)
defaut = sc.Config()
diff = [k for k in plat if getattr(cfg, k) != getattr(defaut, k)]
verifier("reglages.json reprend exactement les réglages par défaut du moteur", not diff, str(diff))
verifier("options du site lues à part", options == {"backtest_prix_depuis_2001": False}, str(options))
verifier("caches courts pour l'actualisation quotidienne", cfg.cache_prix_jours < 1 and cfg.cache_sec_jours < 1)
mauvais = os.path.join(TMP, "mauvais.json")
for contenu, attendu in [('{"signaux": {"seuil_achat": 90,}}', "ligne"), ('{"signaux": {"seuil_achatt": 90}}', "inconnu"),
                         ('{"signaux": {"seuil_achat": 40}}', "seuil"), ('{"portefeuille": {"n_positions": "beaucoup"}}', "invalide")]:
    with open(mauvais, "w", encoding="utf-8") as fh:
        fh.write(contenu)
    try:
        p, o = sw.lire_reglages(mauvais)
        sw.config_web(p, TMP, CANARI)
        verifier(f"réglage incorrect refusé ({attendu})", False)
    except ValueError as e:
        verifier(f"réglage incorrect refusé avec un message clair ({attendu})", attendu in str(e).lower(), str(e)[:90])

# ---------------------------------------------------------------------------
print("\n2. Deux actualisations successives (veille, puis jour même)")
D["fixer_date"]("2026-10-15")
e1 = sw.executer(args())
D["fixer_date"]("2026-10-16")
e2 = sw.executer(args())
site = os.path.join(TMP, "_site")
attendus = ["index.html", "app.js", "logique.js", "style.css", "favicon.svg", "polices/OFL.txt",
            "data/classement.json", "data/historique.json", "data/backtest.json", "data/etat.json",
            "rapports/classement.xlsx", "rapports/classement.html", "rapports/backtest.xlsx", "rapports/backtest.html"]
manquants = [f for f in attendus if not os.path.exists(os.path.join(site, f))]
verifier("tous les fichiers du site sont produits", not manquants, str(manquants))
verifier("polices hébergées avec le site", len(glob.glob(os.path.join(site, "polices", "*.woff2"))) == 2)
jsons = glob.glob(os.path.join(site, "data", "**", "*.json"), recursive=True)
erreurs = []
for f in jsons:
    try:
        lire(f)
    except ValueError as e:
        erreurs.append(f"{os.path.basename(f)}: {e}")
verifier("JSON stricts (aucun NaN ni infini)", not erreurs, f"{len(jsons)} fichiers ; {erreurs[:2]}")

c = lire(os.path.join(site, "data", "classement.json"))
lignes = [dict(zip(c["colonnes"], l)) for l in c["lignes"]]
verifier("classement : une ligne par action, colonnes cohérentes",
         len(lignes) == 60 and all(len(l) == len(c["colonnes"]) for l in c["lignes"]), f"{len(lignes)} lignes")
indispensables = {"t", "nom", "secteur", "secteur_fr", "signal", "score", "potentiel", "robustesse", "motif", "echec",
                  "cik", "f_fscore", "f_volatilite", "s_volatilite", "cours", "capitalisation", "fin", "dispo"}
verifier("classement : champs attendus par l'application", indispensables <= set(c["colonnes"]),
         str(indispensables - set(c["colonnes"])))
verifier("classement : signaux connus", {l["signal"] for l in lignes} <= set(sc.SIGNAUX))
par = {l["t"]: l for l in lignes}
port = c["portefeuille"]
plafond = int(c["reglages"]["max_par_secteur"] * c["reglages"]["n_positions"] + 1e-9)
secteurs = pd.Series([par[t]["secteur"] for t in port]).value_counts()
verifier("portefeuille proposé : uniquement des ACHETER, plafond par secteur respecté",
         all(par[t]["signal"] == "ACHETER" for t in port) and (secteurs.max() if len(secteurs) else 0) <= plafond
         and len(port) <= c["reglages"]["n_positions"], f"{len(port)} lignes, max {secteurs.max() if len(secteurs) else 0} par secteur")
verifier("réglages publiés sans e-mail ni chemin du cache", not {"email", "dossier"} & set(c["reglages"]))

h = lire(os.path.join(site, "data", "historique.json"))
verifier("historique : les deux séances", h["dates"] == ["2026-10-15", "2026-10-16"], str(h["dates"]))
ch = h["changements"][-1]
verifier("historique : changements de signal entre les deux séances",
         ch["precedent"] == "2026-10-15" and ch["date"] == "2026-10-16" and all(x["avant"] != x["apres"] for x in ch["liste"]),
         f"{len(ch['liste'])} changements")
inst = sorted(glob.glob(os.path.join(TMP, "historique", "2026", "*.csv")))
verifier("instantanés enregistrés pour le dépôt (un fichier par séance)", [os.path.basename(x) for x in inst]
         == ["2026-10-15.csv", "2026-10-16.csv"])

b = lire(os.path.join(site, "data", "backtest.json"))
n = len(b["series"]["dates"])
verifier("backtest : séries alignées sur les dates", n > 3000 and all(len(v) == n for v in b["series"]["valeurs"]), f"{n} jours")
verifier("backtest : trois périodes de mesure", len(b["metriques"]) == 3, str(list(b["metriques"])))
verifier("backtest : empreinte des réglages enregistrée", b["empreinte"] == sw.empreinte(cfg, options))
verifier("backtest : journal des décisions", len(b["journal"]) > 100 and "portefeuille" in b["journal"][0])

e = lire(os.path.join(site, "data", "etat.json"))
verifier("état : statut, date des données, sources", e["statut"] in ("ok", "avertissement") and e["date_donnees"] == "2026-10-16"
         and "cours" in e["sources"] and "sec" in e["sources"], e["statut"])
verifier("état : backtest non recalculé à la 2e actualisation", e1["backtest"]["recalcule"] and not e2["backtest"]["recalcule"],
         e2["backtest"]["raison"])
verifier("état : fichiers facultatifs signalés", e["fichiers"] == {"backtest": True, "backtest_prix": False})

titres = glob.glob(os.path.join(site, "data", "titres", "*.json"))
f0 = lire(titres[0])
verifier("fiches : une par action, cours et historique du score", len(titres) == 60 and len(f0["dates"]) == len(f0["cours"]) > 400
         and len(f0["quotidien"]) == 2, f"{len(titres)} fiches, {len(f0['mensuel'])} scores mensuels")

fuites = []
for racine in (site, os.path.join(TMP, "historique")):
    for f in glob.glob(os.path.join(racine, "**", "*"), recursive=True):
        if not os.path.isfile(f):
            continue
        if f.endswith(".xlsx"):
            with zipfile.ZipFile(f) as z:
                contenu = b"".join(z.read(n) for n in z.namelist())
        else:
            contenu = open(f, "rb").read()
        if CANARI.encode() in contenu:
            fuites.append(os.path.relpath(f, TMP))
verifier("l'adresse e-mail (secret SEC_EMAIL) n'apparaît dans aucun fichier publié ou enregistré", not fuites, str(fuites[:3]))

e3 = sw.executer(args())
verifier("3e passage le même jour : instantané remplacé, pas dupliqué", len(glob.glob(os.path.join(TMP, "historique", "2026", "*.csv"))) == 2
         and lire(os.path.join(site, "data", "historique.json"))["dates"][-1] == "2026-10-16")
modif = os.path.join(TMP, "reglages_modifies.json")
r = json.load(open(os.path.join(RACINE, "reglages.json"), encoding="utf-8"))
r["portefeuille"]["n_positions"] = 20
json.dump(r, open(modif, "w", encoding="utf-8"))
p2, o2 = sw.lire_reglages(modif)
refaire, raison = sw.backtest_a_refaire("auto", os.path.join(TMP, "donnees", "web", "backtest.json"),
                                        sw.empreinte(sw.config_web(p2, TMP, CANARI), o2))
verifier("réglages modifiés : le backtest sera recalculé", refaire and "réglages" in raison, raison)

# ---------------------------------------------------------------------------
print("\n3. Échec d'une source : le site précédent est republié avec le message")
sortie_gh = os.path.join(TMP, "github_output.txt")
os.environ["GITHUB_OUTPUT"] = sortie_gh
classement_avant = open(os.path.join(site, "data", "classement.json"), "rb").read()


def panne(cfg, positions=None):
    raise RuntimeError("Yahoo Finance ne répond pas (panne simulée)")


sc.lancer_screener = panne
code = sw.main(argv(args()))
sc.lancer_screener = VRAI_SCREENER
e = lire(os.path.join(site, "data", "etat.json"))
verifier("le script se termine en erreur (GitHub prévient par e-mail)", code == 1)
verifier("le site précédent est republié, avec le message d'erreur", e["statut"] == "erreur" and "panne simulée" in e["erreur"]["message"]
         and open(os.path.join(site, "data", "classement.json"), "rb").read() == classement_avant, e["erreur"]["message"][:60])
sorties = open(sortie_gh, encoding="utf-8").read()
verifier("sorties pour GitHub Actions : publier oui, enregistrer l'historique non", "succes=false" in sorties and "publier=true" in sorties)
os.environ.pop("GITHUB_OUTPUT")

# ---------------------------------------------------------------------------
print("\n4. Contrôles de qualité")
res = sc.lancer_screener(cfg_demo := sw.config_web(plat, os.path.join(TMP, "donnees"), CANARI))
try:
    sw.controler(res, cfg_demo, pd.Timestamp("2026-10-30").date())
    verifier("cours figés depuis plus de 5 jours : refusés", False)
except sw.ErreurQualite as ex:
    verifier("cours figés depuis plus de 5 jours : refusés", "pas à jour" in str(ex), str(ex)[:70])
sc.ETAT_SOURCES["cours"] = {"demandes": 100, "obtenus": 70, "par_alpaca": []}
try:
    sw.controler(res, cfg_demo, pd.Timestamp("2026-10-17").date())
    verifier("trop de cours manquants : refusés", False)
except sw.ErreurQualite as ex:
    verifier("trop de cours manquants : refusés", "Cours manquants" in str(ex), str(ex)[:70])
sc.ETAT_SOURCES["cours"] = {"demandes": 100, "obtenus": 99, "par_alpaca": ["XYZ"]}
sc.ETAT_SOURCES["sec"] = {"societes": 60, "exploitables": 60}
avert = sw.controler(res, cfg_demo, pd.Timestamp("2026-10-17").date())
verifier("source de secours utilisée : simple avertissement", any("Alpaca" in a for a in avert), str(avert)[:80])
os.environ.pop("SEC_EMAIL")
code = sw.main(argv(args(sortie=os.path.join(TMP, "_site_sans_email"), donnees=os.path.join(TMP, "donnees_vides"))))
verifier("secret SEC_EMAIL absent : échec explicite", code == 1)
os.environ["SEC_EMAIL"] = CANARI

# ---------------------------------------------------------------------------
print("\n5. Logique JavaScript identique au moteur Python")
node = shutil.which("node")
if not node:
    print("  (Node.js absent : tests JavaScript ignorés)")
else:
    df = pd.DataFrame(lignes).set_index("t")
    cfg_p = sc.Config(n_positions=c["reglages"]["n_positions"], max_par_secteur=c["reglages"]["max_par_secteur"])
    achetables = [l["t"] for l in lignes if l["signal"] == "ACHETER"]
    autres = [l["t"] for l in lignes if l["signal"] in ("GARDER", "SURVEILLER", "VENDRE")]
    cas = [[], achetables[:3], autres[:6] + ["AAPLX"], autres[-5:] + achetables[-2:], [l["t"] for l in lignes][::3]]
    script = os.path.join(TMP, "parite.js")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write("const fs = require('fs');\n"
                 f"const L = require({json.dumps(os.path.join(RACINE, 'web', 'logique.js'))});\n"
                 f"const c = L.preparerClassement(JSON.parse(fs.readFileSync({json.dumps(os.path.join(site, 'data', 'classement.json'))}, 'utf8')));\n"
                 f"const cas = {json.dumps(cas)};\n"
                 "const out = cas.map((p) => L.construirePortefeuille(c, p));\n"
                 "out.push({csv: L.csv([['=CMD', 1.5, 'a;b', null]], ['x', 'y', 'z', 'w']), liste: L.lireListeTickers('aapl, brk.b; MSFT msft\\nTicker'),"
                 " zero: L.fPct(-0.00001, 1), nb: L.fNb(-0.2, 0), g: L.graduations(-0.004, 0.35, 5)});\n"
                 "console.log(JSON.stringify(out));\n")
    sortie = json.loads(subprocess.run([node, script], capture_output=True, text=True, check=True).stdout)
    ecarts = []
    for p, js in zip(cas, sortie):
        g, a, v = sc.construire_portefeuille(df, p, cfg_p, hors_univers="HORS")
        hors_py = [t for t, m in v if m == "HORS"]
        ventes_py = [t for t, m in v if m != "HORS"]
        if (g, a, ventes_py, hors_py) != (js["gardes"], js["achats"], [x["t"] for x in js["ventes"]], js["hors"]):
            ecarts.append((p[:3], a[:5], js["achats"][:5]))
    verifier("portefeuille cible : JavaScript = Python sur 5 cas", not ecarts, str(ecarts[:1]))
    extra = sortie[-1]
    verifier("CSV : pas de formule exécutable, séparateur protégé", extra["csv"].startswith("﻿x;y;z;w\r\n'=CMD;1,5;\"a;b\";"),
             repr(extra["csv"][:40]))
    verifier("saisie de tickers : normalisée et dédoublonnée", extra["liste"] == ["AAPL", "BRK-B", "MSFT"], str(extra["liste"]))
    verifier("pas de « -0 » affiché", extra["zero"] == "0,0 %" and extra["nb"] == "0", f"{extra['zero']!r} {extra['nb']!r}")
    verifier("graduations sans -0", "-0" not in json.dumps(extra["g"]) and 0 in extra["g"], str(extra["g"]))

shutil.rmtree(TMP, ignore_errors=True)
print(f"\nRésultat : {len(OK)} tests réussis, {len(KO)} échecs")
if KO:
    print("Échecs :", KO)
    sys.exit(1)
