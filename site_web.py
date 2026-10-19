#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Application web du screener S&P 500
===================================

Ce script est lancé chaque soir de bourse par GitHub Actions (voir .github/workflows/actualisation.yml).
Il fait tourner le moteur (screener_sp500.py), vérifie la qualité des données, puis construit le site
statique publié sur GitHub Pages :

    _site/
      index.html, app.js, style.css, polices/      l'application (copiée depuis web/)
      data/classement.json                          classement du jour, signaux, portefeuille proposé
      data/backtest.json                            backtest (recalculé chaque semaine ou si les réglages changent)
      data/historique.json                          évolution des signaux au fil des actualisations
      data/etat.json                                sources, contrôles, avertissements
      data/titres/<TICKER>.json                     cours sur deux ans et historique du score
      rapports/                                     classeurs Excel et rapports HTML

Ce qui doit survivre d'une actualisation à l'autre :
  - donnees/ (cache GitHub Actions) : cours, comptes SEC, dernier backtest, dernier site publié ;
  - historique/ (enregistré dans le dépôt) : un instantané des signaux par séance.

En cas d'échec (source indisponible, contrôle de qualité raté), le site précédent est republié avec un
message d'erreur, et le script se termine en erreur pour que GitHub prévienne par e-mail.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import math
import os
import re
import shutil
import sys
import time
import traceback
from collections import Counter
from dataclasses import asdict
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
import screener_sp500 as sc  # noqa: E402

VERSION_DONNEES = 1
GROUPES = ("portefeuille", "signaux", "filtres", "backtest", "donnees")
OPTIONS_SITE = {"backtest_prix_depuis_2001": False}
NON_PUBLICS = ("email", "dossier", "pause_sec", "cache_sec_jours", "cache_prix_jours")
CODES = {"ACHETER": "A", "GARDER": "G", "SURVEILLER": "S", "VENDRE": "V", "DONNÉES INSUFFISANTES": "N"}
JOURS_BACKTEST = 7          # le backtest est recalculé au moins une fois par semaine
FRAICHEUR_MAX_JOURS = 5     # au-delà, les cours sont jugés périmés (jours fériés compris)


class ErreurQualite(RuntimeError):
    """Données jugées inutilisables : le site précédent reste en ligne."""


