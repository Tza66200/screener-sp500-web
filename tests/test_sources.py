"""Formats réels des sources (yfinance, Alpaca, FRED, SEC) reproduits sans réseau."""
import logging
import os
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import screener_sp500 as sc  # noqa: E402

ICI = os.path.dirname(os.path.abspath(__file__))
SORTIE = os.path.join(tempfile.mkdtemp(prefix="test_sources_"), "sortie")
if os.path.exists(SORTIE):
    shutil.rmtree(SORTIE)
OK, KO = [], []


def verifier(nom, cond, detail=""):
    (OK if cond else KO).append(nom)
    print(("  OK  " if cond else "  ÉCHEC ") + nom + (f"  ({detail})" if detail else ""))


cfg = sc.Config(dossier=SORTIE)

print("\n1. Téléchargement Yahoo : format réel de yfinance 1.x (simulé, réseau bloqué ici)")
import yfinance as yf  # noqa: E402

appels = {"n": 0}
jours = pd.bdate_range("2023-01-02", "2023-03-31")


def faux_download(tickers, start=None, **kw):
    appels["n"] += 1
    assert kw.get("auto_adjust") is False and kw.get("actions") is True
    if appels["n"] == 1:   # premier appel : limitation de débit Yahoo
        logging.getLogger("yfinance").error("['AAA']: YFRateLimitError('Too Many Requests. Rate limited.')")
    champs = ["Adj Close", "Close", "Dividends", "High", "Low", "Open", "Stock Splits", "Volume"]
    cols = pd.MultiIndex.from_product([champs, tickers], names=["Price", "Ticker"])
    df = pd.DataFrame(np.nan, index=pd.DatetimeIndex(jours, name="Date"), columns=cols)
    for k, t in enumerate(tickers):
        if t == "MORT" or (appels["n"] == 1 and t == "AAA"):
            continue        # société disparue : colonnes vides
        base = 100.0 + k
        df[("Close", t)] = base
        df[("Adj Close", t)] = base * 0.98
        df[("Stock Splits", t)] = 0.0
        if t == "BBB":
            df.loc[jours[20], ("Stock Splits", t)] = 2.0
    return df


yf.download = faux_download
sc.time.sleep = lambda s: None
out = sc._yf_telecharger(["AAA", "BBB", "MORT"], pd.Timestamp("2023-01-01"))
verifier("limitation de débit détectée puis nouvel essai", appels["n"] == 2, f"{appels['n']} appels")
verifier("société disparue ignorée, les autres récupérées", list(out["adj"].columns) == ["AAA", "BBB"],
         list(out["adj"].columns))
verifier("rendement total et cours ajusté des divisions séparés",
         abs(out["adj"]["BBB"].iloc[0] / out["close"]["BBB"].iloc[0] - 0.98) < 1e-12)
f = sc.facteur_divisions(out["splits"], out["adj"].index)
verifier("facteur de division : 2 avant, 1 après", f["BBB"].iloc[0] == 2.0 and f["BBB"].iloc[-1] == 1.0
         and f.loc[jours[20], "BBB"] == 1.0 and f.loc[jours[19], "BBB"] == 2.0)
# cache de prix
appels["n"] = 5
p1 = sc.telecharger_prix(["AAA", "BBB"], "2023-01-01", cfg)
n_apres = appels["n"]
p2 = sc.telecharger_prix(["AAA"], "2023-01-01", cfg)
verifier("cache du jour réutilisé (aucun nouvel appel)", appels["n"] == n_apres and list(p2["adj"].columns) == ["AAA"])

print("\n2. Révisions d'analystes : format réel de eps_trend")
et = pd.DataFrame({"current": [1.0, 1.2, 4.0, 4.6], "7daysAgo": [1.0, 1.2, 4.0, 4.6],
                   "30daysAgo": [1.0, 1.1, 3.9, 4.5], "60daysAgo": [0.9, 1.1, 3.8, 4.4],
                   "90daysAgo": [0.9, 1.0, 3.6, 4.4]}, index=pd.Index(["0q", "+1q", "0y", "+1y"], name="period"))
