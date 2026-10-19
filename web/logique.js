/* Screener S&P 500 : fonctions sans effet de bord (formats, portefeuille, export), testables hors navigateur. */
"use strict";
(function (racine) {
  const FR = "fr-FR";
  const FINE = " "; // espace fine insécable (avant %, $, x)
  const formats = new Map();

  function nf(min, max) {
    const cle = min + "-" + max;
    if (!formats.has(cle)) {
      formats.set(cle, new Intl.NumberFormat(FR, { minimumFractionDigits: min, maximumFractionDigits: max }));
    }
    return formats.get(cle);
  }

  const fini = (x) => typeof x === "number" && Number.isFinite(x);

  /** Évite « -0 » quand une petite valeur négative s'arrondit à zéro. */
  function sansMoinsZero(x, dec) {
    return Math.abs(x) < 0.5 * Math.pow(10, -dec) ? 0 : x;
  }

  function fNb(x, dec = 0) {
    return fini(x) ? nf(dec, dec).format(sansMoinsZero(x, dec)) : "—";
  }

  function fPct(x, dec = 1, signe = false) {
    if (!fini(x)) return "—";
    const v = sansMoinsZero(x * 100, dec);
    return (signe && v > 0 ? "+" : "") + nf(dec, dec).format(v) + FINE + "%";
  }

  function fMult(x, dec = 1) {
    return fini(x) ? nf(dec, dec).format(x) + FINE + "x" : "—";
  }

  function fArgent(x) {
    if (!fini(x)) return "—";
    const a = Math.abs(x);
    if (a >= 1e9) {
      const d = a >= 1e11 ? 0 : 1;
      return nf(d, d).format(x / 1e9) + FINE + "Md$";
    }
    if (a >= 1e6) return nf(0, 0).format(x / 1e6) + FINE + "M$";
    return nf(0, 0).format(x) + FINE + "$";
  }

  function fCours(x) {
    return fini(x) ? nf(2, 2).format(x) + FINE + "$" : "—";
  }

  const dateCourte = new Intl.DateTimeFormat(FR, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const dateLongue = new Intl.DateTimeFormat(FR, { weekday: "long", day: "numeric", month: "long", year: "numeric",
                                                   timeZone: "UTC" });
  const moisAnnee = new Intl.DateTimeFormat(FR, { month: "short", year: "numeric", timeZone: "UTC" });

  function versDate(iso) {
    if (!iso) return null;
    const d = new Date(iso.length === 10 ? iso + "T12:00:00Z" : iso);
    return isNaN(d.getTime()) ? null : d;
  }

  function fDate(iso, style = "courte") {
    const d = versDate(iso);
    if (!d) return "—";
    return (style === "longue" ? dateLongue : style === "mois" ? moisAnnee : dateCourte).format(d);
  }

  function fDateHeure(iso) {
    const d = versDate(iso);
    if (!d) return "—";
    return d.toLocaleString(FR, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  }

  function ilYa(iso, maintenant = Date.now()) {
    const d = versDate(iso);
    if (!d) return "";
    const min = Math.round((maintenant - d.getTime()) / 60000);
    if (min < 2) return "à l'instant";
    if (min < 60) return "il y a " + min + " min";
    const h = Math.round(min / 60);
    if (h < 24) return "il y a " + h + " h";
    const j = Math.round(h / 24);
    return "il y a " + j + (j > 1 ? " jours" : " jour");
  }

  // ------------------------------------------------------------------ signaux
  const SIGNAUX = {
    "ACHETER": { cls: "achat", sym: "▲", court: "Acheter", code: "A", ordre: 0 },
    "GARDER": { cls: "garder", sym: "●", court: "Garder", code: "G", ordre: 1 },
    "SURVEILLER": { cls: "surv", sym: "◆", court: "Surveiller", code: "S", ordre: 2 },
    "VENDRE": { cls: "vente", sym: "▼", court: "Vendre", code: "V", ordre: 3 },
    "DONNÉES INSUFFISANTES": { cls: "nd", sym: "?", court: "Sans données", code: "N", ordre: 4 },
    "HORS UNIVERS": { cls: "nd", sym: "–", court: "Hors S&P 500", code: "H", ordre: 5 },
  };
  const PAR_CODE = { A: "ACHETER", G: "GARDER", S: "SURVEILLER", V: "VENDRE", N: "DONNÉES INSUFFISANTES" };
  const ACTIONS = {
    "ACHETER": "Conserver (renforcer possible)",
    "GARDER": "Conserver",
    "SURVEILLER": "Conserver, sous surveillance",
    "VENDRE": "Vendre",
    "DONNÉES INSUFFISANTES": "Pas d'avis (données insuffisantes)",
    "HORS UNIVERS": "Non analysée (hors S&P 500)",
  };

  /** Signal attendu d'après la seule zone de score (avant les filtres et l'exigence de robustesse). */
  function signalDeZone(score, reglages) {
    if (!fini(score)) return "DONNÉES INSUFFISANTES";
    if (score >= reglages.seuil_achat) return "ACHETER";
    if (score >= reglages.seuil_garder) return "GARDER";
    if (score >= reglages.seuil_vente) return "SURVEILLER";
    return "VENDRE";
  }

  // ------------------------------------------------------------------ données
  function preparerClassement(c) {
    const idx = {};
    c.colonnes.forEach((k, i) => { idx[k] = i; });
    c.rows = c.lignes.map((l) => {
      const o = {};
      for (const k of c.colonnes) o[k] = l[idx[k]];
      return o;
    });
    c.par = new Map(c.rows.map((r) => [r.t, r]));
    c.proposes = new Set(c.portefeuille || []);
    return c;
  }

  function normaliserTicker(s) {
    return String(s || "").trim().toUpperCase().replace(/[./]/g, "-").replace(/[^A-Z0-9^-]/g, "");
  }

  function lireListeTickers(texte) {
    const vus = new Set();
    const out = [];
    for (const morceau of String(texte || "").split(/[\s,;]+/)) {
      const t = normaliserTicker(morceau);
      if (t && t.length <= 10 && !vus.has(t) && !/^(TICKER|SYMBOLE|SYMBOL)$/.test(t)) {
        vus.add(t);
        out.push(t);
      }
    }
    return out;
  }

  // ------------------------------------------------------------------ portefeuille (même règle que le moteur Python)
  const GARDABLES = new Set(["ACHETER", "GARDER", "SURVEILLER", "DONNÉES INSUFFISANTES"]);

  /**
   * Conserve les positions encore valables, puis complète avec les meilleurs ACHETER :
   * n lignes au plus, un plafond par secteur, une seule classe d'actions par société.
   * Port fidèle de construire_portefeuille() dans screener_sp500.py.
   */
  function construirePortefeuille(c, actuels) {
    const reg = c.reglages;
    const n = reg.n_positions;
    const plafond = Math.max(1, Math.floor(reg.max_par_secteur * n + 1e-9));
    const gardes = [];
    const ventes = [];
    const hors = [];
    for (const t of Array.from(new Set(actuels))) {
      const r = c.par.get(t);
      if (!r) hors.push(t);
      else if (GARDABLES.has(r.signal)) gardes.push(t);
      else ventes.push({ t, motif: r.motif });
    }
    const compte = new Map();
    const ciks = new Set();
    for (const t of gardes) {
      const r = c.par.get(t);
      compte.set(r.secteur, (compte.get(r.secteur) || 0) + 1);
      if (fini(r.cik)) ciks.add(r.cik);
    }
    const garde = new Set(gardes);
    const cands = c.rows
      .filter((r) => r.signal === "ACHETER" && !garde.has(r.t))
      .sort((a, b) => (fini(b.score) ? b.score : -1) - (fini(a.score) ? a.score : -1));
    const achats = [];
    for (const r of cands) {
      if (gardes.length + achats.length >= n) break;
      if ((compte.get(r.secteur) || 0) >= plafond) continue;
      if (fini(r.cik) && ciks.has(r.cik)) continue;
      achats.push(r.t);
      compte.set(r.secteur, (compte.get(r.secteur) || 0) + 1);
      if (fini(r.cik)) ciks.add(r.cik);
    }
    return { gardes, achats, ventes, hors, plafond, n };
  }

  // ------------------------------------------------------------------ export CSV (Excel en français)
  function csv(lignes, entetes) {
    const cellule = (v) => {
      if (v === null || v === undefined) return "";
      if (typeof v === "number") return Number.isFinite(v) ? String(v).replace(".", ",") : "";
      let s = String(v);
      if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;              // pas de formule dans un tableur
      return /[";\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const corps = [entetes.map(cellule).join(";")].concat(lignes.map((l) => l.map(cellule).join(";")));
    return "﻿" + corps.join("\r\n") + "\r\n";
  }

  // ------------------------------------------------------------------ échelles des graphiques
  function graduations(min, max, n = 5) {
    if (!(max > min)) return [min];
    const brut = (max - min) / n;
    const p = Math.pow(10, Math.floor(Math.log10(brut)));
    const pas = [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => (max - min) / s <= n + 0.5) || 10 * p;
    const out = [];
    for (let v = Math.ceil(min / pas - 1e-9) * pas; v <= max + pas * 1e-9; v += pas) out.push(+(Math.round(v / pas) * pas).toPrecision(12) || 0);
    return out;
  }

  function graduationsLog(min, max) {
    const out = [];
    const e0 = Math.floor(Math.log10(min));
    const e1 = Math.ceil(Math.log10(max));
    for (let e = e0; e <= e1; e++) {
      for (const m of [1, 2, 5]) {
        const v = m * Math.pow(10, e);
        if (v >= min * 0.999 && v <= max * 1.001) out.push(v);
      }
    }
    if (out.length < 3) {
      const r = graduations(min, max, 4);
      return r.filter((v) => v > 0);
    }
    return out;
  }

  /** Indice du point le plus proche (tableau trié) par dichotomie. */
  function plusProche(trie, x) {
    let a = 0;
    let b = trie.length - 1;
    if (b < 0) return -1;
    while (b - a > 1) {
      const m = (a + b) >> 1;
      if (trie[m] < x) a = m; else b = m;
    }
    return Math.abs(trie[a] - x) <= Math.abs(trie[b] - x) ? a : b;
  }

  /** Série rebasée à 1 au début d'une fenêtre de dates [debut, fin]. */
  function rebaser(dates, valeurs, debut, fin) {
    let i0 = dates.findIndex((d) => d >= debut);
    if (i0 < 0) i0 = 0;
    let i1 = dates.length - 1;
    while (i1 > i0 && dates[i1] > fin) i1--;
    let base = null;
    for (let i = i0; i <= i1; i++) {
      if (fini(valeurs[i])) { base = valeurs[i]; break; }
    }
    const out = [];
    for (let i = i0; i <= i1; i++) out.push(fini(valeurs[i]) && base ? valeurs[i] / base : null);
    return { dates: dates.slice(i0, i1 + 1), valeurs: out };
  }

  function baisses(valeurs) {
    let haut = null;
    return valeurs.map((v) => {
      if (!fini(v)) return null;
      haut = haut === null ? v : Math.max(haut, v);
      return v / haut - 1;
    });
  }

  const API = {
    FINE, fini, fNb, fPct, fMult, fArgent, fCours, fDate, fDateHeure, ilYa, versDate,
    SIGNAUX, PAR_CODE, ACTIONS, signalDeZone, preparerClassement, normaliserTicker, lireListeTickers,
    construirePortefeuille, csv, graduations, graduationsLog, plusProche, rebaser, baisses,
  };
  if (typeof module === "object" && module.exports) module.exports = API;
  else racine.Logique = API;
})(typeof window !== "undefined" ? window : globalThis);