def maintenant() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def horodatage(t: Optional[dt.datetime] = None) -> str:
    return (t or maintenant()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def info(msg: str) -> None:
    sc.info(msg)


# ---------------------------------------------------------------------------
# Réglages
# ---------------------------------------------------------------------------

def lire_reglages(chemin: Optional[str]) -> Tuple[dict, dict]:
    """Lit reglages.json (regroupé par thème) et renvoie (réglages du moteur, options du site)."""
    brut = {}
    if chemin and os.path.exists(chemin):
        with open(chemin, encoding="utf-8") as fh:
            try:
                brut = json.load(fh)
            except json.JSONDecodeError as e:
                raise ValueError(f"reglages.json n'est pas un JSON valide (ligne {e.lineno}, colonne {e.colno}) : "
                                 f"{e.msg}. Vérifie les virgules et les guillemets.") from None
    if not isinstance(brut, dict):
        raise ValueError("reglages.json doit contenir un objet { ... }.")
    plat = {}
    for k, v in brut.items():
        if str(k).startswith("_"):
            continue
        if k in GROUPES and isinstance(v, dict):
            for k2, v2 in v.items():
                if not str(k2).startswith("_"):
                    plat[k2] = v2
        else:
            plat[k] = v
    options = dict(OPTIONS_SITE)
    for k in list(plat):
        if k in OPTIONS_SITE:
            options[k] = bool(plat.pop(k))
    return plat, options


def config_web(plat: dict, dossier: str, email: str) -> sc.Config:
    cfg = sc.Config.depuis_dict(plat, email=email or "ton.email@exemple.com", dossier=dossier)
    # Actualisation quotidienne : cours et comptes sont relus à chaque passage du soir.
    cfg.cache_prix_jours = 0.3
    cfg.cache_sec_jours = 0.5
    return cfg


def reglages_publics(cfg: sc.Config) -> dict:
    d = {k: v for k, v in asdict(cfg).items() if k not in NON_PUBLICS}
    d["secteurs_sans_filtre_fcf"] = list(d.get("secteurs_sans_filtre_fcf", ()))
    return d


def empreinte(cfg: sc.Config, options: dict) -> str:
    """Change dès qu'un réglage ou la version du moteur change : le backtest est alors recalculé."""
    d = reglages_publics(cfg)
    d["_options"] = options
    d["_moteur"] = sc.VERSION
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Conversions JSON (aucun NaN, nombres arrondis)
# ---------------------------------------------------------------------------

def nb(x, sig: int = 4):
    """Nombre fini arrondi à `sig` chiffres significatifs, sinon None."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    if x == 0:
        return 0
    v = float(f"{x:.{sig}g}")
    return int(v) if v.is_integer() and abs(v) < 1e15 else v


def jour(d) -> Optional[str]:
    if d is None or (not isinstance(d, str) and pd.isna(d)):
        return None
    return pd.Timestamp(d).strftime("%Y-%m-%d")


def texte(x) -> str:
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return ""
    return str(x)


def ecrire_json(chemin: str, obj) -> None:
    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, chemin)


def lire_json(chemin: str):
    if not os.path.exists(chemin):
        return None
    with open(chemin, encoding="utf-8") as fh:
        return json.load(fh)


def nom_fichier(ticker: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]", "_", str(ticker))


# ---------------------------------------------------------------------------
# Classement du jour
# ---------------------------------------------------------------------------

# (colonne du moteur, nom dans le JSON, chiffres significatifs ou type)
CHAMPS = [
    ("nom", "nom", "txt"), ("secteur", "secteur", "txt"), ("secteur_fr", "secteur_fr", "txt"),
    ("sous_secteur", "sous_secteur", "txt"), ("cik", "cik", 10), ("signal", "signal", "txt"),
    ("score", "score", 4), ("potentiel_pct", "potentiel", 4), ("robustesse_pct", "robustesse", 4),
    ("p_momentum", "p_momentum", 3), ("p_resultats", "p_resultats", 3), ("p_valeur", "p_valeur", 3),
    ("p_qualite", "p_qualite", 3), ("p_faible_risque", "p_faible_risque", 3),
    ("motif", "motif", "txt"), ("alertes", "alertes", "txt"), ("echec_filtre", "echec", "bool"),
    ("prix_split", "cours", 6), ("capitalisation", "capitalisation", 4),
    ("mom", "mom", 4), ("vol", "vol", 4), ("beta", "beta", 3), ("mdd", "mdd", 4),
    ("revision", "revision", 4), ("surprise", "surprise", 4),
    ("rend_fcf", "rend_fcf", 4), ("ebit_ve", "ebit_ve", 4), ("rend_benef", "rend_benef", 4), ("bm", "bm", 4),
    ("rentab_brute", "rentab_brute", 4), ("roa_moy", "roa_moy", 4), ("cfo_actif", "cfo_actif", 4),
    ("stabilite", "stabilite", 4), ("levier_fin", "levier_fin", 4),
    ("fscore_9", "fscore_9", 3), ("fscore_n", "fscore_n", 2), ("couverture", "couverture", 4),
    ("dette_ebitda", "dette_ebitda", 4), ("accruals", "accruals", 4), ("beneish", "beneish", 4),
    ("fcf_3a", "fcf_3a", 4), ("fcf", "fcf", 4), ("revenus", "revenus", 4), ("resultat_net", "resultat_net", 4),
    ("ebit", "ebit", 4), ("dette", "dette", 4), ("tresorerie", "tresorerie", 4),
    ("fin", "fin", "date"), ("dispo", "dispo", "date"),
    ("f_volatilite", "f_volatilite", "txt"), ("f_fscore", "f_fscore", "txt"), ("f_couverture", "f_couverture", "txt"),
    ("f_ebitda", "f_ebitda", "txt"), ("f_levier", "f_levier", "txt"), ("f_fcf", "f_fcf", "txt"),
    ("f_accruals", "f_accruals", "txt"), ("f_beneish", "f_beneish", "txt"),
    ("s_volatilite", "s_volatilite", 4), ("s_couverture", "s_couverture", 3), ("s_levier", "s_levier", 4),
    ("s_accruals", "s_accruals", 4),
]


def _valeur(v, kind):
    if kind == "txt":
        return texte(v)
    if kind == "bool":
        return None if v is None or (not isinstance(v, (bool, np.bool_)) and pd.isna(v)) else bool(v)
    if kind == "date":
        return jour(v)
    return nb(v, kind)


def exporter_classement(res: dict, cfg: sc.Config, options: dict) -> dict:
    df = res["classement"]
    noms = ["t"] + [n for _, n, _ in CHAMPS]
    lignes = []
    for t, r in df.iterrows():
        ligne = [str(t)]
        for col, _, kind in CHAMPS:
            ligne.append(_valeur(r[col], kind) if col in df.columns else None)
        lignes.append(ligne)
    port = res["portefeuille"]
    comptes = {k: int(v) for k, v in res["comptes"].items()}
    return {
        "version": VERSION_DONNEES,
        "date": jour(res["date"]),
        "genere_le": horodatage(),
        "mode": cfg.mode,
        "source_univers": res.get("source_univers", ""),
        "comptes": comptes,
        "reglages": reglages_publics(cfg),
        "options": options,
        "portefeuille": [str(t) for t in port.index],
        "colonnes": noms,
        "lignes": lignes,
    }


# ---------------------------------------------------------------------------
# Contrôles de qualité
# ---------------------------------------------------------------------------

def controler(res: dict, cfg: sc.Config, aujourd_hui: Optional[dt.date] = None) -> List[str]:
    """Lève ErreurQualite si les données sont inutilisables ; renvoie les avertissements sinon."""
    avert = []
    auj = aujourd_hui or maintenant().date()
    d = pd.Timestamp(res["date"]).date()
    retard = (auj - d).days
    if retard > FRAICHEUR_MAX_JOURS:
        raise ErreurQualite(f"Les cours ne sont pas à jour : dernière séance disponible le {d:%d/%m/%Y} "
                            f"({retard} jours). Yahoo Finance renvoie peut-être des données figées.")
    df = res["classement"]
    n = len(df)
    cours = sc.ETAT_SOURCES.get("cours", {})
    if cours.get("demandes"):
        part = cours.get("obtenus", 0) / cours["demandes"]
        if part < 0.90:
            raise ErreurQualite(f"Cours manquants pour {cours['demandes'] - cours.get('obtenus', 0)} titres "
                                f"sur {cours['demandes']} : Yahoo Finance limite sans doute les requêtes.")
        if cours.get("par_alpaca"):
            n_a = len(cours["par_alpaca"])
            avert.append((f"{n_a} titres absents de Yahoo ont été complétés" if n_a > 1 else
                          "1 titre absent de Yahoo a été complété") + " par Alpaca "
                         f"({', '.join(cours['par_alpaca'][:6])}{'…' if n_a > 6 else ''}).")
    if cfg.mode == "complet":
        sec = sc.ETAT_SOURCES.get("sec", {})
        if sec.get("societes"):
            part = sec.get("exploitables", 0) / sec["societes"]
            if part < 0.80:
                raise ErreurQualite(f"Comptes SEC exploitables pour seulement {sec.get('exploitables', 0)} sociétés "
                                    f"sur {sec['societes']}. Vérifie le secret SEC_EMAIL, ou la SEC est indisponible.")
    insuff = int((df["signal"] == "DONNÉES INSUFFISANTES").sum())
    if n == 0 or insuff > 0.40 * n:
        raise ErreurQualite(f"{insuff} titres sur {n} sans données suffisantes : classement jugé peu fiable.")
    if insuff > 0.10 * n:
        avert.append(f"{insuff} titres sur {n} n'ont pas assez de données pour être notés.")
    rev = sc.ETAT_SOURCES.get("revisions")
    if cfg.revisions_analystes and rev and rev.get("demandes"):
        if rev.get("obtenues", 0) < 0.5 * rev["demandes"]:
            avert.append(f"Révisions d'analystes obtenues pour {rev.get('obtenues', 0)} titres sur {rev['demandes']} "
                         "(Yahoo a limité les requêtes) : le classement s'appuie davantage sur les autres facteurs.")
    return avert


# ---------------------------------------------------------------------------
# Historique : un instantané des signaux par séance (enregistré dans le dépôt)
# ---------------------------------------------------------------------------

def enregistrer_instantane(res: dict, dossier: str) -> str:
    d = pd.Timestamp(res["date"])
    chemin = os.path.join(dossier, f"{d:%Y}", f"{d:%Y-%m-%d}.csv")
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    x = res["classement"][["signal", "score", "potentiel_pct", "robustesse_pct"]].copy()
    x.columns = ["signal", "score", "potentiel", "robustesse"]
    x.index.name = "ticker"
    x.round(2).to_csv(chemin, encoding="utf-8")
    return chemin


def lire_instantanes(dossier: str) -> Dict[str, pd.DataFrame]:
    out = {}
    for chemin in sorted(glob.glob(os.path.join(dossier, "*", "*.csv"))):
        nom = os.path.basename(chemin)[:-4]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", nom):
            continue
        try:
            out[nom] = pd.read_csv(chemin, index_col="ticker", encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            info(f"Instantané illisible ignoré : {chemin} ({type(e).__name__})")
    return dict(sorted(out.items()))


def exporter_historique(inst: Dict[str, pd.DataFrame], noms: Dict[str, str], n_jours: int = 130,
                        n_changements: int = 60) -> dict:
    dates = list(inst)
    jours = []
    for d in dates[-n_jours:]:
        x = inst[d]
        c = x["signal"].value_counts()
        jours.append({"date": d, "titres": int(len(x)), "comptes": {k: int(c.get(k, 0)) for k in CODES}})
    changements = []
    for a, b in list(zip(dates[:-1], dates[1:]))[-n_changements:]:
        xa, xb = inst[a], inst[b]
        lot = []
        for t in xb.index.union(xa.index):
            sa = xa["signal"].get(t) if t in xa.index else None
            sb = xb["signal"].get(t) if t in xb.index else None
            if sa == sb:
                continue
            lot.append({"t": str(t), "nom": noms.get(str(t), ""), "avant": sa, "apres": sb,
                        "score_avant": nb(xa["score"].get(t), 3) if sa else None,
                        "score_apres": nb(xb["score"].get(t), 3) if sb else None})
        changements.append({"date": b, "precedent": a, "liste": lot})
    return {"version": VERSION_DONNEES, "dates": dates, "jours": jours, "changements": changements}


# ---------------------------------------------------------------------------
# Fiches par titre : cours sur deux ans et historique du score
# ---------------------------------------------------------------------------

def exporter_titres(res: dict, inst: Dict[str, pd.DataFrame], hist_bt: Optional[pd.DataFrame], dossier: str) -> int:
    os.makedirs(dossier, exist_ok=True)
    cours = res.get("cours")
    dates = [jour(d) for d in cours.index] if cours is not None else []
    mensuel = {}
    if hist_bt is not None and not hist_bt.empty:
        h = hist_bt.dropna(subset=["score"]).sort_values("date")
        for t, g in h.groupby("ticker"):
            mensuel[str(t)] = [[jour(d), nb(s, 3), CODES.get(str(sg), "N")]
                               for d, s, sg in zip(g["date"], g["score"], g["signal"])]
    quotidien: Dict[str, list] = {}
    for d, x in inst.items():
        for t, s, sg in zip(x.index, x["score"], x["signal"]):
            quotidien.setdefault(str(t), []).append([d, nb(s, 3), CODES.get(str(sg), "N")])
    n = 0
    for t in res["classement"].index:
        t = str(t)
        serie = cours[t] if cours is not None and t in cours.columns else None
        obj = {"t": t, "dates": dates,
               "cours": [nb(v, 6) for v in serie.values] if serie is not None else [],
               "mensuel": mensuel.get(t, []), "quotidien": quotidien.get(t, [])}
        ecrire_json(os.path.join(dossier, nom_fichier(t) + ".json"), obj)
        n += 1
    return n


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------

def _tableau(df: Optional[pd.DataFrame], index_nom: str, sig: int = 4) -> Optional[dict]:
    if df is None or len(df) == 0:
        return None
    return {"index_nom": index_nom, "index": [texte(i) for i in df.index], "colonnes": [str(c) for c in df.columns],
            "valeurs": [[nb(v, sig) if not isinstance(v, str) else v for v in ligne] for ligne in df.values]}


def exporter_backtest(bt: dict, cfg: sc.Config, options: dict, cle: str) -> dict:
    navs = bt["navs"]
    metriques = {nom: _tableau(tab, "Indicateur") for nom, tab in bt["metriques"].items()}
    an = bt["annuel"]
    fin = pd.Timestamp(bt["fin"])
    debut = pd.Timestamp(bt["debut"])
    partielles = [int(a) for a in an.index if (int(a) == fin.year and fin.month < 12)
                  or (int(a) == debut.year and debut.month > 1)]
    a = bt["analyse"]
    ic = a.get("ic")
    journal = []
    for r in bt["journal"].itertuples(index=False):
        decoupe = lambda s: [x.strip() for x in str(s).split(",") if x.strip()]  # noqa: E731
        journal.append({"date": jour(r.date), "rebalancement": bool(r.rebalancement), "positions": int(r.positions),
                        "titres": int(r.titres), "acheter": int(r.acheter), "insuffisantes": int(r.insuffisantes),
                        "achats": decoupe(r.achats), "ventes": decoupe(r.ventes), "rotation": nb(r.rotation, 3),
                        "frais": nb(r.frais, 3), "liquidites": nb(r.liquidites, 3),
                        "portefeuille": decoupe(r.portefeuille)})
    cv = bt["couverture"]
    return {
        "version": VERSION_DONNEES,
        "genere_le": horodatage(),
        "empreinte": cle,
        "mode": cfg.mode,
        "debut": jour(debut), "fin": jour(fin),
        "reglages": reglages_publics(cfg),
        "options": options,
        "series": {"dates": [jour(d) for d in navs.index], "noms": [str(c) for c in navs.columns],
                   "valeurs": [[nb(v, 5) for v in navs[c].values] for c in navs.columns]},
        "metriques": metriques,
        "annuel": {"annees": [int(x) for x in an.index], "noms": [str(c) for c in an.columns],
                   "valeurs": [[nb(v, 4) for v in an[c].values] for c in an.columns], "partielles": partielles},
        "synthese": {k: nb(v, 4) for k, v in bt["synthese"].items()},
        "couverture": {"dates": [jour(d) for d in cv.index], "valeurs": [nb(v, 4) for v in cv.values]},
        "facteurs": None if ic is None or ic.empty else [
            {k: (texte(v) if k == "Facteur" else nb(v, 3)) for k, v in rec.items()} for rec in ic.to_dict("records")],
        "quintiles": _tableau(a.get("quintiles"), "Quintile"),
        "signaux": _tableau(a.get("signaux"), "Signal"),
        "journal": journal,
    }


def backtest_a_refaire(mode: str, chemin_json: str, cle: str) -> Tuple[bool, str]:
    if mode == "oui":
        return True, "demandé"
    if mode == "non":
        return False, "désactivé"
    ancien = lire_json(chemin_json)
    if not ancien:
        return True, "aucun backtest enregistré"
    if ancien.get("empreinte") != cle:
        return True, "les réglages ou le moteur ont changé"
    try:
        age = (maintenant() - dt.datetime.fromisoformat(ancien["genere_le"].replace("Z", "+00:00"))).days
    except (KeyError, ValueError):
        return True, "date du dernier backtest illisible"
    if age >= JOURS_BACKTEST:
        return True, f"dernier backtest vieux de {age} jours"
    return False, f"backtest du {ancien['genere_le'][:10]} conservé"


# ---------------------------------------------------------------------------
# Assemblage du site
# ---------------------------------------------------------------------------

def copier_application(web: str, sortie: str) -> None:
    if os.path.exists(sortie):
        shutil.rmtree(sortie)
    shutil.copytree(web, sortie, ignore=shutil.ignore_patterns(".*", "*.md"))


def lien_github() -> dict:
    depot = os.environ.get("GITHUB_REPOSITORY", "")
    serveur = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run = os.environ.get("GITHUB_RUN_ID", "")
    branche = os.environ.get("GITHUB_REF_NAME", "main") or "main"
    if not depot:
        return {}
    return {"depot": depot, "branche": branche,
            "reglages": f"{serveur}/{depot}/edit/{branche}/reglages.json",
            "actions": f"{serveur}/{depot}/actions/workflows/actualisation.yml",
            "execution": f"{serveur}/{depot}/actions/runs/{run}" if run else ""}


def ecrire_sorties_github(**valeurs) -> None:
    chemin = os.environ.get("GITHUB_OUTPUT")
    if chemin:
        with open(chemin, "a", encoding="utf-8") as fh:
            for k, v in valeurs.items():
                fh.write(f"{k}={str(v).lower() if isinstance(v, bool) else v}\n")


def resume_github(lignes: List[str]) -> None:
    chemin = os.environ.get("GITHUB_STEP_SUMMARY")
    if chemin:
        with open(chemin, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lignes) + "\n")


def annotation_github(niveau: str, titre: str, message: str) -> None:
    """Message affiché en tête de l'exécution dans l'onglet Actions (error, warning ou notice)."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        echap = lambda x: str(x).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")  # noqa: E731
        print(f"::{niveau} title={echap(titre).replace(':', ' ').replace(',', ' ')}::{echap(message)[:3000]}", flush=True)