r = sc._revision(et)
verifier("révision BPA 90 jours = moyenne (exercice, exercice suivant)",
         abs(r - np.mean([(4.0 - 3.6) / 3.6, (4.6 - 4.4) / 4.4])) < 1e-12, f"{r:.4f}")

print("\n3. SEC : refus sans adresse e-mail")
try:
    sc.ClientSEC(sc.Config())
    verifier("adresse e-mail exigée", False)
except ValueError:
    verifier("adresse e-mail exigée", True)
verifier("l'e-mail n'est jamais envoyé à Wikipédia ni à GitHub",
         "@" not in sc._ua_web(sc.Config(email="moi@domaine-test.org"))["User-Agent"])

print("\n4. Alpaca (source de secours) : format réel de l'API v2/stocks/bars (simulé)")
jours_a = pd.bdate_range("2016-01-04", "2016-03-31")
j_div = pd.Timestamp("2016-02-16")
requetes = []


class Reponse:
    def __init__(self, code, js):
        self.status_code, self._js, self.text = code, js, str(js)[:200]

    def json(self):
        return self._js


def faux_get(url, headers=None, params=None, timeout=None):
    assert url == sc.URL_ALPACA and headers["APCA-API-KEY-ID"] == "cle" and headers["APCA-API-SECRET-KEY"] == "secret"
    requetes.append(dict(params))
    syms = params["symbols"].split(",")
    aj = params["adjustment"]

    def barres(sym):
        out = []
        for k, j in enumerate(jours_a):
            brut = 100.0 + k if sym == "AAA" else (300.0 if j < j_div else 150.0)
            if sym == "BRK.B" and aj in ("split", "all") and j < j_div:
                brut /= 2.0
            if aj == "all" and j < pd.Timestamp("2016-03-01"):
                brut *= 0.99                      # dividende détaché le 1er mars
            out.append({"t": (j + pd.Timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ"), "o": brut, "h": brut,
                        "l": brut, "c": brut, "v": 1000, "n": 10, "vw": brut})
        return out
    if params.get("page_token") is None:          # 1re page : le premier symbole seulement
        return Reponse(200, {"bars": {syms[0]: barres(syms[0])}, "next_page_token": "page2" if len(syms) > 1 else None})
    return Reponse(200, {"bars": {s: barres(s) for s in syms[1:]}, "next_page_token": None})


sc.requests.get = faux_get
alp = sc._alpaca_telecharger(["AAA", "BRK-B"], pd.Timestamp("2016-01-01"), ("cle", "secret"))
verifier("Alpaca : pagination suivie, tickers au format Yahoo", list(alp["adj"].columns) == ["AAA", "BRK-B"]
         and any(r.get("page_token") == "page2" for r in requetes), list(alp["adj"].columns))
verifier("Alpaca : symbole BRK.B demandé avec un point", any("BRK.B" in r["symbols"] for r in requetes))
verifier("Alpaca : dates de cotation (heure de New York)", alp["adj"].index[0] == jours_a[0] and len(alp["adj"]) == len(jours_a))
sp = alp["splits"]["BRK-B"]
verifier("Alpaca : division 2 pour 1 détectée le bon jour", sp.loc[j_div] == 2.0 and (sp.drop(j_div) == 0).all())
fa = sc.facteur_divisions(alp["splits"], alp["adj"].index)["BRK-B"]
verifier("Alpaca : facteur de division 2 avant, 1 après", fa.iloc[0] == 2.0 and fa.loc[j_div] == 1.0)
verifier("Alpaca : rendement total (dividende) distinct du cours ajusté des divisions",
         abs(alp["adj"]["AAA"].iloc[0] / alp["close"]["AAA"].iloc[0] - 0.99) < 1e-12)

# Intégration : Yahoo n'a pas BRK-B -> complété par Alpaca, et signalé
os.environ["ALPACA_API_KEY_ID"], os.environ["ALPACA_API_SECRET_KEY"] = "cle", "secret"
appels["n"] = 5


def yahoo_sans_brk(tickers, start=None, **kw):
    df = faux_download(tickers, start=start, **kw)
    return df.drop(columns=[c for c in df.columns if c[1] == "BRK-B"])


yf.download = yahoo_sans_brk
cfg_a = sc.Config(dossier=os.path.join(SORTIE, "alpaca"))
pa = sc.telecharger_prix(["AAA", "BRK-B"], "2016-01-01", cfg_a)
yf.download = faux_download
verifier("Yahoo + Alpaca : le titre manquant chez Yahoo est complété", "BRK-B" in pa["adj"].columns
         and pa["adj"]["BRK-B"].notna().sum() > 50, list(pa["adj"].columns))
verifier("Yahoo + Alpaca : la source de secours est tracée", sc.ETAT_SOURCES["cours"]["par_alpaca"] == ["BRK-B"],
         str(sc.ETAT_SOURCES["cours"]))
del os.environ["ALPACA_API_KEY_ID"], os.environ["ALPACA_API_SECRET_KEY"]

print("\n5. Taux sans risque officiel (FRED, série DTB3) : format CSV réel (simulé)")


class Texte:
    def __init__(self, t):
        self.text = t


csv = "observation_date,DTB3\n" + "\n".join(
    f"{d.date()},{'.' if k % 50 == 7 else f'{1.5 + k / 1000:.2f}'}" for k, d in enumerate(pd.bdate_range("2019-01-01", "2020-06-30")))
vieux_get = sc.http_get
sc.http_get = lambda url, entetes=None, timeout=45, essais=4: Texte(csv) if "fredgraph" in url else vieux_get(url, entetes)
tb = sc.charger_taux_sans_risque(sc.Config(dossier=os.path.join(SORTIE, "fred")))
verifier("FRED : série lue, valeurs manquantes « . » ignorées", tb is not None and len(tb) > 350 and tb.notna().all()
         and abs(tb.iloc[0] - 1.5) < 1e-9, f"{0 if tb is None else len(tb)} jours")
sc.http_get = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("HTTP 403"))
tb2 = sc.charger_taux_sans_risque(sc.Config(dossier=os.path.join(SORTIE, "fred_ko")))
verifier("FRED injoignable : None (le backtest prend ^IRX)", tb2 is None)
sc.http_get = vieux_get

