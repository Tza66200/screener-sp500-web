"""Données simulées imitant la structure réelle des sources (SEC companyfacts, Yahoo, composition)."""
import datetime as dt

import numpy as np
import pandas as pd

AUJ = pd.Timestamp("2026-10-18")
SECTEURS = (["Information Technology"] * 8 + ["Health Care"] * 6 + ["Industrials"] * 6
            + ["Consumer Discretionary"] * 5 + ["Energy"] * 5 + ["Financials"] * 6
            + ["Utilities"] * 3 + ["Real Estate"] * 2)   # 41 sociétés


def _fin_mois(y, m):
    if m == 12:
        return dt.date(y, 12, 31)
    return dt.date(y, m + 1, 1) - dt.timedelta(days=1)


def trimestres(fy_mois_fin=12, semaines=False, debut=2006, fin=2027):
    """Liste (exercice, n, début, fin) des trimestres fiscaux."""
    out = []
    for fy in range(debut, fin + 1):
        for n in range(1, 5):
            m = (fy_mois_fin + 3 * n - 1) % 12 + 1          # mois de fin du trimestre
            y = fy if m <= fy_mois_fin else fy - 1
            if fy_mois_fin == 12:
                y = fy
            e = _fin_mois(y, m)
            if semaines:
                e = e - dt.timedelta(days=(e.weekday() - 5) % 7)   # dernier samedi
            out.append([fy, n, None, e])
    out.sort(key=lambda r: r[3])
    for k, r in enumerate(out):
        r[2] = out[k - 1][3] + dt.timedelta(days=1) if k else r[3] - dt.timedelta(days=90)
    return out


