"""Moteur point-in-time sur de VRAIS fichiers companyfacts de la SEC (10 sociétés du S&P 500).

Chiffres de référence : rapports annuels 10-K publiés (chiffre d'affaires et résultat net).
Contrôles indépendants : 12 mois glissants = somme des 4 trimestres reconstitués à partir des faits bruts.
"""
import gzip
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import screener_sp500 as sc  # noqa: E402

D = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "donnees_sec")
OK, KO = [], []


def verifier(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("  OK  " if cond else "  ÉCHEC ") + nom + (f"  ({detail})" if detail else ""))


def charger(cik):
    js = json.load(gzip.open(os.path.join(D, f"{cik}.json.gz")))
    return js, sc.table_fondamentale(sc.extraire_faits(js))


def ligne(t, fin):
    x = t[t["fin"] == pd.Timestamp(fin)]
    return x.iloc[0] if len(x) else None


print("\n1. Totaux annuels publiés (10-K)")
REF = [  # cik, société, fin d'exercice, chiffre d'affaires, résultat net (milliards de $)
    (320193, "Apple", "2024-09-28", 391.035, 93.736), (320193, "Apple", "2025-09-27", 416.161, 112.010),
    (21344, "Coca-Cola", "2024-12-31", 47.061, 10.631), (59478, "Eli Lilly", "2024-12-31", 45.043, 10.590),
    (40533, "General Dynamics", "2024-12-31", 47.716, 3.782), (721371, "Cardinal Health", "2025-06-30", 222.578, 1.561),
]
tables = {}
for cik, nom, fin, ca, rn in REF:
    if cik not in tables:
        tables[cik] = charger(cik)
    _, t = tables[cik]
    x = ligne(t, fin)
    ok = x is not None and abs(x["revenus"] / 1e9 / ca - 1) < 0.005 and abs(x["resultat_net"] / 1e9 / rn - 1) < 0.005
    verifier(f"{nom} {fin[:4]} : CA et résultat net", ok,
             "absent" if x is None else f"CA {x['revenus'] / 1e9:.2f} (réf. {ca}), RN {x['resultat_net'] / 1e9:.2f} (réf. {rn})")

print("\n2. Douze mois glissants = somme de 4 trimestres reconstitués indépendamment")


def trimestres_bruts(js, tags):
    """Trimestres isolés : faits de 3 mois, et T4 = exercice - 9 mois. Première publication."""
    pts = []
    for tag in tags:
        for r in js["facts"]["us-gaap"].get(tag, {}).get("units", {}).get("USD", []):
            if r.get("form") in sc.FORMULAIRES and r.get("start"):
                pts.append((pd.Timestamp(r["start"]), pd.Timestamp(r["end"]), float(r["val"]), r["filed"]))
    df = pd.DataFrame(pts, columns=["deb", "fin", "val", "depot"]).sort_values("depot")
    df = df.drop_duplicates(["deb", "fin"], keep="first")
    df["jours"] = (df["fin"] - df["deb"]).dt.days
    q = {r.fin: r.val for r in df[df["jours"].between(80, 100)].itertuples()}
    for r in df[df["jours"].between(350, 380)].itertuples():
        neuf = df[(df["deb"] == r.deb) & df["jours"].between(260, 285)]
        if len(neuf) and r.fin not in q:
            q[r.fin] = r.val - neuf["val"].iloc[0]
    return pd.Series(q).sort_index()


for cik, nom, tags in [(320193, "Apple", ["RevenueFromContractWithCustomerExcludingAssessedTax"]),
                       (21344, "Coca-Cola", ["Revenues"]), (59478, "Eli Lilly", ["Revenues"]),
                       (721371, "Cardinal Health", ["Revenues"])]:
    js, t = tables[cik]
    q = trimestres_bruts(js, tags)
    ecarts = []
    for _, x in t[t["fin"] >= "2019-01-01"].iterrows():
        prec = q[(q.index <= x["fin"] + pd.Timedelta(days=5)) & (q.index > x["fin"] - pd.Timedelta(days=360))]
        if len(prec) == 4 and np.isfinite(x["revenus"]):
            ecarts.append(abs(x["revenus"] / prec.sum() - 1))
    verifier(f"{nom} : CA 12 mois glissants (depuis 2019)", len(ecarts) >= 20 and np.median(ecarts) < 1e-6
             and max(ecarts) < 0.02, f"{len(ecarts)} trimestres, écart médian {np.median(ecarts):.1e}, max {max(ecarts):.2%}")

print("\n3. Dette, intérêts et EBIT (étiquettes de repli)")
for cik in (1534701, 906163, 879169, 936340, 1841666):
    tables[cik] = charger(cik)
_, psx = tables[1534701]
x = psx.iloc[-1]
verifier("Phillips 66 : EBIT reconstitué (résultat net + impôt + intérêts)", np.isfinite(x["ebit"]) and x["ebit"] > x["resultat_net"]
         and np.isfinite(x["couverture"]), f"EBIT {x['ebit'] / 1e9:.2f} Md, couverture {x['couverture']:.1f}x")
_, gd = tables[40533]
x = gd.iloc[-1]
verifier("General Dynamics : couverture via la charge nette d'intérêts", np.isfinite(x["couverture"]) and 5 < x["couverture"] < 40,
         f"{x['couverture']:.1f}x")
verifier("General Dynamics : dette totale ~8 Md$", 6e9 < x["dette"] < 11e9, f"{x['dette'] / 1e9:.2f}")
_, aapl = tables[320193]
x = aapl.iloc[-1]
verifier("Apple : dette (long terme + échéances + billets de trésorerie)", 70e9 < x["dette"] < 120e9, f"{x['dette'] / 1e9:.1f} Md")
verifier("Apple : ~14,6 milliards d'actions", 14.0e9 < x["actions"] < 15.2e9, f"{x['actions'] / 1e9:.2f}")
_, nvr = tables[906163]
verifier("NVR : dette au bilan non reconnue mais intérêts versés -> inconnue (pas nulle)", np.isnan(nvr.iloc[-1]["dette"]))
_, incy = tables[879169]
verifier("Incyte : intérêts minimes (locations) -> dette nulle, trésorerie nette", incy.iloc[-1]["dette"] == 0
         and incy.iloc[-1]["dette_ebitda"] < 0)
_, ko = tables[21344]
verifier("Coca-Cola : dette totale 40-50 Md$", 40e9 < ko.iloc[-1]["dette"] < 50e9, f"{ko.iloc[-1]['dette'] / 1e9:.1f}")

print("\n4. Indicateurs plausibles pour les 10 sociétés")
for f in sorted(os.listdir(D)):
    if not f.endswith(".json.gz") or "submissions" in f:
        continue
    cik = int(f.split(".")[0])
    js, t = tables.get(cik) or charger(cik)
    x = t.iloc[-1]
    nom = js["entityName"]
    fs9 = x["fscore"] * 9 / x["fscore_n"]
    ok = (len(t) >= 20 and x["fscore_n"] >= 6 and 0 <= fs9 <= 9 and x["actif"] > 1e9 and x["actions"] > 1e6
          and (pd.Timestamp("2026-10-18") - x["dispo"]).days < 200)
    verifier(f"{nom} : table exploitable, F-score calculable, comptes récents", ok,
             f"{len(t)} trimestres, F-score {fs9:.1f}/9 sur {int(x['fscore_n'])} signaux, dernier dépôt {x['dispo'].date()}")

print(f"\nRésultat : {len(OK)} tests réussis, {len(KO)} échecs")
if KO:
    print("Échecs :", KO)
    sys.exit(1)