print("\n6. Cache des comptes SEC : relu quand les règles d'extraction changent")
import gzip  # noqa: E402
import json  # noqa: E402

with gzip.open(os.path.join(ICI, "donnees_sec", "21344.json.gz"), "rt", encoding="utf-8") as fh:
    js_ko = json.load(fh)
cfg_sec = sc.Config(dossier=os.path.join(SORTIE, "sec"), email="test@domaine-test.org")
dossier_sec = os.path.dirname(cfg_sec.chemin("cache", "sec", "x"))
ancien = os.path.join(dossier_sec, "faits_0000021344.pkl")             # copie d'une version précédente
pd.DataFrame(columns=sc.COLONNES_FAITS).to_pickle(ancien)
client = sc.ClientSEC(cfg_sec)
lus = []
client._json = lambda url: lus.append(url) or js_ko
f1 = client.faits(21344)
f2 = client.faits(21344)
verifier("règles d'extraction changées : comptes relus une seule fois, ancienne copie supprimée",
         sum("companyfacts" in u for u in lus) == 1 and len(f1) > 1000 and len(f2) == len(f1) and not os.path.exists(ancien)
         and [f for f in os.listdir(dossier_sec) if f.startswith("faits_")]
         == [f"faits_0000021344_{sc.EMPREINTE_EXTRACTION}.pkl"], str(os.listdir(dossier_sec)))
cfg_sec.cache_sec_jours = 0                                            # copie périmée et SEC en panne
client._json = lambda url: (_ for _ in ()).throw(RuntimeError("HTTP 503"))
verifier("SEC en panne : dernière copie utilisée", len(client.faits(21344)) == len(f1))