def societe(cik, graine, qualite, banque=False, fy_mois_fin=12, semaines=False, retraitement=False,
            sans_sga=False, sans_interets=False, capex_eleve=False, dette_elevee=False, division=None, multi_classes=False, debut_xbrl=None):
    rng = np.random.default_rng(graine)
    tri = trimestres(fy_mois_fin, semaines)
    n = len(tri)
    t = np.arange(n)
    rev = 1e9 * (1 + rng.random()) * (1.012 + 0.01 * qualite) ** t * (1 + 0.03 * rng.standard_normal(n))
    gm = np.clip(0.25 + 0.35 * qualite + 0.02 * rng.standard_normal(n), 0.05, 0.9)
    actif = rev * 4 * (1.3 - 0.4 * qualite)
    levier = (0.35 - 0.2 * qualite) * (2.5 if dette_elevee else 1.0)
    dette_lt = actif * levier
    interet = dette_lt * 0.012
    sga = rev * (0.12 - 0.04 * qualite)
    da = rev * 0.04
    ebit = rev * gm - sga - da
    if banque:
        gm[:] = np.nan
        interet = rev * 0.35
        ebit = rev * 0.45
        actif = rev * 40
        dette_lt = actif * 0.05
    pretax = ebit - interet
    rn = pretax * 0.79
    cfo = rn + da + rev * (0.02 * qualite - 0.01) + 0.01 * rev * rng.standard_normal(n)
    capex = rev * (0.25 if capex_eleve else 0.05)
    actions = 5e8 * (1 + 0.003 * (1 - qualite) - 0.006 * qualite) ** t
    q = {"rev": rev, "cogs": rev * (1 - np.nan_to_num(gm, nan=0.0)), "gp": rev * gm, "ebit": ebit,
         "pretax": pretax, "rn": rn, "int": interet, "sga": sga, "cfo": cfo, "capex": capex, "da": da}
    bilan = {"Assets": actif, "AssetsCurrent": 0.35 * actif, "LiabilitiesCurrent": 0.2 * actif,
             "StockholdersEquity": actif * ((0.1 if banque else 0.4 + 0.2 * qualite)),
             "CashAndCashEquivalentsAtCarryingValue": 0.08 * actif, "LongTermDebtNoncurrent": dette_lt,
             "LongTermDebtCurrent": 0.02 * actif, "AccountsReceivableNetCurrent": 0.12 * actif,
             "PropertyPlantAndEquipmentNet": 0.3 * actif}
    bilan["Liabilities"] = actif - bilan["StockholdersEquity"]
    bilan["LiabilitiesAndStockholdersEquity"] = actif.copy()
    if banque:
        for k in ("AssetsCurrent", "LiabilitiesCurrent"):
            bilan.pop(k)

    faits = {}

    def ajouter(tag, unite, deb, fin_, val, accn, fy, fp, form, depot):
        if not np.isfinite(val):
            return
        e = {"end": str(fin_), "val": float(val), "accn": accn, "fy": fy, "fp": fp, "form": form,
             "filed": str(depot)}
        if deb is not None:
            e["start"] = str(deb)
        ns = "dei" if tag == "EntityCommonStockSharesOutstanding" else "us-gaap"
        faits.setdefault(ns, {}).setdefault(tag, {"units": {}})["units"].setdefault(unite, []).append(e)

    tags_flux = {"rev": None, "cogs": "CostOfRevenue", "gp": "GrossProfit", "ebit": "OperatingIncomeLoss",
                 "pretax": "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                 "rn": "NetIncomeLoss", "int": "InterestExpense", "sga": "SellingGeneralAndAdministrativeExpense"}
    if banque:
        for k in ("cogs", "gp"):
            tags_flux.pop(k)
    if sans_sga:
        tags_flux.pop("sga")
    if sans_interets:
        tags_flux.pop("int")
    tags_cf = {"cfo": "NetCashProvidedByUsedInOperatingActivities",
               "capex": "PaymentsToAcquirePropertyPlantAndEquipment",
               "da": "DepreciationDepletionAndAmortization"}

    def tag_rev(depot):
        if banque:
            return "Revenues"
        return "SalesRevenueNet" if depot < dt.date(2018, 3, 1) else "RevenueFromContractWithCustomerExcludingAssessedTax"

    par_fy = {}
    for k, (fy, nq, d0, d1) in enumerate(tri):
        par_fy.setdefault(fy, []).append(k)

    def somme(cle, ks):
        return float(np.sum(q[cle][ks]))

    for k, (fy, nq, d0, d1) in enumerate(tri):
        if nq == 4:
            continue
        depot = d1 + dt.timedelta(days=40 + int(rng.integers(0, 5)))
        if depot.year < 2009 or pd.Timestamp(depot) > AUJ or (debut_xbrl and depot < debut_xbrl):
            continue
        accn = f"{cik:010d}-{fy}-Q{nq}"
        ks = par_fy[fy][:nq]
        kp = [x - 4 for x in ks]
        d_fy = tri[ks[0]][2]
        d_fy_p = tri[kp[0]][2]
        for cle, tag in tags_flux.items():
            tg = tag or tag_rev(depot)
            ajouter(tg, "USD", d0, d1, q[cle][k], accn, fy, f"Q{nq}", "10-Q", depot)
            ajouter(tg, "USD", tri[k - 4][2], tri[k - 4][3], q[cle][k - 4], accn, fy, f"Q{nq}", "10-Q", depot)
            if nq >= 2:
                ajouter(tg, "USD", d_fy, d1, somme(cle, ks), accn, fy, f"Q{nq}", "10-Q", depot)
                ajouter(tg, "USD", d_fy_p, tri[kp[-1]][3], somme(cle, kp), accn, fy, f"Q{nq}", "10-Q", depot)
        for cle, tag in tags_cf.items():
            ajouter(tag, "USD", d_fy, d1, somme(cle, ks), accn, fy, f"Q{nq}", "10-Q", depot)
            ajouter(tag, "USD", d_fy_p, tri[kp[-1]][3], somme(cle, kp), accn, fy, f"Q{nq}", "10-Q", depot)
        k_fy_prec = par_fy[fy - 1][-1]
        for tag, serie in bilan.items():
            ajouter(tag, "USD", None, d1, serie[k], accn, fy, f"Q{nq}", "10-Q", depot)
            ajouter(tag, "USD", None, tri[k_fy_prec][3], serie[k_fy_prec], accn, fy, f"Q{nq}", "10-Q", depot)
        couv = depot - dt.timedelta(days=3)
        if multi_classes:
            ajouter("CommonStockSharesOutstanding", "shares", None, d1, actions[k], accn, fy, f"Q{nq}", "10-Q", depot)
        else:
            ajouter("EntityCommonStockSharesOutstanding", "shares", None, couv,
                    actions[k] * (4 if division and couv >= division else 1), accn, fy, f"Q{nq}", "10-Q", depot)
        ajouter("WeightedAverageNumberOfDilutedSharesOutstanding", "shares", d0, d1,
                actions[k] * (4 if division and d1 >= division else 1), accn, fy, f"Q{nq}", "10-Q", depot)

    for fy, ks in par_fy.items():
        if len(ks) < 4 or fy - 2 not in par_fy:
            continue
        k4 = ks[-1]
        d1 = tri[k4][3]
        depot = d1 + dt.timedelta(days=55 + int(rng.integers(0, 6)))
        if depot.year < 2009 or pd.Timestamp(depot) > AUJ or (debut_xbrl and depot < debut_xbrl):
            continue
        accn = f"{cik:010d}-{fy}-K"
        for decal in (0, 1, 2):
            kk = par_fy[fy - decal]
            for cle, tag in list(tags_flux.items()) + list(tags_cf.items()):
                tg = tag or tag_rev(depot)
                val = somme(cle, kk)
                if retraitement and fy == 2015 and decal == 1 and cle == "rn":
                    val *= 1.2   # chiffre de 2014 retraité dans le 10-K 2015
                ajouter(tg, "USD", tri[kk[0]][2], tri[kk[-1]][3], val, accn, fy, "FY", "10-K", depot)
        for decal in (0, 1):
            kk = par_fy[fy - decal][-1]
            for tag, serie in bilan.items():
                ajouter(tag, "USD", None, tri[kk][3], serie[kk], accn, fy, "FY", "10-K", depot)
        couv = depot - dt.timedelta(days=3)
        if multi_classes:
            ajouter("CommonStockSharesOutstanding", "shares", None, d1, actions[k4], accn, fy, "FY", "10-K", depot)
        else:
            ajouter("EntityCommonStockSharesOutstanding", "shares", None, couv,
                    actions[k4] * (4 if division and couv >= division else 1), accn, fy, "FY", "10-K", depot)
        ajouter("WeightedAverageNumberOfDilutedSharesOutstanding", "shares", tri[ks[0]][2], d1,
                float(np.mean(actions[ks])), accn, fy, "FY", "10-K", depot)
    verite = {"tri": tri, "q": q, "bilan": bilan, "actions": actions}
    return {"cik": cik, "entityName": f"Societe {cik}", "facts": faits}, verite


def univers():
    rng = np.random.default_rng(7)
    lignes = []
    for k, sect in enumerate(SECTEURS):
        lignes.append({"ticker": f"T{k:02d}", "nom": f"Société {k:02d}", "secteur": sect,
                       "sous_secteur": "", "cik": 1000 + k, "qualite": float(rng.random())})
    lignes[3]["ticker"] = "NEW1"        # ancien ticker OLD1 (renommage en 2018)
    lignes.append({"ticker": "ADD1", "nom": "Société ajoutée", "secteur": "Information Technology",
                   "sous_secteur": "", "cik": 2000, "qualite": 0.7})
    u = pd.DataFrame(lignes)
    return u


def construire(dossier_json=None):
    u = univers()
    jsons, verites = {}, {}
    for k, r in u.iterrows():
        opts = {}
        if r["secteur"] == "Financials":
            opts["banque"] = True
        if k == 1:
            opts.update(fy_mois_fin=9, semaines=True)
        if k == 2:
            opts["retraitement"] = True
        if k == 5:
            opts["sans_sga"] = True
        if k == 6:
            opts["sans_interets"] = True
        if k == 9:
            opts["capex_eleve"] = True
        if k == 10:
            opts["dette_elevee"] = True
        if k == 7:
            opts["division"] = dt.date(2020, 8, 31)
        if k == 12:
            opts["multi_classes"] = True
        if k in (13, 14, 15, 16):
            opts["debut_xbrl"] = dt.date(2010, 7, 1)    # sociétés passées au XBRL en 2010
        js, ver = societe(int(r["cik"]), 100 + k, r["qualite"], **opts)
        jsons[int(r["cik"])] = js
        verites[int(r["cik"])] = ver
    # Cours
    rng = np.random.default_rng(11)
    jours = pd.bdate_range("2009-01-02", "2026-10-16")
    n = len(jours)
    marche = 0.00035 + 0.011 * rng.standard_normal(n)
    prix = {}
    for k, r in u.iterrows():
        q = r["qualite"]
        beta = 0.6 + 0.9 * (1 - q)
        sig = 0.010 + 0.015 * (1 - q)
        drift = (0.02 + 0.10 * (q - 0.5)) / 252
        ret = drift + beta * marche + sig * rng.standard_normal(n)
        s = 50 * np.exp(np.cumsum(ret))
        if r["ticker"] == "ADD1":
            s[: n // 2] = np.nan     # introduite en bourse plus tard
        prix[r["ticker"]] = s
    prix["SPY"] = 100 * np.exp(np.cumsum(marche + 0.0001))
    prix["RSP"] = 100 * np.exp(np.cumsum(marche * 1.05))
    prix["^IRX"] = np.full(n, 2.0)
    close = pd.DataFrame(prix, index=jours)
    splits = pd.DataFrame(0.0, index=jours, columns=close.columns)
    splits.loc[pd.Timestamp("2020-08-31"), "T07"] = 4.0
    # Composition historique : GONE (sans cours) sort en 2015, OLD1 -> NEW1 en 2018, ADD1 entre en 2020
    base = [t for t in u["ticker"] if t not in ("NEW1", "ADD1")]
    hist = pd.DataFrame({
        "date": pd.to_datetime(["2008-12-31", "2015-06-01", "2018-06-01", "2020-03-02"]),
        "tickers": [sorted(base + ["OLD1", "GONE"]), sorted(base + ["OLD1"]),
                    sorted(base + ["NEW1"]), sorted(base + ["NEW1", "ADD1"])]})
    actuel = u[["ticker", "nom", "secteur", "sous_secteur", "cik"]].copy()
    return {"univers": u, "actuel": actuel, "hist": hist, "close": close, "splits": splits, "jsons": jsons,
            "verites": verites}
