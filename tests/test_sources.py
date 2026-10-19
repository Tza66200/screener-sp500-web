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

print(f"\nRésultat : {len(OK)} tests réussis, {len(KO)} échecs")
if KO:
    print("Échecs :", KO)
    sys.exit(1)