print("\n7. Rapport publié sur EDGAR mais absent de l'API XBRL : lu dans son instance XBRL")
ACCN = "0000936340-26-000146"          # 10-Q de DTE Energy (juin 2026), absent de l'API en octobre 2026
INSTANCE = """<?xml version="1.0" encoding="utf-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:us-gaap="http://fasb.org/us-gaap/2026"
  xmlns:dei="http://xbrl.sec.gov/dei/2026" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
  xmlns:iso4217="http://www.xbrl.org/2003/iso4217" xmlns:dte="http://dteenergy.com/20260630"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
 <xbrli:context id="h1_26"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000936340</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2026-01-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
 <xbrli:context id="h1_25"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000936340</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-06-30</xbrli:endDate></xbrli:period></xbrli:context>
 <xbrli:context id="q2_26"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000936340</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
 <xbrli:context id="q2_25"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000936340</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:startDate>2025-04-01</xbrli:startDate><xbrli:endDate>2025-06-30</xbrli:endDate></xbrli:period></xbrli:context>
 <xbrli:context id="b_26"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000936340</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:instant>2026-06-30</xbrli:instant></xbrli:period></xbrli:context>
 <xbrli:context id="b_25"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000936340</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
 <xbrli:context id="garde"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000936340</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:instant>2026-07-24</xbrli:instant></xbrli:period></xbrli:context>
 <xbrli:context id="h1_26_electric"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000936340</xbrli:identifier>
  <xbrli:segment><xbrldi:explicitMember dimension="dei:LegalEntityAxis">dte:DTEElectricMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
  <xbrli:period><xbrli:startDate>2026-01-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
 <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
 <xbrli:unit id="shares"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>
 <xbrli:unit id="usdPerShare"><xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator>
  <xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide></xbrli:unit>
 <us-gaap:RegulatedAndUnregulatedOperatingRevenue contextRef="h1_26" unitRef="usd" decimals="-6">8000000000</us-gaap:RegulatedAndUnregulatedOperatingRevenue>
 <us-gaap:RegulatedAndUnregulatedOperatingRevenue contextRef="h1_25" unitRef="usd" decimals="-6">7859000000</us-gaap:RegulatedAndUnregulatedOperatingRevenue>
 <us-gaap:RegulatedAndUnregulatedOperatingRevenue contextRef="q2_26" unitRef="usd" decimals="-6">3900000000</us-gaap:RegulatedAndUnregulatedOperatingRevenue>
 <us-gaap:RegulatedAndUnregulatedOperatingRevenue contextRef="q2_25" unitRef="usd" decimals="-6">3640000000</us-gaap:RegulatedAndUnregulatedOperatingRevenue>
 <us-gaap:RegulatedAndUnregulatedOperatingRevenue contextRef="h1_26_electric" unitRef="usd" decimals="-6">3100000000</us-gaap:RegulatedAndUnregulatedOperatingRevenue>
 <us-gaap:NetIncomeLoss contextRef="h1_26" unitRef="usd" decimals="-6">850000000</us-gaap:NetIncomeLoss>
 <us-gaap:NetIncomeLoss contextRef="h1_25" unitRef="usd" decimals="-6">790000000</us-gaap:NetIncomeLoss>
 <us-gaap:Assets contextRef="b_26" unitRef="usd" decimals="-6">53000000000</us-gaap:Assets>
 <us-gaap:Assets contextRef="b_25" unitRef="usd" decimals="-6">52000000000</us-gaap:Assets>
 <us-gaap:EarningsPerShareBasic contextRef="h1_26" unitRef="usdPerShare" decimals="2">4.10</us-gaap:EarningsPerShareBasic>
 <us-gaap:Goodwill contextRef="b_26" unitRef="usd" xsi:nil="true"/>
 <dei:EntityCommonStockSharesOutstanding contextRef="garde" unitRef="shares" decimals="INF">207600000</dei:EntityCommonStockSharesOutstanding>
</xbrli:xbrl>
""".encode()
js_inst = sc.instance_xbrl_vers_faits(INSTANCE, ACCN, "10-Q", "2026-07-28")
rev = js_inst["facts"]["us-gaap"]["RegulatedAndUnregulatedOperatingRevenue"]["units"]["USD"]
verifier("instance XBRL : faits sans ventilation seulement, comme l'API de la SEC",
         sorted(p["val"] for p in rev) == [3.64e9, 3.9e9, 7.859e9, 8.0e9] and all(p["accn"] == ACCN for p in rev)
         and "EarningsPerShareBasic" not in js_inst["facts"]["us-gaap"] and "Goodwill" not in js_inst["facts"]["us-gaap"]
         and js_inst["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"][0]["val"] == 207.6e6,
         f"{len(rev)} faits de chiffre d'affaires")

