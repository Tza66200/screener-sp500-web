"""Sources de données simulées pour l'aperçu de l'application et les tests (aucun accès au réseau).

Les sociétés, tickers et chiffres sont FICTIFS. Les fichiers imitent la structure exacte des vraies
sources : JSON « companyfacts » de la SEC, cours Yahoo (rendement total, ajusté des divisions,
divisions d'actions), composition historique de l'indice.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

import donnees_simulees as ds

# Répartition proche de celle du S&P 500 par secteur (en nombre de sociétés)
POIDS_SECTEURS = {"Information Technology": 69, "Health Care": 60, "Financials": 72, "Consumer Discretionary": 50,
                  "Industrials": 78, "Communication Services": 23, "Consumer Staples": 37, "Energy": 22,
                  "Utilities": 31, "Real Estate": 31, "Materials": 27}
SOUS_SECTEURS = {
    "Information Technology": ["Semiconductors", "Application Software", "Systems Software",
                               "Electronic Components", "IT Consulting & Other Services"],
    "Health Care": ["Pharmaceuticals", "Biotechnology", "Health Care Equipment", "Managed Health Care",
                    "Life Sciences Tools & Services"],
    "Financials": ["Diversified Banks", "Regional Banks", "Property & Casualty Insurance",
                   "Asset Management & Custody Banks", "Transaction & Payment Processing Services"],
    "Consumer Discretionary": ["Restaurants", "Homebuilding", "Apparel Retail", "Automobile Manufacturers",
                               "Hotels, Resorts & Cruise Lines"],
    "Industrials": ["Aerospace & Defense", "Industrial Machinery", "Rail Transportation",
                    "Building Products", "Electrical Components & Equipment"],
    "Communication Services": ["Interactive Media & Services", "Integrated Telecommunication Services",
                               "Movies & Entertainment"],
    "Consumer Staples": ["Packaged Foods & Meats", "Household Products", "Soft Drinks & Non-alcoholic Beverages",
                         "Consumer Staples Merchandise Retail"],
    "Energy": ["Integrated Oil & Gas", "Oil & Gas Exploration & Production", "Oil & Gas Refining & Marketing"],
    "Utilities": ["Electric Utilities", "Multi-Utilities", "Water Utilities"],
    "Real Estate": ["Industrial REITs", "Residential REITs", "Data Center REITs", "Health Care REITs"],
    "Materials": ["Specialty Chemicals", "Construction Materials", "Steel", "Paper & Plastic Packaging Products"],
}
SUFFIXES = {
    "Information Technology": ["Systems", "Semiconducteurs", "Logiciels", "Réseaux", "Data"],
    "Health Care": ["Santé", "Biotech", "Pharma", "Médical", "Diagnostics"],
    "Financials": ["Banque", "Assurances", "Capital", "Gestion", "Paiements"],
    "Consumer Discretionary": ["Maison", "Mode", "Loisirs", "Automobiles", "Restauration"],
    "Industrials": ["Industries", "Aéronautique", "Machines", "Transports", "Équipements"],
    "Communication Services": ["Médias", "Télécom", "Studios"],
    "Consumer Staples": ["Alimentation", "Boissons", "Distribution", "Hygiène"],
    "Energy": ["Énergie", "Pétrole", "Raffinage"],
    "Utilities": ["Électricité", "Réseaux urbains", "Eaux"],
    "Real Estate": ["Foncière", "Immobilier", "Entrepôts"],
    "Materials": ["Chimie", "Matériaux", "Aciers", "Emballages"],
}
DEBUTS = ["Al", "Bor", "Cal", "Dor", "El", "Fen", "Gal", "Har", "Iv", "Jun", "Kel", "Lor", "Mar", "Nor", "Or",
          "Pel", "Quin", "Ros", "Sel", "Tor", "Ul", "Val", "Wes", "Yar", "Zen", "Ast", "Bel", "Cor", "Del", "Est"]
MILIEUX = ["a", "e", "i", "o", "en", "ar", "or", "an", "il", "u"]
FINS = ["ex", "on", "ia", "is", "um", "ar", "ent", "ix", "ane", "ode", "ys", "ora"]


def univers_demo(n: int = 500, graine: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(graine)
    total = sum(POIDS_SECTEURS.values())
    secteurs = []
    for s, p in POIDS_SECTEURS.items():
        secteurs += [s] * max(2, round(p * n / total))
    secteurs = secteurs[:n]
    noms, tickers, lignes = set(), set(), []
    for k, s in enumerate(secteurs):
        while True:
            base = rng.choice(DEBUTS) + rng.choice(MILIEUX) + rng.choice(FINS)
            if base not in noms:
                noms.add(base)
                break
        while True:
            t = f"{base[:2].upper()}{int(rng.integers(10, 99))}"
            if t not in tickers:
                tickers.add(t)
                break
        lignes.append({"ticker": t, "nom": f"{base} {rng.choice(SUFFIXES[s])}", "secteur": s,
                       "sous_secteur": str(rng.choice(SOUS_SECTEURS[s])), "cik": 100000 + k,
                       "qualite": float(rng.beta(2.2, 2.2))})
    return pd.DataFrame(lignes)


def construire_demo(n: int = 500) -> dict:
    u = univers_demo(n)
    jsons = {}
    for k, r in u.iterrows():
        opts = {}
        if r["secteur"] == "Financials":
            opts["banque"] = True
        if k % 37 == 1:
            opts.update(fy_mois_fin=9, semaines=True)
        if k % 53 == 9:
            opts["capex_eleve"] = True
        if k % 41 == 10:
            opts["dette_elevee"] = True
        if k % 29 == 12:
            opts["multi_classes"] = True
        if k % 31 == 13:
            opts["debut_xbrl"] = pd.Timestamp("2010-07-01").date()
        js, _ = ds.societe(int(r["cik"]), 1000 + k, r["qualite"], **opts)
        js["entityName"] = r["nom"]
        jsons[int(r["cik"])] = js
    rng = np.random.default_rng(23)
    jours = pd.bdate_range("2009-01-02", "2026-10-16")
    nj = len(jours)
    marche = 0.00038 + 0.011 * rng.standard_normal(nj)
    facteurs_sect = {s: 0.004 * rng.standard_normal(nj) for s in POIDS_SECTEURS}
    prix = {}
    for _, r in u.iterrows():
        q = r["qualite"]
        beta = 0.55 + 0.9 * (1 - q) + 0.15 * rng.standard_normal()
        sig = 0.009 + 0.016 * (1 - q)
        drift = (0.025 + 0.11 * (q - 0.5)) / 252
        ret = drift + beta * marche + facteurs_sect[r["secteur"]] + sig * rng.standard_normal(nj)
        s = (20 + 180 * rng.random()) * np.exp(np.cumsum(ret) - np.cumsum(ret)[-1])
        prix[r["ticker"]] = s
    entrees = u.sample(12, random_state=3)["ticker"].tolist()      # entrées dans l'indice après 2014
    for k, t in enumerate(entrees):
        prix[t][: int(nj * (0.25 + 0.04 * k))] = np.nan
    prix["SPY"] = 400 * np.exp(np.cumsum(marche + 0.00012) - np.sum(marche + 0.00012))
    prix["RSP"] = 160 * np.exp(np.cumsum(marche * 1.04) - np.sum(marche * 1.04))
    prix["^IRX"] = np.clip(2.0 + np.cumsum(0.004 * rng.standard_normal(nj)), 0.05, 5.5)
    close = pd.DataFrame(prix, index=jours)
    splits = pd.DataFrame(0.0, index=jours, columns=close.columns)
    base = [t for t in u["ticker"] if t not in entrees]
    disparus = [f"ZZ{k:02d}" for k in range(15)]                    # sociétés rachetées : pas de cours
    hist = pd.DataFrame({"date": pd.to_datetime(["2008-12-31", "2016-06-01", "2019-03-01", "2022-09-01"]),
                         "tickers": [sorted(base + disparus), sorted(base + disparus[:6] + entrees[:4]),
                                     sorted(base + entrees[:8]), sorted(base + entrees)]})
    actuel = u[["ticker", "nom", "secteur", "sous_secteur", "cik"]].copy()
    actuel.attrs["source"] = "Données simulées"
    return {"univers": u, "actuel": actuel, "hist": hist, "close": close, "splits": splits, "jsons": jsons}


def installer(sc, n: int = None, date_fin: str = "2026-10-16") -> dict:
    """Remplace les sources réseau du moteur par les données simulées. Renvoie les données."""
    n = n or int(os.environ.get("DEMO_TITRES", "500"))
    D = construire_demo(n)
    etat = {"fin": pd.Timestamp(date_fin)}

    class FauxSEC:
        def __init__(self, cfg):
            pass

        def table_tickers(self):
            return {sc.cle_ticker(r.ticker): (int(r.cik), r.nom) for r in D["actuel"].itertuples()}

        def faits(self, cik):
            js = D["jsons"].get(int(cik))
            return sc.extraire_faits(js) if js else pd.DataFrame(columns=sc.COLONNES_FAITS)

        def sic(self, cik):
            return 3570

    def faux_prix(tickers, debut, cfg):
        c = D["close"].loc[D["close"].index <= etat["fin"]]
        cols = [t for t in sorted(set(tickers)) if t in c.columns]
        m = c.index >= pd.Timestamp(debut)
        sc.ETAT_SOURCES["cours"] = {"demandes": len(set(tickers)), "obtenus": len(cols), "par_alpaca": [],
                                    "derniere_seance": str(c.index.max().date())}
        return {"adj": c.loc[m, cols], "close": c.loc[m, cols], "splits": D["splits"].loc[c.index[m], cols]}

    def fausses_revisions(tickers, cfg):
        r = np.random.default_rng(int(etat["fin"].strftime("%Y%m%d")) % 1000)
        s = pd.Series(r.normal(0.01, 0.06, len(tickers)), index=list(tickers))
        sc.ETAT_SOURCES["revisions"] = {"demandes": len(tickers), "obtenues": len(tickers)}
        return s

    sc.charger_sp500_actuel = lambda cfg: D["actuel"]
    sc.charger_historique = lambda cfg: D["hist"]
    sc.telecharger_prix = faux_prix
    sc.ClientSEC = FauxSEC
    sc.lire_revisions = fausses_revisions
    sc.lire_capitalisations = lambda tickers: pd.Series(2e10, index=list(tickers))
    sc.charger_taux_sans_risque = lambda cfg: None
    sc.aujourdhui = lambda: etat["fin"]

    def fixer_date(d: str):
        etat["fin"] = pd.Timestamp(d)
    D["fixer_date"] = fixer_date
    return D
