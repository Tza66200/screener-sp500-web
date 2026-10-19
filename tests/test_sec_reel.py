"""Moteur point-in-time sur de VRAIS fichiers companyfacts de la SEC (20 sociétés du S&P 500).

Chiffres de référence : rapports annuels 10-K publiés (chiffre d'affaires et résultat net).
Contrôles indépendants : 12 mois glissants = somme des 4 trimestres reconstitués à partir des faits bruts.
Cas particuliers : changement de date de clôture, scission récente, nouvelle holding, total d'actif absent.
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
_, apa = tables[1841666]
x = apa[apa["fin"] == "2025-12-31"].iloc[0]
verifier("APA : CA reconstitué (résultat d'exploitation + charges), investissements pétroliers reconnus",
         abs(x["revenus"] - 9.516e9) < 1e6 and abs(x["capex"] - 2.740e9) < 1e6 and np.isfinite(apa.iloc[-1]["fcf"])
         and apa.iloc[-1]["fscore_n"] >= 8, f"CA {x['revenus'] / 1e9:.2f} Md$, capex {x['capex'] / 1e9:.2f} Md$")
_, lly = tables[59478]
x = lly.iloc[-1]
verifier("Eli Lilly : intérêts publiés au seul rapport annuel -> couverture sur le dernier exercice (2025)",
         abs(x["charges_interets"] - 895e6) < 1e6 and 20 < x["couverture"] < 60,
         f"intérêts {x['charges_interets'] / 1e6:.0f} M$, couverture {x['couverture']:.1f}x au {x['fin'].date()}")
verifier("Apple : intérêts plus publiés depuis 2023 -> couverture inconnue (pas de valeur périmée)",
         np.isnan(aapl.iloc[-1]["couverture"]))

print("\n4. Indicateurs plausibles pour les 10 sociétés à long historique")
for cik in (320193, 21344, 59478, 40533, 721371, 1534701, 1841666, 879169, 906163, 936340):
    js, t = tables.get(cik) or charger(cik)
    x = t.iloc[-1]
    nom = js["entityName"]
    fs9 = x["fscore"] * 9 / x["fscore_n"]
    ok = (len(t) >= 20 and x["fscore_n"] >= 6 and 0 <= fs9 <= 9 and x["actif"] > 1e9 and x["actions"] > 1e6
          and (pd.Timestamp("2026-10-18") - x["dispo"]).days < 200)
    verifier(f"{nom} : table exploitable, F-score calculable, comptes récents", ok,
             f"{len(t)} trimestres, F-score {fs9:.1f}/9 sur {int(x['fscore_n'])} signaux, dernier dépôt {x['dispo'].date()}")

print("\n5. Cas particuliers des comptes récents")
_, ferg = charger(2011641)        # Ferguson : clôture déplacée du 31 juillet au 31 décembre (période de transition)
x = ferg.iloc[-1]
verifier("Ferguson : 12 mois glissants à travers le changement de date de clôture",
         x["fin"] == pd.Timestamp("2026-06-30") and abs(x["revenus"] - (16223e6 + 31316e6 - 15576e6)) < 1e6
         and x["fscore_n"] >= 6, f"CA {x['revenus'] / 1e9:.3f} Md$, F-score sur {int(x['fscore_n'])} critères")
_, wat = charger(1000697)         # Waters : trimestres calendaires ajoutés au rapport annuel
x = wat.iloc[-1]
verifier("Waters : F-score complet malgré les trimestres « calendaires » du rapport annuel",
         x["fscore_n"] >= 7 and abs(x["revenus"] - 4644e6) < 1e6, f"{int(x['fscore_n'])} critères")
_, lennar = charger(920760)       # Lennar : total de l'actif absent du dernier 10-Q
x = lennar.iloc[-1]
verifier("Lennar : total de l'actif = total du passif et des capitaux propres",
         x["fin"] == pd.Timestamp("2026-08-31") and abs(x["actif"] - 33378.2e6) < 1e5, f"{x['actif'] / 1e9:.2f} Md$")
_, qnity = charger(2058873)       # Qnity : scission de DuPont (novembre 2025), comparatifs trimestriels absents
_, blk = charger(2012383)         # BlackRock : nouvelle holding depuis octobre 2024
pan = sc.panneau_fondamental({2058873: qnity, 2012383: blk})
x = sc.fondamentaux_aux_dates(pan, ["2026-10-16"], [2058873, 2012383]).set_index("cik")
verifier("scission récente : le dernier rapport complet (annuel 2025) reste en vigueur",
         qnity.iloc[-1]["fscore_n"] < 6 and x.at[2058873, "fin"] == pd.Timestamp("2025-12-31")
         and x.at[2058873, "fscore_n"] >= 6, f"{qnity.iloc[-1]['fscore_n']:.0f} critères au dernier trimestre")
verifier("nouvelle holding : rapport complet retenu", x.at[2012383, "fscore_n"] >= 6, f"{x.at[2012383, 'fin'].date()}")
_, xom = charger(2115436)         # ExxonMobil Holdings : un seul 10-Q sous le nouveau numéro CIK
verifier("ExxonMobil Holdings seule : historique insuffisant (d'où la fusion avec l'ancienne société)",
         len(xom) == 1 and xom.iloc[-1]["fscore_n"] < 6 and sc.PREDECESSEURS.get(2115436) == 34088)

_, dis = charger(1744489)         # Disney : charge d'intérêts de l'exercice 2025 publiée avec un signe négatif
x = dis.iloc[-1]
verifier("Disney : signe inversé d'une charge d'intérêts corrigé (couverture calculée)",
         1.5e9 < x["charges_interets"] < 2.2e9 and 5 < x["couverture"] < 20, f"{x['couverture']:.1f}x")
_, exr = charger(1289490)         # Extra Space Storage : foncière, sans impôt ni total de la dette
x = exr.iloc[-1]
verifier("Extra Space Storage : EBIT sans ligne d'impôt, dette = somme des lignes du bilan",
         x["ebit"] > 1e9 and 12e9 < x["dette"] < 15e9 and 1.5 < x["couverture"] < 4,
         f"EBIT {x['ebit'] / 1e9:.2f} Md$, dette {x['dette'] / 1e9:.1f} Md$, couverture {x['couverture']:.1f}x")
_, nke = charger(320187)          # Nike : produits d'intérêts nets, intérêts versés publiés à l'exercice
x = nke.iloc[-1]
verifier("Nike : intérêts versés retenus malgré des produits d'intérêts nets",
         abs(x["charges_interets"] - 323e6) < 1e6 and 5 < x["couverture"] < 30, f"{x['couverture']:.1f}x")
_, cost = charger(909832)         # Costco : 4e trimestre de 16 semaines
x = cost[cost["annuel"]].iloc[-1]
verifier("Costco : surprise de résultats du 4e trimestre de 16 semaines", np.isfinite(x["surprise_rn"]),
         f"exercice clos le {x['fin'].date()}")

print(f"\nRésultat : {len(OK)} tests réussis, {len(KO)} échecs")
if KO:
    print("Échecs :", KO)
    sys.exit(1)