with gzip.open(os.path.join(ICI, "donnees_sec", "936340.json.gz"), "rt", encoding="utf-8") as fh:
    js_dte = json.load(fh)
DEPOTS = {"filings": {"recent": {
    "accessionNumber": [ACCN, "0000936340-26-000081", "0000936340-26-000054", "0000950103-26-000001"],
    "filingDate": ["2026-07-28", "2026-04-30", "2026-02-17", "2026-07-30"],
    "form": ["10-Q", "10-Q", "10-K", "8-K"],
    "primaryDocument": ["dte-20260630.htm", "dte-20260331.htm", "dte-20251231.htm", "d8k.htm"],
    "isXBRL": [1, 1, 1, 0]}}}


class Reponse:
    def __init__(self, contenu=None, js=None):
        self.content, self._js = contenu, js

    def json(self):
        return self._js


appels_sec = []


def faux_get(url):
    appels_sec.append(url)
    if "companyfacts" in url:
        return Reponse(js=js_dte)
    if "submissions" in url:
        return Reponse(js=DEPOTS)
    if url.endswith("/936340/000093634026000146/dte-20260630_htm.xml"):
        return Reponse(contenu=INSTANCE)
    raise RuntimeError(f"HTTP 404 pour {url}")


sc.aujourdhui = lambda: pd.Timestamp("2026-10-19")
cfg_e = sc.Config(dossier=os.path.join(SORTIE, "edgar"), email="test@domaine-test.org")
client = sc.ClientSEC(cfg_e)
client._get = faux_get
f_dte = client.faits(936340)
t_dte = sc.table_fondamentale(f_dte)
x = t_dte.iloc[-1]
fy25 = t_dte[t_dte["fin"] == "2025-12-31"].iloc[0]["revenus"]
verifier("rapport absent de l'API : lu sur EDGAR, trimestre de juin 2026 ajouté avec ses 12 mois glissants",
         ACCN in set(f_dte["accn"]) and x["fin"] == pd.Timestamp("2026-06-30")
         and abs(x["revenus"] - (fy25 + 8.0e9 - 7.859e9)) < 1e6 and x["dispo"] == pd.Timestamp("2026-07-28")
         and client.complements == {936340: [ACCN]}, f"CA {x['revenus'] / 1e9:.2f} Md$ au {x['fin'].date()}")
n_appels = len(appels_sec)
client2 = sc.ClientSEC(cfg_e)
client2._get = faux_get
f_dte2 = client2.faits(936340)
verifier("comptes complétés gardés en cache, rapport compris", len(appels_sec) == n_appels
         and len(f_dte2) == len(f_dte) and client2.complements == {936340: [ACCN]})
cfg_e.cache_sec_jours = 0
client3 = sc.ClientSEC(cfg_e)
client3._get = faux_get
client3.faits(936340)
verifier("rapport déjà lu : relu depuis le cache local, sans nouveau téléchargement",
         not any(u.endswith("_htm.xml") for u in appels_sec[n_appels:]) and client3.complements == {936340: [ACCN]})
client4 = sc.ClientSEC(sc.Config(dossier=os.path.join(SORTIE, "edgar_ko"), email="test@domaine-test.org"))
appels_ko = []


def get_ko(url):
    appels_ko.append(url)
    if "companyfacts" in url:
        return Reponse(js=js_dte)
    if "submissions" in url:
        return Reponse(js=DEPOTS)
    raise RuntimeError("HTTP 403 (EDGAR saturé)")


client4._get = get_ko
for k in range(8):
    client4.faits(936340 + k)
verifier("EDGAR inaccessible : abandon après 5 échecs, les comptes de l'API restent utilisés",
         sum(u.endswith(".xml") for u in appels_ko) == 5 and client4.complements == {})

print(f"\nRésultat : {len(OK)} tests réussis, {len(KO)} échecs")
if KO:
    print("Échecs :", KO)
    sys.exit(1)