def publier_secours(args, message: str, detail: str) -> bool:
    """Republie le dernier site réussi avec un message d'erreur. Renvoie True si un site a été produit."""
    precedent = os.path.join(args.donnees, "web", "dernier_site")
    if not os.path.exists(os.path.join(precedent, "index.html")):
        return False
    if os.path.exists(args.sortie):
        shutil.rmtree(args.sortie)
    shutil.copytree(precedent, args.sortie)
    # L'application elle-même est toujours prise dans sa dernière version
    for nom in os.listdir(args.web):
        src = os.path.join(args.web, nom)
        if nom.startswith(".") or nom.endswith(".md"):
            continue
        dst = os.path.join(args.sortie, nom)
        if os.path.isdir(src):
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    chemin = os.path.join(args.sortie, "data", "etat.json")
    etat = lire_json(chemin) or {}
    etat.update({"statut": "erreur", "erreur": {"le": horodatage(), "message": message, "detail": detail[-1500:]},
                 "liens": lien_github() or etat.get("liens", {})})
    ecrire_json(chemin, etat)
    return True


# ---------------------------------------------------------------------------
# Programme principal
# ---------------------------------------------------------------------------

def diagnostic_sec(cfg: sc.Config, classement: pd.DataFrame, dossier: str, maximum: int = 50) -> None:
    """Copie brute des comptes SEC des sociétés dont une donnée clé manque, pour en trouver la cause :
    actions sans signal, dette ou couverture des intérêts inconnues, surprise de résultats incalculable."""
    import gzip
    c = classement
    sans = c["signal"] == "DONNÉES INSUFFISANTES"
    nonfin = (c["secteur"] != "Financials") & ~sans
    capi = pd.to_numeric(c["capitalisation"], errors="coerce").fillna(0)
    groupes = [
        ("sans signal", sans),
        ("dette inconnue", nonfin & c["dette"].isna()),
        ("couverture inconnue", nonfin & c["couverture"].isna() & (pd.to_numeric(c["dette"], errors="coerce") > 0)),
        ("surprise inconnue", ~sans & c["surprise"].isna()),
    ]
    choix: Dict[str, dict] = {}
    for raison, masque in groupes:
        for t in capi[masque.fillna(False)].sort_values(ascending=False).index[:20]:
            cik = c.at[t, "cik"]
            if pd.notna(cik) and len(choix) < maximum:
                choix.setdefault(str(t), {"cik": int(cik), "nom": str(c.at[t, "nom"]), "raisons": []})
                choix[str(t)]["raisons"].append(raison)
    if not choix:
        return
    os.makedirs(dossier, exist_ok=True)
    client = sc.ClientSEC(cfg)
    for t, d in choix.items():
        cik = d["cik"]
        for nom, url in ((f"{nom_fichier(t)}_{cik}", f"{client.BASE}/api/xbrl/companyfacts/CIK{cik:010d}.json"),
                         (f"{nom_fichier(t)}_{cik}_depots", f"{client.BASE}/submissions/CIK{cik:010d}.json")):
            try:
                js = client._json(url)
                with gzip.open(os.path.join(dossier, nom + ".json.gz"), "wt", encoding="utf-8") as fh:
                    json.dump(js, fh)
            except Exception as e:  # noqa: BLE001
                info(f"Diagnostic : {nom} indisponible ({type(e).__name__}).")
    ecrire_json(os.path.join(dossier, "liste.json"), choix)
    n = Counter(r for d in choix.values() for r in d["raisons"])
    info(f"Diagnostic : comptes SEC bruts de {len(choix)} sociétés copiés dans {dossier}/ "
         f"({', '.join(f'{k} : {v}' for k, v in n.items())}).")


def nettoyer_cache(dossier: str, jours: int = 10) -> None:
    """Les révisions d'analystes sont mises en cache jour par jour : on ne garde que les plus récentes."""
    for f in glob.glob(os.path.join(dossier, "cache", "revisions_*.pkl")):
        if time.time() - os.path.getmtime(f) > jours * 86400:
            os.remove(f)


def executer(args) -> dict:
    t0 = time.time()
    nettoyer_cache(args.donnees)
    plat, options = lire_reglages(args.reglages)
    email = "apercu@demo.invalid" if getattr(args, "demo", False) else os.environ.get("SEC_EMAIL", "").strip()
    cfg = config_web(plat, args.donnees, email)
    if cfg.mode == "complet" and not cfg.email_valide():
        raise ErreurQualite("Le secret SEC_EMAIL est absent ou invalide. Ajoute-le dans le dépôt GitHub : Settings → "
                            "Secrets and variables → Actions → New repository secret (nom : SEC_EMAIL).")
    cle = empreinte(cfg, options)
    web_donnees = os.path.join(args.donnees, "web")
    os.makedirs(web_donnees, exist_ok=True)
    sc.ETAT_SOURCES.clear()

    info("=== Classement du jour ===")
    res = sc.lancer_screener(cfg)
    avertissements = controler(res, cfg, pd.Timestamp(res["date"]).date() if getattr(args, "demo", False) else None)
    for t, r in res["classement"][res["classement"]["signal"] == "DONNÉES INSUFFISANTES"].iterrows():
        info(f"  Sans signal : {t} ({texte(r.get('nom'))}) : {texte(r.get('motif'))}")
    if getattr(args, "diagnostic", False) and not getattr(args, "demo", False) and cfg.mode == "complet":
        diagnostic_sec(cfg, res["classement"], "diagnostic")
    sources = {k: dict(v) for k, v in sc.ETAT_SOURCES.items()}

    # --- Backtest (hebdomadaire, ou dès que les réglages changent) ---
    chemin_bt = os.path.join(web_donnees, "backtest.json")
    chemin_bt_scores = os.path.join(web_donnees, "backtest_scores.csv.gz")
    refaire, raison = backtest_a_refaire(args.backtest, chemin_bt, cle)
    info(f"Backtest : {'recalcul' if refaire else 'pas de recalcul'} ({raison}).")
    infos_bt = {"recalcule": False, "raison": raison}
    if refaire:
        try:
            bt = sc.lancer_backtest(cfg)
            ecrire_json(chemin_bt, exporter_backtest(bt, cfg, options, cle))
            bt["historique_scores"].to_csv(chemin_bt_scores, index=False, compression="gzip")
            rap = os.path.join(web_donnees, "rapports")
            os.makedirs(rap, exist_ok=True)
            sc.exporter_excel(os.path.join(rap, "backtest.xlsx"), None, bt, cfg)
            with open(os.path.join(rap, "backtest.html"), "w", encoding="utf-8") as fh:
                fh.write(sc.rapport_html(None, bt))
            infos_bt["recalcule"] = True
            sources["taux"] = dict(sc.ETAT_SOURCES.get("taux", {}))
            if options.get("backtest_prix_depuis_2001"):
                cfg_p = sc.Config.depuis_dict({**plat, "mode": "prix", "debut_backtest": "2001-01-01",
                                               "debut_validation": "2013-01-01", "revisions_analystes": False},
                                              email=cfg.email, dossier=cfg.dossier)
                cfg_p.cache_prix_jours, cfg_p.cache_sec_jours = cfg.cache_prix_jours, cfg.cache_sec_jours
                bt_p = sc.lancer_backtest(cfg_p)
                ecrire_json(os.path.join(web_donnees, "backtest_prix.json"), exporter_backtest(bt_p, cfg_p, options, cle))
            elif os.path.exists(os.path.join(web_donnees, "backtest_prix.json")):
                os.remove(os.path.join(web_donnees, "backtest_prix.json"))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            avertissements.append(f"Le backtest n'a pas pu être recalculé ({type(e).__name__} : {str(e)[:160]}) : "
                                  "le précédent reste affiché.")
            infos_bt["erreur"] = f"{type(e).__name__}: {str(e)[:300]}"

    # --- Historique des signaux ---
    os.makedirs(args.historique, exist_ok=True)
    chemin_inst = enregistrer_instantane(res, args.historique)
    info(f"Instantané enregistré : {chemin_inst}")
    inst = lire_instantanes(args.historique)
    noms = {str(t): texte(n) for t, n in res["classement"]["nom"].items()}

    # --- Site ---
    copier_application(args.web, args.sortie)
    data = os.path.join(args.sortie, "data")
    ecrire_json(os.path.join(data, "classement.json"), exporter_classement(res, cfg, options))
    ecrire_json(os.path.join(data, "historique.json"), exporter_historique(inst, noms))
    hist_bt = None
    if os.path.exists(chemin_bt_scores):
        try:
            hist_bt = pd.read_csv(chemin_bt_scores, parse_dates=["date"])
        except Exception as e:  # noqa: BLE001
            info(f"Historique des scores du backtest illisible ({type(e).__name__}).")
    n_titres = exporter_titres(res, inst, hist_bt, os.path.join(data, "titres"))
    for nom in ("backtest.json", "backtest_prix.json"):
        src = os.path.join(web_donnees, nom)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(data, nom))
    rap_site = os.path.join(args.sortie, "rapports")
    os.makedirs(rap_site, exist_ok=True)
    sc.exporter_excel(os.path.join(rap_site, "classement.xlsx"), res, None, cfg)
    with open(os.path.join(rap_site, "classement.html"), "w", encoding="utf-8") as fh:
        fh.write(sc.rapport_html(res, None))
    for nom in ("backtest.xlsx", "backtest.html"):
        src = os.path.join(web_donnees, "rapports", nom)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(rap_site, nom))
    rapports = sorted(os.listdir(rap_site))

    bt_json = lire_json(os.path.join(data, "backtest.json"))
    etat = {
        "version": VERSION_DONNEES,
        "statut": "avertissement" if avertissements else "ok",
        "genere_le": horodatage(),
        "date_donnees": jour(res["date"]),
        "duree_s": int(time.time() - t0),
        "moteur": sc.VERSION,
        "demo": bool(getattr(args, "demo", False)),
        "mode": cfg.mode,
        "sources": {"univers": res.get("source_univers", ""), **sources},
        "avertissements": avertissements,
        "backtest": None if not bt_json else {"genere_le": bt_json.get("genere_le"), "debut": bt_json.get("debut"),
                                              "fin": bt_json.get("fin"), **infos_bt},
        "historique": {"seances": len(inst), "premiere": next(iter(inst), None)},
        "titres": n_titres,
        "fichiers": {"backtest": os.path.exists(os.path.join(data, "backtest.json")),
                     "backtest_prix": os.path.exists(os.path.join(data, "backtest_prix.json"))},
        "rapports": rapports,
        "liens": lien_github(),
        "erreur": None,
    }
    ecrire_json(os.path.join(data, "etat.json"), etat)

    # Copie du site réussi, republiée telle quelle si une prochaine actualisation échoue
    dernier = os.path.join(web_donnees, "dernier_site")
    if os.path.exists(dernier):
        shutil.rmtree(dernier)
    shutil.copytree(args.sortie, dernier)
    c = res["comptes"]
    info(f"Site construit dans {args.sortie} en {time.time() - t0:.0f} s : {n_titres} titres, "
         + ", ".join(f"{k} {v}" for k, v in c.items()))
    resume_github([f"## Actualisation du {pd.Timestamp(res['date']):%d/%m/%Y}", "",
                   "| Signal | Titres |", "|---|---|"] + [f"| {k} | {v} |" for k, v in c.items()]
                  + ["", f"Backtest : {'recalculé' if infos_bt['recalcule'] else raison}."]
                  + ([""] + [f"- ⚠️ {a}" for a in avertissements] if avertissements else []))
    for a in avertissements:
        annotation_github("warning", "Avertissement", a)
    annotation_github("notice", f"Classement du {pd.Timestamp(res['date']):%d/%m/%Y}",
                      ", ".join(f"{k} {v}" for k, v in c.items()) + f". Backtest : {'recalculé' if infos_bt['recalcule'] else raison}.")
    return etat


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Calcule le screener et construit le site web statique.")
    ap.add_argument("--sortie", default="_site", help="dossier du site à publier")
    ap.add_argument("--donnees", default="donnees", help="cache conservé entre deux actualisations")
    ap.add_argument("--historique", default="historique", help="instantanés des signaux (enregistrés dans le dépôt)")
    ap.add_argument("--reglages", default=os.path.join(ICI, "reglages.json"))
    ap.add_argument("--web", default=os.path.join(ICI, "web"), help="fichiers de l'application")
    ap.add_argument("--backtest", choices=["auto", "oui", "non"], default="auto")
    ap.add_argument("--demo", action="store_true", help="données simulées (aperçu, sans réseau)")
    ap.add_argument("--diagnostic", action="store_true",
                    help="copier les comptes SEC bruts des actions sans signal dans diagnostic/")
    args = ap.parse_args(argv)
    simulation = None
    if args.demo:
        sys.path.insert(0, os.path.join(ICI, "tests"))
        import demo  # noqa: E402  (tests/demo.py : sources simulées)
        simulation = demo.installer(sc)
    try:
        if simulation and not glob.glob(os.path.join(args.historique, "*", "*.csv")):
            simulation["fixer_date"]("2026-10-15")     # une séance de plus, pour montrer les changements
            executer(args)
            simulation["fixer_date"]("2026-10-16")
        executer(args)
        ecrire_sorties_github(succes=True, publier=True)
        return 0
    except Exception as e:  # noqa: BLE001
        detail = traceback.format_exc()
        print(detail, file=sys.stderr)
        message = str(e) if isinstance(e, (ErreurQualite, ValueError)) else f"{type(e).__name__} : {e}"
        publie = publier_secours(args, message, detail)
        info(f"ÉCHEC : {message}" + (" — le site précédent est republié avec ce message." if publie else ""))
        resume_github(["## ❌ Actualisation impossible", "", message, "",
                       "Le site précédent reste en ligne." if publie else "Aucun site précédent à republier."])
        annotation_github("error", "Actualisation impossible", message)
        ecrire_sorties_github(succes=False, publier=publie)
        return 1


if __name__ == "__main__":
    sys.exit(main())
