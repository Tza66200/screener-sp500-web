/* Screener S&P 500 — application web statique.
   Aucune dépendance, aucun traceur : les données viennent des fichiers data/*.json du site,
   et tes positions restent dans ce navigateur (localStorage). */
"use strict";
(function () {
  const L = window.Logique;
  const { fini, fNb, fPct, fMult, fArgent, fCours, fDate, SIGNAUX, PAR_CODE } = L;
  const SVG = "http://www.w3.org/2000/svg";
  const CLE = "screener-sp500-web:";

  // ================================================================== DOM
  function appliquer(n, attrs, svg) {
    if (!attrs) return;
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") { if (svg) n.setAttribute("class", v); else n.className = v; }
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
      else if (k === "style" && typeof v === "object") Object.assign(n.style, v);
      else n.setAttribute(k, v === true ? "" : String(v));
    }
  }
  function ajouter(n, enfants) {
    for (const e of enfants.flat(Infinity)) {
      if (e === null || e === undefined || e === false) continue;
      n.append(e instanceof Node ? e : document.createTextNode(String(e)));
    }
  }
  function el(tag, attrs, ...enfants) { const n = document.createElement(tag); appliquer(n, attrs); ajouter(n, enfants); return n; }
  function sv(tag, attrs, ...enfants) { const n = document.createElementNS(SVG, tag); appliquer(n, attrs, true); ajouter(n, enfants); return n; }
  function vider(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  const lien = (cible, texte, cls) => el("a", { href: "#" + cible, class: cls }, texte);
  const externe = (url, texte, cls) => el("a", { href: url, target: "_blank", rel: "noopener noreferrer", class: cls }, texte);

  // ================================================================== stockage local (jamais indispensable)
  function lire(cle, defaut) {
    try { const v = window.localStorage.getItem(CLE + cle); return v === null ? defaut : JSON.parse(v); }
    catch (e) { return defaut; }
  }
  function ecrire(cle, valeur) {
    try { window.localStorage.setItem(CLE + cle, JSON.stringify(valeur)); return true; } catch (e) { return false; }
  }

  // ================================================================== état
  const S = {
    classement: null, etat: null, historique: null, backtest: undefined, backtestPrix: undefined,
    titres: new Map(),
    positions: lire("positions", []),
    montant: lire("montant", null),
    filtres: Object.assign({ q: "", signal: "", secteur: "", jeu: "essentiel", tri: "score", sens: -1 }, lire("filtres", {})),
    periode: 0, sourceBt: "complet", echelleLog: true, journalComplet: false,
    route: { vue: "tableau" },
    observateurs: [],
  };
  if (!Array.isArray(S.positions)) S.positions = [];

  async function charger(chemin, facultatif) {
    try {
      const r = await fetch(chemin, { cache: "no-cache" });
      if (!r.ok) {
        if (facultatif) return null;
        throw new Error("le fichier " + chemin + " est introuvable (erreur " + r.status + ")");
      }
      return await r.json();
    } catch (e) {
      if (facultatif) return null;
      throw e;
    }
  }
  async function chargerBacktest() {
    if (S.backtest === undefined) {
      const f = (S.etat && S.etat.fichiers) || { backtest: true, backtest_prix: true };
      const [b, p] = await Promise.all([f.backtest ? charger("data/backtest.json", true) : null,
        f.backtest_prix ? charger("data/backtest_prix.json", true) : null]);
      S.backtest = b; S.backtestPrix = p;
    }
    return S.backtest;
  }
  async function chargerTitre(t) {
    if (S.etat && S.etat.titres_regroupes) {
      // Aperçu : toutes les fiches dans un seul fichier, dates communes
      if (!S.groupe) S.groupe = charger("data/titres.json", true);
      const g = await S.groupe;
      const f = g && g.titres[t];
      return f ? Object.assign({ t, dates: g.dates }, f) : null;
    }
    if (!S.titres.has(t)) S.titres.set(t, charger("data/titres/" + encodeURIComponent(t.replace(/[^A-Za-z0-9.-]/g, "_")) + ".json", true));
    return S.titres.get(t);
  }

  // ================================================================== navigation
  const VUES = { tableau: vueTableau, classement: vueClassement, portefeuille: vuePortefeuille, backtest: vueBacktest, methode: vueMethode };
  const TITRES = { tableau: "Tableau de bord", classement: "Classement", portefeuille: "Portefeuille", backtest: "Backtest", methode: "Méthode" };

  function routeDepuisAdresse() {
    let h = "";
    try { h = decodeURIComponent((window.location.hash || "").replace(/^#/, "")); } catch (e) { h = ""; }
    if (h.startsWith("titre-")) return { vue: "titre", t: h.slice(6) };
    return { vue: VUES[h] ? h : "tableau" };
  }
  function aller(cible) {
    S.route = cible.startsWith("titre-") ? { vue: "titre", t: cible.slice(6) } : { vue: VUES[cible] ? cible : "tableau" };
    try { if (window.location.hash !== "#" + cible) window.history.pushState(null, "", "#" + cible); } catch (e) { /* aperçu */ }
    rendre();
    window.scrollTo(0, 0);
    const main = document.getElementById("vue");
    if (main) main.focus({ preventScroll: true });
  }
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest && ev.target.closest('a[href^="#"]');
    if (!a || ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
    ev.preventDefault();
    aller(a.getAttribute("href").slice(1));
  });
  window.addEventListener("popstate", () => { S.route = routeDepuisAdresse(); rendre(); });
  window.addEventListener("hashchange", () => {
    const r = routeDepuisAdresse();
    if (r.vue !== S.route.vue || r.t !== S.route.t) { S.route = r; rendre(); }
  });

  function rendre() {
    for (const o of S.observateurs) o.disconnect();
    S.observateurs = [];
    cacherInfobulle();
    const main = document.getElementById("vue");
    vider(main);
    for (const a of document.querySelectorAll(".nav a")) {
      const actif = a.dataset.vue === S.route.vue || (S.route.vue === "titre" && a.dataset.vue === "classement");
      if (actif) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    }
    if (!S.classement) return;
    ajouter(main, bandeaux());
    const fn = S.route.vue === "titre" ? () => vueTitre(S.route.t) : VUES[S.route.vue];
    ajouter(main, fn());
    const nom = S.route.vue === "titre" ? S.route.t : TITRES[S.route.vue];
    document.title = (nom ? nom + " · " : "") + "Screener S&P 500";
  }

  // ================================================================== infobulle
  function montrerInfobulle(x, y, contenu) {
    const ib = document.getElementById("infobulle");
    if (!ib) return;
    vider(ib);
    ajouter(ib, contenu);
    ib.hidden = false;
    const r = ib.getBoundingClientRect();
    let gauche = x + 14;
    let haut = y + 16;
    if (gauche + r.width > window.innerWidth - 8) gauche = x - r.width - 14;
    if (haut + r.height > window.innerHeight - 8) haut = y - r.height - 12;
    ib.style.left = Math.max(8, gauche) + "px";
    ib.style.top = Math.max(8, haut) + "px";
  }
  function cacherInfobulle() { const ib = document.getElementById("infobulle"); if (ib) ib.hidden = true; }
  window.addEventListener("scroll", cacherInfobulle, { passive: true });

  // ================================================================== éléments communs
  function pastille(signal, grand) {
    const s = SIGNAUX[signal] || SIGNAUX["DONNÉES INSUFFISANTES"];
    return el("span", { class: "sig " + s.cls + (grand ? " grand" : "") }, el("span", { class: "sig-sym", "aria-hidden": "true" }, s.sym), s.court);
  }
  function miniEchelle(score) {
    const e = el("span", { class: "mini-echelle", "aria-hidden": "true" }, el("i", { class: "z1" }), el("i", { class: "z2" }), el("i", { class: "z3" }), el("i", { class: "z4" }));
    if (fini(score)) e.append(el("span", { class: "repere", style: { left: Math.max(1.5, Math.min(98.5, score)) + "%" } }));
    return e;
  }
  function celluleScore(score) {
    return el("span", { class: "score-cel" }, el("b", null, fini(score) ? fNb(score, 0) : "—"), miniEchelle(score));
  }
  const reglages = () => S.classement.reglages;

  /** Motif du moteur, ou raison déduite des seuils pour GARDER et SURVEILLER (le moteur n'en écrit pas). */
  function motifAffiche(r) {
    if (r.motif) return r.motif;
    const reg = reglages();
    if (!fini(r.score)) return "";
    if (r.signal === "GARDER") {
      if (r.score >= reg.seuil_achat) return "Score " + fNb(r.score, 0) + " dans la zone d'achat, mais robustesse " + fNb(r.robustesse, 0) + " sous " + reg.robustesse_min_achat;
      return "Score " + fNb(r.score, 0) + ", entre " + reg.seuil_garder + " et " + reg.seuil_achat;
    }
    if (r.signal === "SURVEILLER") return "Score " + fNb(r.score, 0) + ", entre " + reg.seuil_vente + " et " + reg.seuil_garder;
    return "";
  }

  function bandeau(type, titre, ...texte) {
    const icones = { info: "i", attention: "!", erreur: "!" };
    return el("div", { class: "bandeau " + type, role: type === "erreur" ? "alert" : null },
      el("span", { class: "icone", "aria-hidden": "true" }, icones[type]),
      el("div", null, el("p", null, el("strong", null, titre)), texte.filter(Boolean).map((t) => el("p", null, t))));
  }
  function bandeaux() {
    const e = S.etat || {};
    const out = [];
    if (e.demo) {
      out.push(bandeau("info", "Aperçu avec des données simulées.",
        "Les sociétés, tickers et chiffres sont fictifs. Ton site affichera le vrai S&P 500, actualisé chaque soir de bourse."));
    }
    if (e.statut === "erreur" && e.erreur) {
      out.push(bandeau("erreur", "La dernière actualisation a échoué (" + L.fDateHeure(e.erreur.le) + ").",
        e.erreur.message, "Les données affichées sont celles du " + fDate(e.date_donnees) + ".",
        e.liens && e.liens.execution ? externe(e.liens.execution, "Voir le journal de l'actualisation sur GitHub") : null));
    } else if (!e.demo && e.genere_le && Date.now() - Date.parse(e.genere_le) > 4 * 86400000) {
      out.push(bandeau("attention", "Les données ont plus de quatre jours.",
        "Les actualisations automatiques se sont peut-être arrêtées : ouvre l'onglet Actions de ton dépôt GitHub pour vérifier."));
    }
    return out;
  }

  function majEtatEntete() {
    const zone = document.getElementById("etat-donnees");
    if (!zone) return;
    vider(zone);
    const e = S.etat || {};
    const c = S.classement;
    let cls = "";
    if (e.statut === "erreur") cls = "erreur";
    else if (e.statut === "avertissement" || (e.genere_le && !e.demo && Date.now() - Date.parse(e.genere_le) > 4 * 86400000)) cls = "attention";
    zone.className = "etat-donnees " + cls;
    zone.append(el("span", { class: "point", "aria-hidden": "true" }),
      el("span", null, c ? "Données du " + fDate(c.date) : "Données indisponibles",
        e.genere_le ? el("span", { class: "muet" }, ", actualisées " + L.ilYa(e.genere_le)) : null));
  }

  // ================================================================== graphiques : cadre réactif
  function graphe(parent, dessiner) {
    const zone = el("div", { class: "graphe" });
    parent.append(zone);
    let largeur = 0;
    const redessiner = () => {
      const w = Math.floor(zone.clientWidth);
      if (!w || Math.abs(w - largeur) < 2) return;
      largeur = w;
      vider(zone);
      dessiner(zone, w);
    };
    if ("ResizeObserver" in window) {
      const ro = new ResizeObserver(() => redessiner());
      ro.observe(zone);
      S.observateurs.push(ro);
    } else {
      window.addEventListener("resize", redessiner);
    }
    window.requestAnimationFrame(redessiner);
    return zone;
  }

  function figure(titre, legende, construire, tableau) {
    const fig = el("figure", { class: "figure" });
    const outils = el("div", { class: "outils" });
    const tete = el("div", { class: "tete" }, titre ? el("h3", null, titre) : el("span"), outils);
    fig.append(tete);
    const corps = el("div");
    fig.append(corps);
    construire(corps);
    if (tableau) {
      let ouvert = false;
      const bouton = el("button", { class: "bouton discret", type: "button", "aria-expanded": "false" }, "Voir les valeurs");
      const zoneTab = el("div", { hidden: true });
      bouton.addEventListener("click", () => {
        ouvert = !ouvert;
        bouton.setAttribute("aria-expanded", String(ouvert));
        bouton.textContent = ouvert ? "Masquer les valeurs" : "Voir les valeurs";
        if (ouvert && !zoneTab.firstChild) zoneTab.append(tableau());
        zoneTab.hidden = !ouvert;
      });
      outils.append(bouton);
      fig.append(zoneTab);
    }
    if (legende) fig.append(el("figcaption", null, legende));
    return fig;
  }

  function tableSimple(entetes, lignes, alignGauche = 1) {
    return el("div", { class: "tableau-conteneur" }, el("table", { class: "tableau-simple" + (alignGauche >= 3 ? " tableau-texte" : "") },
      el("thead", null, el("tr", null, entetes.map((h, i) => el("th", { class: i < alignGauche ? "g" : null, scope: "col" }, h)))),
      el("tbody", null, lignes.map((l) => el("tr", null, l.map((v, i) => el("td", { class: i < alignGauche ? "g" : null }, v)))))));
  }

  function cheminLigne(xs, ys) {
    let d = "";
    let ouvert = false;
    for (let i = 0; i < xs.length; i++) {
      const y = ys[i];
      if (y === null || !Number.isFinite(y)) { ouvert = false; continue; }
      d += (ouvert ? "L" : "M") + xs[i].toFixed(1) + " " + y.toFixed(1);
      ouvert = true;
    }
    return d;
  }

  function anneesAxe(t0, t1, largeur) {
    const a0 = new Date(t0).getUTCFullYear() + 1;
    const a1 = new Date(t1).getUTCFullYear();
    const n = a1 - a0 + 1;
    if (n <= 0) return [];
    const max = Math.max(2, Math.floor(largeur / 56));
    const pas = [1, 2, 3, 4, 5, 10].find((p) => n / p <= max) || 10;
    const out = [];
    for (let a = a0; a <= a1; a++) if ((a - a0) % pas === 0) out.push(a);
    return out;
  }

  /** Courbes sur un même axe (jamais deux échelles). o.series : [{nom, court, valeurs, cls, forte, aire}] */
  function graphLignes(parent, o) {
    const ts = o.dates.map((d) => Date.parse(d + "T00:00:00Z"));
    return graphe(parent, (zone, W) => {
      const H = o.hauteur || 300;
      const etroit = W < 520;
      const m = { g: 46, d: o.etiquettesFin === false || etroit ? 10 : 112, h: 12, b: 24 };
      const pw = Math.max(40, W - m.g - m.d);
      const ph = H - m.h - m.b;
      let min = Infinity;
      let max = -Infinity;
      for (const s of o.series) for (const v of s.valeurs) if (fini(v)) { if (v < min) min = v; if (v > max) max = v; }
      if (!Number.isFinite(min)) { zone.append(el("p", { class: "muet" }, "Pas de données à afficher.")); return; }
      if (o.zero) { min = Math.min(min, 0); max = Math.max(max, 0); }
      if (o.max !== undefined) max = Math.max(max, o.max);
      if (o.min !== undefined) min = Math.min(min, o.min);
      if (!(max > min)) max = min + (Math.abs(min) || 1) * 0.1;
      let Y;
      let ticks;
      if (o.log && min > 0) {
        const a = min * 0.96;
        const b = max * 1.04;
        const la = Math.log(a);
        const lb = Math.log(b);
        Y = (v) => m.h + ph - ((Math.log(v) - la) / (lb - la)) * ph;
        ticks = L.graduationsLog(a, b);
      } else {
        const marge = (max - min) * 0.05;
        const a = o.zero && min >= 0 ? 0 : min - marge;
        const b = o.zero && max <= 0 ? 0 : max + marge;
        ticks = L.graduations(a, b, ph > 150 ? 5 : 4);
        const lo = Math.min(a, ticks[0]);
        const hi = Math.max(b, ticks[ticks.length - 1]);
        Y = (v) => m.h + ph - ((v - lo) / (hi - lo)) * ph;
      }
      const t0 = ts[0];
      const t1 = ts[ts.length - 1];
      const X = (t) => m.g + ((t - t0) / (t1 - t0 || 1)) * pw;
      const xs = ts.map(X);
      const svg = sv("svg", { width: W, height: H, viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": o.titre || "Graphique" });
      for (const v of ticks) {
        const y = Y(v);
        if (y < m.h - 0.5 || y > m.h + ph + 0.5) continue;
        svg.append(sv("line", { class: "grille", x1: m.g, x2: m.g + pw, y1: y, y2: y }));
        svg.append(sv("text", { x: m.g - 8, y: y + 4, "text-anchor": "end" }, o.fmtAxe(v)));
      }
      if (o.zones) {
        for (const z of o.zones) {
          const ya = Y(z.de);
          const yb = Y(z.a);
          svg.append(sv("rect", { class: z.cls, x: m.g, y: Math.min(ya, yb), width: pw, height: Math.abs(yb - ya) }));
        }
      }
      for (const a of anneesAxe(t0, t1, pw)) {
        const x = X(Date.UTC(a, 0, 1));
        svg.append(sv("line", { class: "axe", x1: x, x2: x, y1: m.h + ph, y2: m.h + ph + 4 }));
        svg.append(sv("text", { x, y: H - 5, "text-anchor": "middle" }, String(a)));
      }
      svg.append(sv("line", { class: "axe", x1: m.g, x2: m.g + pw, y1: m.h + ph, y2: m.h + ph }));
      if (o.ref !== undefined) {
        const y = Y(o.ref);
        svg.append(sv("line", { class: "axe", x1: m.g, x2: m.g + pw, y1: y, y2: y }));
      }
      const ordre = o.series.map((s, i) => [s, i]).sort((a, b) => (a[0].forte ? 1 : 0) - (b[0].forte ? 1 : 0));
      for (const [s] of ordre) {
        const ys = s.valeurs.map((v) => (fini(v) ? Y(v) : null));
        if (s.aire) {
          const base = Y(o.baseAire !== undefined ? o.baseAire : Math.max(min, 0));
          const dl = cheminLigne(xs, ys);
          let premier = -1;
          let dernier = -1;
          ys.forEach((y, i) => { if (y !== null) { if (premier < 0) premier = i; dernier = i; } });
          if (premier >= 0) {
            svg.append(sv("path", { class: "aire f-" + s.cls, d: dl + "L" + xs[dernier].toFixed(1) + " " + base.toFixed(1) + "L" + xs[premier].toFixed(1) + " " + base.toFixed(1) + "Z" }));
          }
        }
        svg.append(sv("path", { class: "ligne l-" + s.cls + (s.forte ? " forte" : ""), d: cheminLigne(xs, ys) }));
        if (s.points) {
          s.valeurs.forEach((v, i) => {
            if (fini(v)) svg.append(sv("circle", { cx: xs[i], cy: Y(v), r: 2.6, class: (s.points[i] || "m-nd") + " marqueur-fin" }));
          });
        }
      }
      // étiquettes de fin : valeur puis nom court, écartées si elles se chevauchent
      if (m.d > 20) {
        const etiq = [];
        o.series.forEach((s) => {
          for (let i = s.valeurs.length - 1; i >= 0; i--) {
            if (fini(s.valeurs[i])) { etiq.push({ s, y: Y(s.valeurs[i]), y0: Y(s.valeurs[i]), v: s.valeurs[i] }); break; }
          }
        });
        etiq.sort((a, b) => a.y - b.y);
        for (let k = 1; k < etiq.length; k++) if (etiq[k].y - etiq[k - 1].y < 15) etiq[k].y = etiq[k - 1].y + 15;
        const debord = etiq.length ? etiq[etiq.length - 1].y - (m.h + ph) : 0;
        if (debord > 0) etiq.forEach((e) => { e.y -= debord; });
        for (const e of etiq) {
          const x = m.g + pw + 8;
          if (Math.abs(e.y - e.y0) > 3) svg.append(sv("line", { class: "curseur", x1: m.g + pw + 2, x2: x - 2, y1: e.y0, y2: e.y }));
          svg.append(sv("circle", { cx: m.g + pw, cy: e.y0, r: 3.5, class: "marqueur f-" + e.s.cls }));
          const t = sv("text", { x, y: e.y + 4 }, sv("tspan", { class: "t-fort" }, o.fmtValeur(e.v)), sv("tspan", { class: "t-second", dx: 5 }, e.s.court || e.s.nom));
          svg.append(t);
        }
      }
      const curseur = sv("line", { class: "curseur", y1: m.h, y2: m.h + ph, visibility: "hidden" });
      const points = o.series.map((s) => sv("circle", { r: 4, class: "marqueur f-" + s.cls, visibility: "hidden" }));
      svg.append(curseur, ...points);
      const cible = sv("rect", { class: "cible", x: m.g, y: m.h, width: pw, height: ph });
      svg.append(cible);
      const bouger = (ev) => {
        const r = svg.getBoundingClientRect();
        const t = t0 + ((ev.clientX - r.left - m.g) / pw) * (t1 - t0);
        const i = L.plusProche(ts, t);
        if (i < 0) return;
        curseur.setAttribute("x1", xs[i]);
        curseur.setAttribute("x2", xs[i]);
        curseur.setAttribute("visibility", "visible");
        o.series.forEach((s, k) => {
          const v = s.valeurs[i];
          if (fini(v)) { points[k].setAttribute("cx", xs[i]); points[k].setAttribute("cy", Y(v)); points[k].setAttribute("visibility", "visible"); }
          else points[k].setAttribute("visibility", "hidden");
        });
        const lignes = o.series.map((s) => el("div", { class: "ib-ligne" }, el("i", { class: "cle cle-" + s.cls }), el("b", null, fini(s.valeurs[i]) ? o.fmtValeur(s.valeurs[i]) : "—"), el("span", null, s.nom)));
        montrerInfobulle(ev.clientX, ev.clientY, [el("div", { class: "ib-titre" }, fDate(o.dates[i])), lignes, o.noteInfobulle ? o.noteInfobulle(i) : null]);
      };
      cible.addEventListener("pointermove", bouger);
      cible.addEventListener("pointerdown", bouger);
      cible.addEventListener("pointerleave", () => {
        cacherInfobulle();
        curseur.setAttribute("visibility", "hidden");
        points.forEach((p) => p.setAttribute("visibility", "hidden"));
      });
      zone.append(svg);
    });
  }

  function legende(series, carre) {
    return el("div", { class: "legende" }, series.map((s) => el("span", null, el("i", { class: (carre ? "carre " : "") + "cle-" + s.cls }), s.nom)));
  }

  function cheminBarre(x, y0, y1, w) {
    const h = Math.abs(y1 - y0);
    const r = Math.min(4, w / 2, h);
    if (h < 0.5) return "";
    if (y1 < y0) {
      return "M" + x + " " + y0 + "V" + (y1 + r) + "Q" + x + " " + y1 + " " + (x + r) + " " + y1 + "H" + (x + w - r) + "Q" + (x + w) + " " + y1 + " " + (x + w) + " " + (y1 + r) + "V" + y0 + "Z";
    }
    return "M" + x + " " + y0 + "V" + (y1 - r) + "Q" + x + " " + y1 + " " + (x + r) + " " + y1 + "H" + (x + w - r) + "Q" + (x + w) + " " + y1 + " " + (x + w) + " " + (y1 - r) + "V" + y0 + "Z";
  }

  /** Barres verticales groupées. o.categories, o.series : [{nom, valeurs, cls}] */
  function graphBarres(parent, o) {
    return graphe(parent, (zone, W) => {
      const H = o.hauteur || 260;
      const m = { g: 48, d: 8, h: 14, b: 26 };
      const pw = W - m.g - m.d;
      const ph = H - m.h - m.b;
      let min = 0;
      let max = 0;
      for (const s of o.series) for (const v of s.valeurs) if (fini(v)) { min = Math.min(min, v); max = Math.max(max, v); }
      if (!(max > min)) max = min + 1;
      const ticks = L.graduations(min, max, 5);
      const lo = Math.min(min, ticks[0]);
      const hi = Math.max(max, ticks[ticks.length - 1]);
      const Y = (v) => m.h + ph - ((v - lo) / (hi - lo)) * ph;
      const svg = sv("svg", { width: W, height: H, viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": o.titre || "Graphique en barres" });
      for (const v of ticks) {
        const y = Y(v);
        svg.append(sv("line", { class: v === 0 ? "axe" : "grille", x1: m.g, x2: m.g + pw, y1: y, y2: y }));
        svg.append(sv("text", { x: m.g - 8, y: y + 4, "text-anchor": "end" }, o.fmtAxe(v)));
      }
      const nc = o.categories.length;
      const ns = o.series.length;
      const groupe = pw / nc;
      const largeur = Math.max(2, Math.min(24, (groupe * 0.8 - (ns - 1) * 2) / ns));
      const total = ns * largeur + (ns - 1) * 2;
      const pasEtiquette = groupe < 30 ? Math.ceil(30 / groupe) : 1;
      const y0 = Y(0);
      o.categories.forEach((cat, i) => {
        const gx = m.g + i * groupe + (groupe - total) / 2;
        const zoneCat = sv("g", { class: "barre", tabindex: 0, role: "img", "aria-label": cat + " : " + o.series.map((s) => s.nom + " " + (fini(s.valeurs[i]) ? o.fmtValeur(s.valeurs[i]) : "—")).join(", ") });
        o.series.forEach((s, k) => {
          const v = s.valeurs[i];
          if (!fini(v)) return;
          const d = cheminBarre(gx + k * (largeur + 2), y0, Y(v), largeur);
          if (d) zoneCat.append(sv("path", { class: "f-" + s.cls, d }));
        });
        zoneCat.append(sv("rect", { class: "cible", x: m.g + i * groupe, y: m.h, width: groupe, height: ph }));
        const montrer = (ev) => {
          const r = ev.currentTarget.getBoundingClientRect ? ev.currentTarget.getBoundingClientRect() : { left: 0, top: 0, width: 0 };
          const x = ev.clientX || r.left + r.width / 2;
          const y = ev.clientY || r.top;
          montrerInfobulle(x, y, [el("div", { class: "ib-titre" }, o.titreCategorie ? o.titreCategorie(cat) : cat),
            o.series.map((s) => el("div", { class: "ib-ligne" }, el("i", { class: "cle cle-" + s.cls }), el("b", null, fini(s.valeurs[i]) ? o.fmtValeur(s.valeurs[i]) : "—"), el("span", null, s.nom)))]);
        };
        zoneCat.addEventListener("pointermove", montrer);
        zoneCat.addEventListener("focus", montrer);
        zoneCat.addEventListener("pointerleave", cacherInfobulle);
        zoneCat.addEventListener("blur", cacherInfobulle);
        svg.append(zoneCat);
        if (i % pasEtiquette === 0) svg.append(sv("text", { x: m.g + i * groupe + groupe / 2, y: H - 6, "text-anchor": "middle" }, o.etiquette ? o.etiquette(cat) : cat));
      });
      zone.append(svg);
    });
  }

  /** Barres horizontales simples (une seule série, une couleur). */
  function barresH(items, fmt, max) {
    const m = max || Math.max(...items.map((i) => i.valeur), 1);
    return el("div", { class: "familles barres-h" }, items.map((it) => el("div", { class: "famille" },
      el("span", null, it.libelle),
      el("span", { class: "piste" }, el("span", { class: "rempli", style: { width: Math.max(0, Math.min(100, (it.valeur / m) * 100)) + "%" } })),
      el("b", null, fmt(it.valeur)))));
  }

  // ================================================================== échelle du jour (ouverture du tableau de bord)
  function echelleDuJour(parent) {
    const c = S.classement;
    const reg = reglages();
    const positions = new Set(S.positions);
    const notes = c.rows.filter((r) => fini(r.score));
    return graphe(parent, (zone, W) => {
      const m = { g: 6, d: 6, h: 30, b: 26 };
      const pw = W - m.g - m.d;
      const col = pw / 100;
      const rayon = Math.max(1.5, Math.min(4.3, col * 0.4));
      const pas = rayon * 2 + 1.3;
      const colonnes = Array.from({ length: 100 }, () => []);
      for (const r of notes) colonnes[Math.min(99, Math.floor(r.score))].push(r);
      const ordre = (r) => {
        const attendu = L.signalDeZone(r.score, reg);
        return (r.signal === attendu ? 0 : r.echec && r.score >= reg.seuil_vente ? 2 : 1) * 10 + SIGNAUX[r.signal].ordre;
      };
      let pile = 1;
      for (const colonne of colonnes) { colonne.sort((a, b) => ordre(a) - ordre(b)); pile = Math.max(pile, colonne.length); }
      const ph = Math.max(48, pile * pas + 6);
      const H = m.h + ph + m.b;
      const X = (s) => m.g + (s / 100) * pw;
      const base = m.h + ph - 3 - rayon;
      const svg = sv("svg", { width: W, height: H, viewBox: "0 0 " + W + " " + H, role: "img",
        "aria-label": "Répartition des " + notes.length + " actions notées selon leur score, de 0 à 100, colorées par signal" });
      const zones = [[0, reg.seuil_vente, "zone-vente", "Vendre", "moins de " + reg.seuil_vente],
        [reg.seuil_vente, reg.seuil_garder, "zone-surv", "Surveiller", reg.seuil_vente + " à " + reg.seuil_garder],
        [reg.seuil_garder, reg.seuil_achat, "zone-garder", "Garder", reg.seuil_garder + " à " + reg.seuil_achat],
        [reg.seuil_achat, 100, "zone-achat", "Acheter", reg.seuil_achat + " et plus"]];
      for (const [a, b, cls, nom, regle] of zones) {
        svg.append(sv("rect", { class: cls, x: X(a), y: m.h, width: X(b) - X(a), height: ph }));
        const larg = X(b) - X(a);
        const txt = larg > 150 ? nom + " · " + regle : larg > 62 ? nom : larg > 34 ? nom.slice(0, 4) + "." : "";
        if (txt) svg.append(sv("text", { x: X(a) + 6, y: m.h - 10, class: "t-second" }, txt));
      }
      for (const v of [0, reg.seuil_vente, reg.seuil_garder, reg.seuil_achat, 100]) {
        const x = X(v);
        svg.append(sv("line", { class: "axe", x1: x, x2: x, y1: m.h, y2: m.h + ph + 4 }));
        if (v === 100 && X(100) - X(reg.seuil_achat) < 44) continue;
        svg.append(sv("text", { x, y: H - 6, "text-anchor": v === 0 ? "start" : v === 100 ? "end" : "middle" }, String(v)));
      }
      const pts = [];
      colonnes.forEach((colonne, k) => {
        colonne.forEach((r, j) => {
          const cx = m.g + (k + 0.5) * col;
          const cy = base - j * pas;
          const veto = r.echec && r.score >= reg.seuil_vente;
          const cls = veto ? "m-veto" : "m-" + SIGNAUX[r.signal].cls;
          svg.append(sv("circle", { cx: cx.toFixed(1), cy: cy.toFixed(1), r: veto ? rayon - 0.6 : rayon, class: cls }));
          if (c.proposes.has(r.t)) svg.append(sv("circle", { cx: cx.toFixed(1), cy: cy.toFixed(1), r: rayon + 2, class: "anneau-propose" }));
          if (positions.has(r.t)) svg.append(sv("circle", { cx: cx.toFixed(1), cy: cy.toFixed(1), r: rayon + 2.8, class: "anneau-position" }));
          pts.push({ x: cx, y: cy, r });
        });
      });
      const actif = sv("circle", { r: rayon + 3, class: "anneau-propose point-actif", visibility: "hidden" });
      svg.append(actif);
      const proche = (ev) => {
        const b = svg.getBoundingClientRect();
        const x = ev.clientX - b.left;
        const y = ev.clientY - b.top;
        let mieux = null;
        let d2 = 18 * 18;
        for (const p of pts) {
          const d = (p.x - x) * (p.x - x) + (p.y - y) * (p.y - y) * 0.6;
          if (d < d2) { d2 = d; mieux = p; }
        }
        return mieux;
      };
      svg.addEventListener("pointermove", (ev) => {
        const p = proche(ev);
        if (!p) { actif.setAttribute("visibility", "hidden"); cacherInfobulle(); svg.style.cursor = ""; return; }
        svg.style.cursor = "pointer";
        actif.setAttribute("cx", p.x); actif.setAttribute("cy", p.y); actif.setAttribute("visibility", "visible");
        const r = p.r;
        montrerInfobulle(ev.clientX, ev.clientY, [
          el("div", { class: "ib-titre" }, r.t + " · " + r.nom),
          el("div", null, pastille(r.signal), " score ", el("b", null, fNb(r.score, 0))),
          motifAffiche(r) ? el("div", { class: "ib-note" }, motifAffiche(r).split("; ")[0]) : null,
          c.proposes.has(r.t) ? el("div", { class: "ib-note" }, "Dans le portefeuille proposé") : null,
          positions.has(r.t) ? el("div", { class: "ib-note" }, "Dans tes positions") : null]);
      });
      svg.addEventListener("pointerleave", () => { actif.setAttribute("visibility", "hidden"); cacherInfobulle(); });
      svg.addEventListener("click", (ev) => { const p = proche(ev); if (p) aller("titre-" + p.r.t); });
      zone.append(svg);
    });
  }

  // ================================================================== vue : tableau de bord
  function vueTableau() {
    const c = S.classement;
    const comptes = c.comptes;
    const total = c.rows.length;
    const sansNote = c.rows.filter((r) => !fini(r.score)).length;
    const ouverture = el("section", { class: "ouverture apparition", "aria-labelledby": "titre-ouverture" },
      el("div", { class: "titre-page" },
        el("h1", { id: "titre-ouverture" }, total + " actions du S&P 500 classées le " + fDate(c.date, "longue").replace(/^\w+ /, "")),
        el("p", { class: "chapo" }, "Chaque point est une action, placée selon son score de 0 à 100. Sa couleur donne le signal ; un cercle vide marque une action écartée par un filtre de sécurité, quel que soit son score.")),
      el("div", { class: "legende-signaux", role: "group", "aria-label": "Nombre d'actions par signal" },
        ["ACHETER", "GARDER", "SURVEILLER", "VENDRE", "DONNÉES INSUFFISANTES"].map((sig) => el("button", {
          type: "button", onclick: () => { S.filtres.signal = sig; S.filtres.q = ""; ecrire("filtres", S.filtres); aller("classement"); },
          "aria-label": (comptes[sig] || 0) + " actions " + SIGNAUX[sig].court + ", voir la liste" },
          pastille(sig), el("span", { class: "compte" }, fNb(comptes[sig] || 0))))));
    const fig = el("figure", { class: "figure" });
    echelleDuJour(fig);
    fig.append(el("div", { class: "legende-marques" },
      el("span", null, symbole("plein"), "action notée (couleur du signal)"),
      el("span", null, symbole("veto"), "écartée par un filtre de sécurité"),
      el("span", null, symbole("propose"), "dans le portefeuille proposé"),
      S.positions.length ? el("span", null, symbole("position"), "dans tes positions") : null,
      sansNote ? el("span", { class: "muet" }, sansNote + " action" + (sansNote > 1 ? "s" : "") + " sans score (données insuffisantes)") : null));
    fig.append(el("figcaption", null, "Le score compare chaque action aux autres de son secteur. ACHETER demande aussi une robustesse d'au moins " + reglages().robustesse_min_achat + " et tous les filtres passés ; c'est pourquoi des points verts manquent parfois tout en haut. Touche un point pour ouvrir sa fiche."));
    ouverture.append(fig);

    const gauche = el("div", { class: "colonne" }, blocPortefeuillePropose());
    const droite = el("div", { class: "colonne" }, blocChangements(), S.positions.length ? blocMesPositionsBref() : null, blocBacktestBref());
    return [ouverture, el("div", { class: "deux-colonnes" }, gauche, droite)];
  }

  function symbole(type) {
    const s = sv("svg", { width: 16, height: 16, viewBox: "0 0 16 16", "aria-hidden": "true" });
    if (type === "plein") s.append(sv("circle", { cx: 8, cy: 8, r: 4.3, class: "m-achat" }));
    if (type === "veto") s.append(sv("circle", { cx: 8, cy: 8, r: 3.7, class: "m-veto" }));
    if (type === "propose") { s.append(sv("circle", { cx: 8, cy: 8, r: 4.3, class: "m-garder" })); s.append(sv("circle", { cx: 8, cy: 8, r: 6.3, class: "anneau-propose" })); }
    if (type === "position") { s.append(sv("circle", { cx: 8, cy: 8, r: 4, class: "m-garder" })); s.append(sv("circle", { cx: 8, cy: 8, r: 6.6, class: "anneau-position" })); }
    return s;
  }

  function blocPortefeuillePropose() {
    const c = S.classement;
    const lignes = c.portefeuille.map((t) => c.par.get(t)).filter(Boolean);
    const n = reglages().n_positions;
    const poids = lignes.length ? 1 / lignes.length : 0;
    return el("section", { class: "bloc" },
      el("header", null, el("h2", null, "Portefeuille proposé"),
        el("p", null, lignes.length + " ligne" + (lignes.length > 1 ? "s" : "") + " à poids égal (" + fPct(poids, 1) + " chacune)")),
      lignes.length < n ? el("p", { class: "petit second" }, "Seules " + lignes.length + " actions remplissent aujourd'hui toutes les conditions d'achat sur " + n + " lignes visées : le reste attend en liquidités.") : null,
      el("div", { class: "panneau" },
        el("div", { class: "liste-port" }, lignes.map((r) => el("a", { href: "#titre-" + r.t },
          el("span", { class: "tk" }, r.t), el("span", { class: "nom-l" }, r.nom), el("span", { class: "sect" }, r.secteur_fr), celluleScore(r.score)))),
        el("div", { class: "actions-fiche" }, lien("portefeuille", "Adapter à mes positions", "bouton principal"), lien("classement", "Voir tout le classement", "bouton"))));
  }

  function blocChangements() {
    const h = S.historique;
    const dernier = h && h.changements && h.changements.length ? h.changements[h.changements.length - 1] : null;
    const corps = el("div", { class: "panneau" });
    if (!dernier) {
      corps.append(el("p", { class: "second petit" }, "Les changements de signal apparaîtront ici à partir de la deuxième actualisation."));
    } else {
      const groupes = [
        ["Nouveaux ACHETER", (x) => x.apres === "ACHETER"],
        ["Ne sont plus ACHETER", (x) => x.avant === "ACHETER" && x.apres],
        ["Passent à VENDRE", (x) => x.apres === "VENDRE" && x.avant !== "ACHETER"],
        ["Remontent de VENDRE", (x) => x.avant === "VENDRE" && x.apres && x.apres !== "ACHETER"],
        ["Entrées dans l'indice", (x) => !x.avant],
        ["Sorties de l'indice", (x) => !x.apres],
      ];
      const pris = new Set();
      const blocs = [];
      for (const [titre, f] of groupes) {
        const liste = dernier.liste.filter((x) => !pris.has(x.t) && f(x));
        liste.forEach((x) => pris.add(x.t));
        if (!liste.length) continue;
        blocs.push(el("div", { class: "changement" }, el("h4", null, titre + " (" + liste.length + ")"),
          el("div", { class: "puces" }, liste.slice(0, 18).map((x) => el("a", { class: "puce", href: x.apres ? "#titre-" + x.t : "#classement", title: x.nom },
            x.apres ? pastille(x.apres) : pastille("HORS UNIVERS"), el("b", null, x.t),
            x.avant ? el("span", { class: "avant" }, "avant : " + SIGNAUX[x.avant].court.toLowerCase()) : null)),
          liste.length > 18 ? el("span", { class: "muet petit" }, "et " + (liste.length - 18) + " autres") : null)));
      }
      const autres = dernier.liste.length - pris.size;
      if (!blocs.length) corps.append(el("p", { class: "second petit" }, "Aucun changement de signal par rapport à la séance précédente."));
      corps.append(el("div", { class: "changements" }, blocs));
      if (autres > 0) corps.append(el("p", { class: "muet petit" }, autres + " autre" + (autres > 1 ? "s" : "") + " changement" + (autres > 1 ? "s" : "") + " entre GARDER et SURVEILLER."));
    }
    return el("section", { class: "bloc" },
      el("header", null, el("h2", null, "Depuis la séance précédente"),
        dernier ? el("p", null, "du " + fDate(dernier.precedent) + " au " + fDate(dernier.date)) : null), corps);
  }

  function blocMesPositionsBref() {
    const c = S.classement;
    const lignes = S.positions.map((t) => c.par.get(t));
    const vendre = S.positions.filter((t, i) => lignes[i] && lignes[i].signal === "VENDRE");
    const hors = S.positions.filter((t, i) => !lignes[i]);
    const garder = S.positions.length - vendre.length - hors.length;
    return el("section", { class: "bloc" },
      el("header", null, el("h2", null, "Tes positions"), el("p", null, S.positions.length + " action" + (S.positions.length > 1 ? "s" : "") + " suivie" + (S.positions.length > 1 ? "s" : ""))),
      el("div", { class: "panneau" },
        el("div", { class: "chiffres-bref" },
          el("div", null, el("b", null, fNb(garder)), el("span", null, "à conserver")),
          el("div", null, el("b", { class: vendre.length ? "neg" : null }, fNb(vendre.length)), el("span", null, "à vendre")),
          el("div", null, el("b", null, fNb(hors.length)), el("span", null, "hors S&P 500"))),
        vendre.length ? el("div", { class: "puces" }, vendre.map((t) => el("a", { class: "puce", href: "#titre-" + t }, pastille("VENDRE"), el("b", null, t)))) : null,
        el("div", { class: "actions-fiche" }, lien("portefeuille", "Voir le détail et les achats proposés", "bouton"))));
  }

  function blocBacktestBref() {
    const sec = el("section", { class: "bloc" }, el("header", null, el("h2", null, "Le backtest en bref")));
    const panneau = el("div", { class: "panneau" }, el("p", { class: "muet petit" }, "Chargement du backtest…"));
    sec.append(panneau);
    chargerBacktest().then((b) => {
      vider(panneau);
      if (!b) { panneau.append(el("p", { class: "second petit" }, "Le backtest n'est pas encore calculé : il le sera lors d'une prochaine actualisation.")); return; }
      const nom = Object.keys(b.metriques)[0];
      const t = b.metriques[nom];
      const val = (ind, serie) => { const i = t.index.indexOf(ind); const j = t.colonnes.indexOf(serie); return i >= 0 && j >= 0 ? t.valeurs[i][j] : null; };
      panneau.append(
        el("p", { class: "second petit" }, "Stratégie rejouée du " + fDate(b.debut) + " au " + fDate(b.fin) + ", frais compris, comparée au S&P 500."),
        el("div", { class: "chiffres-bref" },
          el("div", null, el("b", null, fPct(val("Rendement annualisé", "Stratégie"))), el("span", null, "par an (S&P 500 : " + fPct(val("Rendement annualisé", "S&P 500 (SPY)")) + ")")),
          el("div", null, el("b", null, fPct(val("Perte maximale", "Stratégie"))), el("span", null, "pire baisse (S&P 500 : " + fPct(val("Perte maximale", "S&P 500 (SPY)")) + ")")),
          el("div", null, el("b", null, fPct(val("Périodes de 12 mois battant le S&P 500", "Stratégie"), 0)), el("span", null, "des périodes de 12 mois au-dessus du S&P 500"))));
      const iS = b.series.noms.indexOf("Stratégie");
      const iR = b.series.noms.indexOf("S&P 500 (SPY)");
      if (iS >= 0 && iR >= 0) {
        const fig = el("div");
        panneau.append(fig);
        graphLignes(fig, { dates: b.series.dates, log: true, hauteur: 170, titre: "Valeur de la stratégie et du S&P 500",
          series: [{ nom: "Stratégie", court: "Stratégie", valeurs: b.series.valeurs[iS], cls: "s1", forte: true },
            { nom: "S&P 500 (SPY)", court: "S&P 500", valeurs: b.series.valeurs[iR], cls: "s2" }],
          fmtAxe: (v) => fNb(v, v < 10 && v !== Math.round(v) ? 1 : 0), fmtValeur: (v) => fNb(v, 2) });
        panneau.append(legende([{ nom: "Stratégie", cls: "s1" }, { nom: "S&P 500 (SPY)", cls: "s2" }]));
      }
      panneau.append(el("div", { class: "actions-fiche" }, lien("backtest", "Voir le backtest complet", "bouton")));
    });
    return sec;
  }

  // ================================================================== vue : classement
  const FMT = {
    n0: (v) => fNb(v, 0), n1: (v) => fNb(v, 1), n2: (v) => fNb(v, 2), pct: (v) => fPct(v, 1), pct2: (v) => fPct(v, 2),
    mult: (v) => fMult(v, 1), argent: fArgent,
  };
  const COLONNES = {
    action: { titre: "Action", g: true, tri: (r) => r.t, fixe: true },
    secteur: { titre: "Secteur", g: true, tri: (r) => r.secteur_fr },
    signal: { titre: "Signal", g: true, tri: (r) => SIGNAUX[r.signal].ordre },
    score: { titre: "Score", tri: (r) => r.score },
    potentiel: { titre: "Potentiel", f: "n0" }, robustesse: { titre: "Robustesse", f: "n0" },
    mom: { titre: "Momentum 12-1", f: "pct" }, vol: { titre: "Volatilité 1 an", f: "pct" }, beta: { titre: "Bêta", f: "n2" },
    mdd: { titre: "Perte max 1 an", f: "pct" }, revision: { titre: "Révision BPA 90 j", f: "pct" },
    surprise: { titre: "Surprise résultats", f: "pct2" }, rend_fcf: { titre: "Rendement FCF", f: "pct" },
    ebit_ve: { titre: "EBIT / VE", f: "pct" }, rend_benef: { titre: "Rendement bénéfices", f: "pct" },
    bm: { titre: "Valeur comptable / cours", f: "n2" }, capitalisation: { titre: "Capitalisation", f: "argent" },
    p_valeur: { titre: "Valorisation (rang)", f: "n0" }, rentab_brute: { titre: "Rentabilité brute", f: "pct" },
    roa_moy: { titre: "ROA", f: "pct" }, cfo_actif: { titre: "Flux d'exploitation / actif", f: "pct" },
    fscore_9: { titre: "F-score /9", f: "n1" }, couverture: { titre: "Couverture intérêts", f: "mult" },
    dette_ebitda: { titre: "Dette nette / EBITDA", f: "n1" }, accruals: { titre: "Accruals", f: "pct" },
    beneish: { titre: "M-score Beneish", f: "n2" }, motif: { titre: "Motif", g: true, long: true, tri: (r) => r.motif },
  };
  const JEUX = {
    essentiel: { nom: "Essentiel", cols: ["action", "signal", "score", "secteur", "potentiel", "robustesse", "mom", "vol", "motif"] },
    valorisation: { nom: "Valorisation", cols: ["action", "signal", "score", "rend_fcf", "ebit_ve", "rend_benef", "bm", "capitalisation", "p_valeur"] },
    qualite: { nom: "Qualité et sécurité", cols: ["action", "signal", "score", "fscore_9", "couverture", "dette_ebitda", "rentab_brute", "roa_moy", "cfo_actif", "accruals", "beneish"] },
    risque: { nom: "Risque et tendance", cols: ["action", "signal", "score", "vol", "beta", "mdd", "mom", "revision", "surprise"] },
  };

  function lignesFiltrees() {
    const c = S.classement;
    const f = S.filtres;
    const q = f.q.trim().toLowerCase();
    let rows = c.rows.filter((r) => (!f.signal || r.signal === f.signal) && (!f.secteur || r.secteur_fr === f.secteur)
      && (!q || r.t.toLowerCase().includes(q) || (r.nom || "").toLowerCase().includes(q)));
    const col = COLONNES[f.tri] || COLONNES.score;
    const cle = col.tri || ((r) => r[f.tri]);
    rows = rows.slice().sort((a, b) => {
      const va = cle(a);
      const vb = cle(b);
      const na = va === null || va === undefined || va === "" || (typeof va === "number" && !Number.isFinite(va));
      const nb = vb === null || vb === undefined || vb === "" || (typeof vb === "number" && !Number.isFinite(vb));
      if (na || nb) return na === nb ? 0 : na ? 1 : -1;
      if (typeof va === "string") return va.localeCompare(vb, "fr") * f.sens;
      return (va - vb) * f.sens;
    });
    return rows;
  }

  function cellule(r, cle) {
    const col = COLONNES[cle];
    if (cle === "action") return el("td", { class: "g col-action" }, el("a", { class: "tk", href: "#titre-" + r.t }, r.t), el("span", { class: "nom" }, r.nom));
    if (cle === "secteur") return el("td", { class: "g col-secteur" }, r.secteur_fr);
    if (cle === "signal") return el("td", { class: "g" }, pastille(r.signal));
    if (cle === "score") return el("td", null, celluleScore(r.score));
    if (cle === "motif") return el("td", { class: "g texte-long" }, motifAffiche(r) || "—");
    const v = r[cle];
    let cls = null;
    if (["mom", "revision", "surprise"].includes(cle) && fini(v)) cls = v > 0 ? "pos" : v < 0 ? "neg" : null;
    return el("td", { class: cls }, FMT[col.f](v));
  }

  function vueClassement() {
    const c = S.classement;
    const f = S.filtres;
    const secteurs = Array.from(new Set(c.rows.map((r) => r.secteur_fr))).sort((a, b) => a.localeCompare(b, "fr"));
    const table = el("table");
    const thead = el("thead");
    const tbody = el("tbody");
    table.append(el("caption", { class: "visuellement-cache" }, "Classement des actions"), thead, tbody);
    const compteur = el("p", { class: "compteur", role: "status" });

    const majTableau = () => {
      ecrire("filtres", f);
      const cols = (JEUX[f.jeu] || JEUX.essentiel).cols;
      vider(thead);
      thead.append(el("tr", null, cols.map((cle) => {
        const col = COLONNES[cle];
        const actif = f.tri === cle;
        return el("th", { scope: "col", class: (col.g ? "g " : "") + (col.fixe ? "col-action" : ""), "aria-sort": actif ? (f.sens < 0 ? "descending" : "ascending") : "none" },
          el("button", { type: "button", onclick: () => {
            if (f.tri === cle) f.sens = -f.sens; else { f.tri = cle; f.sens = col.g && cle !== "signal" ? 1 : -1; }
            majTableau();
          } }, col.titre));
      })));
      const rows = lignesFiltrees();
      vider(tbody);
      const frag = document.createDocumentFragment();
      for (const r of rows) {
        const tr = el("tr", { class: "cliquable" }, cols.map((cle) => cellule(r, cle)));
        tr.addEventListener("click", (ev) => { if (!ev.target.closest("a")) aller("titre-" + r.t); });
        frag.append(tr);
      }
      tbody.append(frag);
      compteur.textContent = rows.length + " action" + (rows.length > 1 ? "s" : "") + " affichée" + (rows.length > 1 ? "s" : "") + " sur " + c.rows.length;
    };

    const boutonsSignal = el("div", { class: "segments", role: "group", "aria-label": "Filtrer par signal" });
    const majBoutons = () => {
      vider(boutonsSignal);
      [["", "Tous", c.rows.length]].concat(["ACHETER", "GARDER", "SURVEILLER", "VENDRE", "DONNÉES INSUFFISANTES"].map((s) => [s, SIGNAUX[s].court, c.comptes[s] || 0]))
        .forEach(([val, nom, n]) => boutonsSignal.append(el("button", { type: "button", "aria-pressed": String(f.signal === val), onclick: () => { f.signal = val; majBoutons(); majTableau(); } }, nom + " " + n)));
    };
    majBoutons();
    const recherche = el("input", { id: "recherche", type: "search", value: f.q, placeholder: "Ticker ou nom de société", autocomplete: "off" });
    recherche.addEventListener("input", () => { f.q = recherche.value; majTableau(); });
    const choixSecteur = el("select", { id: "secteur" }, el("option", { value: "" }, "Tous les secteurs"), secteurs.map((s) => el("option", { value: s, selected: s === f.secteur }, s)));
    choixSecteur.addEventListener("change", () => { f.secteur = choixSecteur.value; majTableau(); });
    const choixJeu = el("select", { id: "colonnes" }, Object.entries(JEUX).map(([k, j]) => el("option", { value: k, selected: k === f.jeu }, j.nom)));
    choixJeu.addEventListener("change", () => { f.jeu = choixJeu.value; majTableau(); });
    const exporter = el("button", { type: "button", class: "bouton", onclick: () => exporterClassement(lignesFiltrees()) }, "Exporter en CSV");
    majTableau();
    return [
      el("div", { class: "titre-page" }, el("h1", null, "Classement"),
        el("p", { class: "chapo" }, c.rows.length + " actions notées le " + fDate(c.date) + ". Touche une ligne pour ouvrir la fiche de l'action, ou un titre de colonne pour trier.")),
      el("section", { class: "bloc" },
        el("div", { class: "filtres" },
          el("label", { class: "champ recherche", for: "recherche" }, "Rechercher", recherche),
          el("label", { class: "champ", for: "secteur" }, "Secteur", choixSecteur),
          el("label", { class: "champ", for: "colonnes" }, "Colonnes", choixJeu),
          exporter),
        boutonsSignal, compteur, el("div", { class: "tableau-conteneur" }, table)),
    ];
  }

  // ================================================================== vue : fiche d'une action
  const NOMS_FILTRES = {
    volatilite: "Volatilité sur un an", fscore: "F-score de Piotroski", couverture: "Couverture des intérêts",
    ebitda: "EBITDA et dette nette", levier: "Dette nette / EBITDA", fcf: "Free cash-flow", accruals: "Qualité comptable (accruals)",
    beneish: "M-score de Beneish",
  };
  function lignesFiltres(r, reg) {
    const pv = (x) => fPct(x, 0);
    const lignes = [
      ["volatilite", "Hors des " + pv(reg.exclusion_volatilite) + " d'actions les plus volatiles de l'indice", fPct(r.vol, 0), fini(r.s_volatilite) ? "seuil " + fPct(r.s_volatilite, 0) : ""],
      ["fscore", "Au moins " + fNb(reg.fscore_min, 0) + " sur 9 (solidité comptable en progrès)", fini(r.fscore_9) ? fNb(r.fscore_9, 1) + " / 9" : "—", fini(r.fscore_n) ? r.fscore_n + " signaux mesurés" : ""],
      ["couverture", "Bénéfice d'exploitation d'au moins " + fMult(fini(r.s_couverture) ? r.s_couverture : reg.couverture_min) + " les intérêts", fMult(r.couverture), ""],
      ["ebitda", "Pas d'EBITDA négatif avec une dette nette", "", ""],
      ["levier", "Hors des " + pv(reg.exclusion_levier_secteur) + " les plus endettés du secteur", fNb(r.dette_ebitda, 1), fini(r.s_levier) ? "seuil " + fNb(r.s_levier, 1) : ""],
      ["fcf", "Free cash-flow positif sur trois ans", fArgent(fini(r.fcf_3a) ? r.fcf_3a : r.fcf), fini(r.fcf_3a) ? "cumul 3 ans" : fini(r.fcf) ? "12 derniers mois" : ""],
      ["accruals", "Hors des " + pv(reg.exclusion_accruals_secteur) + " pires du secteur, s'ils sont positifs (bénéfice supérieur au cash-flow d'exploitation)", fPct(r.accruals, 1), fini(r.s_accruals) ? "seuil " + fPct(r.s_accruals, 1) : ""],
      ["beneish", reg.beneish_exclut ? "M-score inférieur à −1,78 (éliminatoire)" : "M-score inférieur à −1,78 (simple alerte)", fNb(r.beneish, 2), ""],
    ];
    return el("div", { class: "filtres-liste" }, lignes.map(([cle, regle, valeur, detail]) => {
      let etat = r["f_" + cle] || "na";
      if (cle === "beneish" && etat === "echec" && !reg.beneish_exclut) etat = "alerte";
      const finance = r.secteur === "Financials" && !["volatilite", "fscore"].includes(cle);
      const symboles = { ok: "✓", echec: "✕", na: "–", alerte: "!" };
      const textes = { ok: "Passé", echec: "Échoué", na: finance ? "Ne s'applique pas aux sociétés financières" : "Non mesuré (donnée absente)", alerte: "Alerte" };
      return el("div", { class: "filtre " + etat },
        el("span", { class: "etat", "aria-hidden": "true" }, symboles[etat]),
        el("div", null, el("div", null, el("strong", null, NOMS_FILTRES[cle])), el("div", { class: "regle" }, regle + ". "), el("span", { class: "visuellement-cache" }, textes[etat]),
          etat === "na" ? el("div", { class: "muet" }, textes.na) : null),
        el("div", { class: "valeur" }, valeur, detail ? el("small", null, detail) : null));
    }));
  }

  function vueTitre(t) {
    const c = S.classement;
    const r = c.par.get(t);
    if (!r) {
      const pos = S.positions.includes(t);
      return [lien("classement", "Retour au classement", "retour"),
        el("div", { class: "titre-page" }, el("h1", null, t), el("p", { class: "chapo" }, "Cette action ne fait pas partie du S&P 500 aujourd'hui : le screener ne l'analyse pas.")),
        pos ? el("div", { class: "actions-fiche" }, boutonPosition(t)) : null];
    }
    const reg = reglages();
    const tete = el("section", { class: "fiche-tete" },
      lien("classement", "Retour au classement", "retour"),
      el("div", { class: "ligne-titre" }, el("h1", { class: "ticker" }, r.t), el("span", { class: "societe" }, r.nom)),
      el("div", { class: "secteurs" }, [r.secteur_fr, r.sous_secteur].filter(Boolean).join(", ")));
    const echelle = el("div", { class: "grande-echelle" },
      el("div", { class: "zones", "aria-hidden": "true" },
        el("span", { style: { left: reg.seuil_vente / 2 + "%" } }, "Vendre"),
        el("span", { style: { left: (reg.seuil_garder + reg.seuil_achat) / 2 + "%" } }, "Garder"),
        el("span", { style: { left: (reg.seuil_achat + 100) / 2 + "%" } }, "Acheter")),
      el("div", { class: "piste", role: "img", "aria-label": "Score " + fNb(r.score, 0) + " sur 100" },
        el("i", { class: "z1", style: { width: reg.seuil_vente + "%" } }), el("i", { class: "z2", style: { width: reg.seuil_garder - reg.seuil_vente + "%" } }),
        el("i", { class: "z3", style: { width: reg.seuil_achat - reg.seuil_garder + "%" } }), el("i", { class: "z4", style: { width: 100 - reg.seuil_achat + "%" } }),
        fini(r.score) ? el("span", { class: "curseur-score", style: { left: r.score + "%" } }) : null),
      el("div", { class: "reperes", "aria-hidden": "true" }, [0, reg.seuil_vente, reg.seuil_garder, reg.seuil_achat, 100].map((v) => el("span", { style: { left: v + "%" } }, String(v)))));
    const verdict = el("section", { class: "panneau" },
      el("div", { class: "verdict" },
        el("div", { class: "score-hero" }, pastille(r.signal, true), el("span", { class: "nombre" }, fini(r.score) ? fNb(r.score, 0) : "—"), el("span", { class: "sur" }, "score sur 100")),
        echelle),
      el("div", { class: "motif-bloc" },
        el("p", null, el("strong", null, "Pourquoi ce signal : "), motifAffiche(r) || "—"),
        r.alertes ? el("p", null, el("strong", null, "Alerte : "), r.alertes) : null,
        el("p", null, "Action conseillée si tu la détiens : ", el("strong", null, L.ACTIONS[r.signal]), ".")),
      el("div", { class: "actions-fiche" }, boutonPosition(r.t),
        fini(r.cik) ? externe("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=" + r.cik + "&type=10-&dateb=&owner=include&count=40", "Rapports déposés à la SEC", "bouton") : null,
        externe("https://finance.yahoo.com/quote/" + encodeURIComponent(r.t), "Cours sur Yahoo Finance", "bouton")));
    const familles = el("section", { class: "bloc" },
      el("header", null, el("h2", null, "Ce qui compose le score"), el("p", null, "Rang de 0 à 100 parmi les actions du même secteur (50 = médiane)")),
      el("div", { class: "panneau" },
        el("div", { class: "familles" },
          ligneFamille("Potentiel", r.potentiel, true), ligneFamille("Momentum 12-1 mois", r.p_momentum), ligneFamille("Dynamique des résultats", r.p_resultats),
          ligneFamille("Valorisation", r.p_valeur),
          ligneFamille("Robustesse", r.robustesse, true), ligneFamille("Qualité", r.p_qualite), ligneFamille("Faible risque", r.p_faible_risque)),
        el("p", { class: "petit second" }, "Score = " + fPct(reg.poids_potentiel, 0) + " potentiel + " + fPct(1 - reg.poids_potentiel, 0) + " robustesse, converti en rang sur tout l'indice.")));
    const filtres = el("section", { class: "bloc" },
      el("header", null, el("h2", null, "Filtres de sécurité"), el("p", null, r.echec ? "Au moins un filtre échoué : signal VENDRE quel que soit le score" : "Un seul échec suffit à donner VENDRE")),
      el("div", { class: "panneau" }, lignesFiltres(r, reg)));
    const graphes = el("section", { class: "bloc" }, el("header", null, el("h2", null, "Cours et historique du score")));
    const zoneGraphes = el("div", { class: "colonne" }, el("p", { class: "muet petit" }, "Chargement…"));
    graphes.append(zoneGraphes);
    chargerTitre(r.t).then((f) => {
      if (S.route.vue !== "titre" || S.route.t !== r.t) return;
      vider(zoneGraphes);
      if (!f) { zoneGraphes.append(el("p", { class: "muet petit" }, "Historique indisponible pour cette action.")); return; }
      if (f.cours && f.cours.some(fini)) {
        zoneGraphes.append(figure("Cours sur deux ans", "Cours de clôture en dollars, ajusté des divisions d'actions (dividendes non réinvestis).", (corps) => {
          graphLignes(corps, { dates: f.dates, series: [{ nom: "Cours", court: "", valeurs: f.cours, cls: "s1", aire: true }], hauteur: 240,
            titre: "Cours de " + r.t, fmtAxe: (v) => fNb(v, v < 20 ? 1 : 0), fmtValeur: fCours, etiquettesFin: false, baseAire: Math.min(...f.cours.filter(fini)) });
        }, () => tableSimple(["Date", "Cours"], f.dates.map((d, i) => [d, fCours(f.cours[i])]).filter((x, i) => i % 5 === 0 || i === f.dates.length - 1))));
      }
      const hist = (f.mensuel || []).concat((f.quotidien || []).filter((x) => !f.mensuel || !f.mensuel.length || x[0] > f.mensuel[f.mensuel.length - 1][0]));
      if (hist.length > 1) {
        zoneGraphes.append(figure("Historique du score", (f.mensuel && f.mensuel.length ? "Score de fin de mois recalculé par le backtest, puis score de chaque actualisation. " : "Score de chaque actualisation. ") + "Les bandes de fond reprennent les zones de signal ; la couleur des points donne le signal de l'époque.", (corps) => {
          graphLignes(corps, { dates: hist.map((x) => x[0]), hauteur: 220, min: 0, max: 100, titre: "Historique du score de " + r.t,
            series: [{ nom: "Score", court: "", valeurs: hist.map((x) => x[1]), cls: "s1", points: hist.map((x) => "m-" + SIGNAUX[PAR_CODE[x[2]] || "DONNÉES INSUFFISANTES"].cls) }],
            zones: [{ de: 0, a: reg.seuil_vente, cls: "zone-vente" }, { de: reg.seuil_vente, a: reg.seuil_garder, cls: "zone-surv" },
              { de: reg.seuil_garder, a: reg.seuil_achat, cls: "zone-garder" }, { de: reg.seuil_achat, a: 100, cls: "zone-achat" }],
            fmtAxe: (v) => fNb(v, 0), fmtValeur: (v) => fNb(v, 0), etiquettesFin: false,
            noteInfobulle: (i) => el("div", { class: "ib-note" }, "Signal : " + SIGNAUX[PAR_CODE[hist[i][2]] || "DONNÉES INSUFFISANTES"].court) });
        }, () => tableSimple(["Date", "Score", "Signal"], hist.map((x) => [x[0], fNb(x[1], 0), SIGNAUX[PAR_CODE[x[2]] || "DONNÉES INSUFFISANTES"].court]))));
      }
    });
    const chiffres = el("section", { class: "bloc" },
      el("header", null, el("h2", null, "Chiffres clés"), el("p", null, fini(r.score) && r.fin ? "Comptes arrêtés au " + fDate(r.fin) + ", publiés le " + fDate(r.dispo) : "")),
      el("div", { class: "panneau" }, el("dl", { class: "chiffres" }, [
        ["Cours", fCours(r.cours)], ["Capitalisation", fArgent(r.capitalisation)],
        ["Chiffre d'affaires (12 mois)", fArgent(r.revenus)], ["Résultat net (12 mois)", fArgent(r.resultat_net)],
        ["EBIT (12 mois)", fArgent(r.ebit)], ["Free cash-flow (12 mois)", fArgent(r.fcf)],
        ["Dette financière", fArgent(r.dette)], ["Trésorerie", fArgent(r.tresorerie)],
        ["Rendement du free cash-flow", fPct(r.rend_fcf)], ["EBIT / valeur d'entreprise", fPct(r.ebit_ve)],
        ["Rendement des bénéfices", fPct(r.rend_benef)], ["Momentum 12-1 mois", fPct(r.mom, 1, true)],
        ["Révision du BPA (90 j)", fPct(r.revision, 1, true)], ["Surprise de résultats", fPct(r.surprise, 2, true)],
        ["Volatilité (1 an)", fPct(r.vol)], ["Bêta (1 an)", fNb(r.beta, 2)], ["Perte maximale (1 an)", fPct(r.mdd)],
        ["Rentabilité brute / actif", fPct(r.rentab_brute)], ["ROA", fPct(r.roa_moy)],
      ].map(([k, v]) => el("div", null, el("dt", null, k), el("dd", null, v))))));
    return [tete, verdict, el("div", { class: "deux-colonnes" }, el("div", { class: "colonne" }, familles, graphes), el("div", { class: "colonne" }, filtres, chiffres))];
  }

  function ligneFamille(nom, valeur, titre) {
    return el("div", { class: "famille" + (titre ? " titre-famille" : "") },
      el("span", null, nom),
      el("span", { class: "piste", "aria-hidden": "true" }, el("span", { class: "milieu" }), fini(valeur) ? el("span", { class: "rempli", style: { width: Math.max(1, Math.min(100, valeur)) + "%" } }) : null),
      el("b", null, fini(valeur) ? fNb(valeur, 0) : "—"));
  }

  function boutonPosition(t) {
    const present = S.positions.includes(t);
    return el("button", { type: "button", class: "bouton" + (present ? "" : " principal"), onclick: () => {
      S.positions = present ? S.positions.filter((x) => x !== t) : S.positions.concat([t]);
      ecrire("positions", S.positions);
      rendre();
    } }, present ? "Retirer de mes positions" : "Ajouter à mes positions");
  }

  // ================================================================== vue : portefeuille
  function vuePortefeuille() {
    const c = S.classement;
    const message = el("p", { class: "petit second", role: "status" });
    const saisie = el("input", { id: "ajout-positions", type: "text", placeholder: "Par exemple : AAPL, MSFT, JNJ", autocomplete: "off", autocapitalize: "characters", spellcheck: "false" });
    const ajouterSaisie = () => {
      const nouveaux = L.lireListeTickers(saisie.value).filter((t) => !S.positions.includes(t));
      if (!nouveaux.length) { message.textContent = "Saisis un ou plusieurs tickers séparés par des virgules ou des espaces."; return; }
      S.positions = S.positions.concat(nouveaux);
      ecrire("positions", S.positions);
      rendre();
    };
    saisie.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); ajouterSaisie(); } });
    const fichier = el("input", { type: "file", accept: ".json,.csv,.txt,text/plain,application/json", class: "visuellement-cache", id: "import-positions" });
    fichier.addEventListener("change", () => {
      const f = fichier.files && fichier.files[0];
      if (!f) return;
      const lecteur = new FileReader();
      lecteur.onload = () => {
        let liste = [];
        try {
          const js = JSON.parse(String(lecteur.result));
          liste = (Array.isArray(js) ? js : js.positions || []).map(L.normaliserTicker).filter(Boolean);
        } catch (e) { liste = L.lireListeTickers(String(lecteur.result)); }
        if (!liste.length) { message.textContent = "Aucun ticker reconnu dans ce fichier."; return; }
        S.positions = Array.from(new Set(S.positions.concat(liste)));
        ecrire("positions", S.positions);
        rendre();
      };
      lecteur.readAsText(f);
    });
    const effacer = el("span", { class: "confirmation" });
    const majEffacer = (demande) => {
      vider(effacer);
      if (!S.positions.length) return;
      if (!demande) { effacer.append(el("button", { type: "button", class: "bouton discret", onclick: () => majEffacer(true) }, "Tout effacer")); return; }
      effacer.append("Effacer les " + S.positions.length + " positions ?",
        el("button", { type: "button", class: "bouton", onclick: () => { S.positions = []; ecrire("positions", []); rendre(); } }, "Oui, effacer"),
        el("button", { type: "button", class: "bouton discret", onclick: () => majEffacer(false) }, "Annuler"));
    };
    majEffacer(false);

    const saisieBloc = el("section", { class: "bloc" },
      el("header", null, el("h2", null, "Tes positions"), el("p", null, "Enregistrées seulement dans ce navigateur, jamais envoyées ailleurs")),
      el("div", { class: "panneau" },
        el("div", { class: "saisie-positions" },
          el("label", { class: "champ", for: "ajout-positions" }, "Ajouter des actions que tu détiens", saisie),
          el("button", { type: "button", class: "bouton principal", onclick: ajouterSaisie }, "Ajouter")),
        message,
        S.positions.length ? el("div", { class: "jetons" }, S.positions.map((t) => el("span", { class: "jeton" }, t,
          el("button", { type: "button", "aria-label": "Retirer " + t, onclick: () => { S.positions = S.positions.filter((x) => x !== t); ecrire("positions", S.positions); rendre(); } }, "×")))) : null,
        el("div", { class: "actions-fiche" },
          el("button", { type: "button", class: "bouton", disabled: !S.positions.length, onclick: () => telecharger("positions.json", JSON.stringify({ positions: S.positions, exporte_le: new Date().toISOString() }, null, 1), "application/json") }, "Exporter (sauvegarde)"),
          el("label", { class: "bouton", for: "import-positions" }, "Importer un fichier"), fichier, effacer)));

    if (!S.positions.length) {
      const exemples = [c.rows.find((r) => r.signal === "ACHETER"), c.rows.find((r) => r.signal === "GARDER"),
        c.rows.find((r) => r.signal === "SURVEILLER"), c.rows.find((r) => r.signal === "VENDRE" && r.echec)].filter(Boolean).map((r) => r.t);
      return [titrePortefeuille(),
        saisieBloc,
        el("div", { class: "vide" },
          el("strong", null, "Ajoute les actions que tu détiens pour savoir lesquelles garder, lesquelles vendre et quoi acheter à la place."),
          el("span", null, "Le calcul suit exactement la règle du backtest : on conserve ce qui reste valable, on vend ce qui casse un filtre ou tombe sous " + reglages().seuil_vente + ", puis on complète avec les meilleurs ACHETER."),
          exemples.length ? el("button", { type: "button", class: "bouton", onclick: () => { S.positions = exemples; ecrire("positions", exemples); rendre(); } }, "Essayer avec " + exemples.length + " actions d'exemple") : null),
        blocProposeDetaille()];
    }

    const p = L.construirePortefeuille(c, S.positions);
    const diag = el("section", { class: "bloc" },
      el("header", null, el("h2", null, "Diagnostic de tes positions")),
      el("div", { class: "tableau-conteneur" }, el("table", null,
        el("thead", null, el("tr", null, ["Action", "Signal", "Score", "Ce que tu en fais", "Pourquoi"].map((h, i) => el("th", { scope: "col", class: i === 2 ? null : "g" }, h)))),
        el("tbody", null, S.positions.map((t) => {
          const r = c.par.get(t);
          const sig = r ? r.signal : "HORS UNIVERS";
          return el("tr", { class: r ? "cliquable" : null, onclick: r ? (ev) => { if (!ev.target.closest("a")) aller("titre-" + t); } : null },
            el("td", { class: "g" }, r ? el("a", { class: "tk", href: "#titre-" + t }, t) : el("span", { class: "tk" }, t), el("span", { class: "nom" }, r ? r.nom : "Hors S&P 500")),
            el("td", { class: "g" }, pastille(sig)), el("td", null, r ? celluleScore(r.score) : "—"),
            el("td", { class: "g" }, el("strong", null, L.ACTIONS[sig])),
            el("td", { class: "g texte-long" }, r ? motifAffiche(r) || "—" : "Le screener n'analyse que les membres actuels du S&P 500."));
        })))));

    const nCible = p.gardes.length + p.achats.length;
    const plan = el("section", { class: "bloc" },
      el("header", null, el("h2", null, "Ton portefeuille cible"),
        el("p", null, nCible + " ligne" + (nCible > 1 ? "s" : "") + " sur " + p.n + " visées, " + p.plafond + " au plus par secteur")),
      el("div", { class: "plan" },
        colonnePlan("vente", "À vendre", p.ventes.map((v) => [v.t, v.motif]), "Rien à vendre."),
        colonnePlan("garder", "À conserver", p.gardes.map((t) => [t, SIGNAUX[c.par.get(t).signal].court + ", score " + fNb(c.par.get(t).score, 0)]), "Aucune position à conserver.")),
      el("section", { class: "bloc" }, el("h3", { class: "titre-plan" }, pastille("ACHETER"), "À acheter (" + p.achats.length + ")"),
        p.achats.length ? tableSimple(["Action", "Secteur", "Score", "Robustesse", "Volatilité 1 an"], p.achats.map((t) => {
          const r = c.par.get(t);
          return [el("span", null, el("a", { class: "tk", href: "#titre-" + t }, t), el("span", { class: "nom" }, r.nom)), r.secteur_fr, celluleScore(r.score), fNb(r.robustesse, 0), fPct(r.vol, 0)];
        }), 2) : el("p", { class: "petit second" }, nCible >= p.n ? "Le portefeuille est complet : rien à acheter." : "Aucun ACHETER disponible (plafond par secteur atteint ou aucun candidat).")),
      p.hors.length ? el("p", { class: "petit second" }, "Hors S&P 500, non analysées et non comptées : " + p.hors.join(", ") + ".") : null,
      nCible < p.n ? el("p", { class: "petit second" }, "Il manque " + (p.n - nCible) + " ligne" + (p.n - nCible > 1 ? "s" : "") + " : le screener préfère garder des liquidités plutôt qu'acheter une action qui ne remplit pas toutes les conditions.") : null,
      blocMontant(nCible));
    return [titrePortefeuille(), saisieBloc, diag, plan, blocProposeDetaille()];
  }

  function titrePortefeuille() {
    return el("div", { class: "titre-page" }, el("h1", null, "Portefeuille"),
      el("p", { class: "chapo" }, "Le screener propose " + reglages().n_positions + " lignes à poids égal, " + fPct(reglages().max_par_secteur, 0) + " au plus dans un même secteur. Indique tes positions pour adapter la proposition à ce que tu détiens déjà."));
  }

  function colonnePlan(cls, titre, items, vide) {
    return el("section", null, el("h3", null, pastille(cls === "vente" ? "VENDRE" : cls === "achat" ? "ACHETER" : "GARDER"), titre + " (" + items.length + ")"),
      items.length ? items.map(([t, raison]) => el("div", { class: "ligne-plan" }, el("a", { class: "tk", href: "#titre-" + t }, t), el("span", { class: "raison" }, raison)))
        : el("p", { class: "petit second" }, vide));
  }

  function blocMontant(nLignes) {
    const sortie = el("output", { for: "montant" });
    const champ = el("input", { id: "montant", type: "number", min: "0", step: "100", inputmode: "decimal", value: fini(S.montant) ? S.montant : "", placeholder: "Par exemple 20000" });
    const maj = () => {
      const v = parseFloat(String(champ.value).replace(",", "."));
      S.montant = Number.isFinite(v) && v > 0 ? v : null;
      ecrire("montant", S.montant);
      sortie.textContent = S.montant && nLignes ? "soit " + fNb(S.montant / nLignes, 0) + " par ligne sur " + nLignes + " lignes" : "";
    };
    champ.addEventListener("input", maj);
    maj();
    return el("div", { class: "panneau" }, el("div", { class: "montant" },
      el("label", { class: "champ", for: "montant" }, "Montant total du portefeuille (dans ta devise)", champ), sortie),
      el("p", { class: "petit second" }, "Poids égal : chaque ligne reçoit la même somme. Rééquilibre une fois par trimestre, comme dans le backtest."));
  }

  function blocProposeDetaille() {
    const c = S.classement;
    const lignes = c.portefeuille.map((t) => c.par.get(t)).filter(Boolean);
    const parSecteur = new Map();
    for (const r of lignes) parSecteur.set(r.secteur_fr, (parSecteur.get(r.secteur_fr) || 0) + 1);
    const items = Array.from(parSecteur.entries()).sort((a, b) => b[1] - a[1]).map(([libelle, valeur]) => ({ libelle, valeur }));
    return el("section", { class: "bloc" },
      el("header", null, el("h2", null, "Portefeuille proposé à partir de zéro"), el("p", null, "Sans tenir compte de tes positions")),
      el("div", { class: "table-et-cote" },
        el("div", { class: "tableau-conteneur" }, el("table", null,
          el("thead", null, el("tr", null, ["Action", "Secteur", "Score", "Potentiel", "Robustesse", "Volatilité"].map((h, i) => el("th", { scope: "col", class: i < 2 ? "g" : null }, h)))),
          el("tbody", null, lignes.map((r) => el("tr", { class: "cliquable", onclick: (ev) => { if (!ev.target.closest("a")) aller("titre-" + r.t); } },
            el("td", { class: "g" }, el("a", { class: "tk", href: "#titre-" + r.t }, r.t), el("span", { class: "nom" }, r.nom)),
            el("td", { class: "g" }, r.secteur_fr), el("td", null, celluleScore(r.score)), el("td", null, fNb(r.potentiel, 0)),
            el("td", null, fNb(r.robustesse, 0)), el("td", null, fPct(r.vol, 0))))))),
        el("div", { class: "panneau" }, el("h3", null, "Répartition par secteur"), barresH(items, (v) => v + " ligne" + (v > 1 ? "s" : ""), Math.max(1, Math.floor(reglages().max_par_secteur * reglages().n_positions))),
          el("p", { class: "petit second" }, "La barre pleine correspond au plafond de " + Math.max(1, Math.floor(reglages().max_par_secteur * reglages().n_positions)) + " lignes par secteur."))));
  }

  // ================================================================== vue : backtest
  const SERIES_BT = { "Stratégie": "s1", "S&P 500 (SPY)": "s2", "Univers équipondéré": "s3", "S&P 500 équipondéré (RSP)": "s4" };
  const COURTS_BT = { "Stratégie": "Stratégie", "S&P 500 (SPY)": "S&P 500", "Univers équipondéré": "Équipondéré", "S&P 500 équipondéré (RSP)": "RSP" };
  const FORMATS_IND = (ind) => (/Ratio|Bêta/.test(ind) ? (v) => fNb(v, 2) : (v) => fPct(v, 1));

  function vueBacktest() {
    const zone = el("div", { class: "colonne" }, el("p", { class: "muet" }, "Chargement du backtest…"));
    chargerBacktest().then(() => {
      if (S.route.vue !== "backtest") return;
      vider(zone);
      ajouter(zone, contenuBacktest());
    });
    return [el("div", { class: "titre-page" }, el("h1", null, "Backtest"),
      el("p", { class: "chapo" }, "La stratégie rejouée mois par mois sur la composition historique de l'indice : le score, les signaux et le portefeuille sont recalculés à chaque fin de mois avec les seules informations connues à cette date.")), zone];
  }

  function contenuBacktest() {
    const b = S.sourceBt === "prix" && S.backtestPrix ? S.backtestPrix : S.backtest;
    if (!b) return [el("div", { class: "vide" }, el("strong", null, "Le backtest n'est pas encore calculé."), el("span", null, "Il est recalculé chaque semaine et dès que les réglages changent. Reviens après la prochaine actualisation."))];
    const reg = b.reglages;
    const periodes = Object.keys(b.metriques);
    if (S.periode >= periodes.length) S.periode = 0;
    const nomPeriode = periodes[S.periode];
    const dv = reg.debut_validation;
    const bornes = [[b.debut, b.fin], [b.debut, dv], [dv, b.fin]];
    const [debut, fin] = bornes[S.periode] || bornes[0];
    const outils = el("div", { class: "filtres" });
    if (S.backtestPrix) {
      outils.append(el("div", { class: "segments", role: "group", "aria-label": "Version du backtest" },
        [["complet", "Cours et comptes (depuis " + S.backtest.debut.slice(0, 4) + ")"], ["prix", "Cours seulement (depuis " + S.backtestPrix.debut.slice(0, 4) + ")"]].map(([k, nom]) =>
          el("button", { type: "button", "aria-pressed": String(S.sourceBt === k), onclick: () => { S.sourceBt = k; S.periode = 0; rendre(); } }, nom))));
    }
    outils.append(el("div", { class: "segments", role: "group", "aria-label": "Période" }, periodes.map((p, i) =>
      el("button", { type: "button", "aria-pressed": String(S.periode === i), onclick: () => { S.periode = i; rendre(); } }, p))));
    const t = b.metriques[nomPeriode];
    const val = (ind, serie) => { const i = t.index.indexOf(ind); const j = t.colonnes.indexOf(serie); return i >= 0 && j >= 0 ? t.valeurs[i][j] : null; };
    const tuile = (lib, ind, dec, note) => el("div", { class: "tuile" }, el("span", { class: "lib" }, lib),
      el("span", { class: "val" }, /Ratio/.test(ind) ? fNb(val(ind, "Stratégie"), 2) : fPct(val(ind, "Stratégie"), dec)),
      el("span", { class: "cmp" }, note || ("S&P 500 : " + (/Ratio/.test(ind) ? fNb(val(ind, "S&P 500 (SPY)"), 2) : fPct(val(ind, "S&P 500 (SPY)"), dec)))));
    const tuiles = el("div", { class: "tuiles" },
      tuile("Rendement annualisé", "Rendement annualisé", 1),
      tuile("Perte maximale", "Perte maximale", 1),
      tuile("Ratio de Sharpe", "Ratio de Sharpe", 2),
      tuile("Périodes de 12 mois battant le S&P 500", "Périodes de 12 mois battant le S&P 500", 0, "pire période de 12 mois : " + fPct(val("Pire période de 12 mois", "Stratégie"), 1)));

    // courbes rebasées sur la période
    const series = b.series.noms.map((nom, k) => {
      const rb = L.rebaser(b.series.dates, b.series.valeurs[k], debut, fin);
      return { nom, court: COURTS_BT[nom] || nom, cls: SERIES_BT[nom] || "s4", forte: nom === "Stratégie", valeurs: rb.valeurs, dates: rb.dates };
    });
    const dates = series.length ? series[0].dates : [];
    const figValeur = figure("Valeur d'un portefeuille de 1 au départ", "Dividendes réinvestis, frais de " + fPct(reg.frais, 2) + " par transaction déduits, " + reg.n_positions + " lignes à poids égal, rebalancement " + reg.rebalancement + ". Comparaison clé : l'univers équipondéré, construit avec exactement les mêmes données.", (corps) => {
      const bouton = el("button", { type: "button", class: "bouton discret", "aria-pressed": String(S.echelleLog) }, S.echelleLog ? "Échelle logarithmique" : "Échelle linéaire");
      bouton.addEventListener("click", () => { S.echelleLog = !S.echelleLog; rendre(); });
      corps.append(el("div", { class: "tete" }, legende(series), bouton));
      graphLignes(corps, { dates, series, log: S.echelleLog, hauteur: 340, titre: "Valeur de la stratégie et des indices de comparaison", fmtAxe: (v) => fNb(v, v < 10 && v !== Math.round(v) ? 1 : 0), fmtValeur: (v) => fNb(v, 2) });
    }, () => tableMensuelle(dates, series, (v) => fNb(v, 3)));
    const ddSeries = series.filter((s) => s.nom === "Stratégie" || s.nom === "S&P 500 (SPY)").map((s) => Object.assign({}, s, { valeurs: L.baisses(s.valeurs), aire: s.nom === "Stratégie" }));
    const figBaisse = figure("Baisse depuis le dernier plus haut", "La mesure du risque de perte : de combien la valeur était sous son meilleur niveau à chaque date.", (corps) => {
      corps.append(legende(ddSeries));
      graphLignes(corps, { dates, series: ddSeries, hauteur: 220, zero: true, baseAire: 0, titre: "Baisses depuis le plus haut", fmtAxe: (v) => fPct(v, 0), fmtValeur: (v) => fPct(v, 1) });
    }, () => tableMensuelle(dates, ddSeries, (v) => fPct(v, 1)));

    const an = b.annuel;
    const serAn = an.noms.filter((n) => n !== "S&P 500 équipondéré (RSP)").map((n) => ({ nom: n, cls: SERIES_BT[n], valeurs: an.valeurs[an.noms.indexOf(n)] }));
    const etiqAn = (a) => String(a) + (an.partielles.includes(a) ? "*" : "");
    const figAn = figure("Rendement de chaque année", "* année incomplète (début ou fin du backtest).", (corps) => {
      corps.append(legende(serAn, true));
      graphBarres(corps, { categories: an.annees, series: serAn, hauteur: 260, fmtAxe: (v) => fPct(v, 0), fmtValeur: (v) => fPct(v, 1), etiquette: etiqAn, titreCategorie: etiqAn, titre: "Rendements annuels" });
    }, () => tableSimple(["Année"].concat(an.noms), an.annees.map((a, i) => [etiqAn(a)].concat(an.noms.map((n, k) => fPct(an.valeurs[k][i], 1))))));

    const tableMetriques = el("section", { class: "bloc" }, el("header", null, el("h2", null, "Tous les indicateurs"), el("p", null, nomPeriode)),
      tableSimple(["Indicateur"].concat(t.colonnes), t.index.map((ind, i) => [ind].concat(t.colonnes.map((c, j) => FORMATS_IND(ind)(t.valeurs[i][j]))))));

    const analyse = [];
    if (b.quintiles) {
      const q = b.quintiles;
      const cats = q.index.map((x) => x.split(" ")[0]);
      const col = (nom) => q.valeurs.map((l) => l[q.colonnes.indexOf(nom)]);
      analyse.push(el("div", { class: "deux-colonnes" },
        figure("Rendement moyen à 12 mois, par quintile de score", "Q1 = les 20 % de scores les plus faibles, Q5 = les 20 % les plus élevés. Un score utile monte de Q1 à Q5.", (corps) =>
          graphBarres(corps, { categories: cats, series: [{ nom: "Rendement moyen à 12 mois", cls: "s1", valeurs: col("Rendement moyen à 12 mois") }], hauteur: 220, fmtAxe: (v) => fPct(v, 0), fmtValeur: (v) => fPct(v, 1), titreCategorie: (c) => q.index[cats.indexOf(c)] })),
        figure("Part des actions en baisse 12 mois plus tard", "Un score utile fait baisser cette part de Q1 à Q5 : c'est l'objectif « le moins de pertes possible ».", (corps) =>
          graphBarres(corps, { categories: cats, series: [{ nom: "Part en baisse à 12 mois", cls: "s1", valeurs: col("Part des titres en baisse à 12 mois") }], hauteur: 220, fmtAxe: (v) => fPct(v, 0), fmtValeur: (v) => fPct(v, 1), titreCategorie: (c) => q.index[cats.indexOf(c)] }))));
    }
    if (b.signaux) {
      const s = b.signaux;
      analyse.push(el("div", { class: "bloc" }, el("h3", null, "Ce que sont devenues les actions selon leur signal, 12 mois plus tard"),
        tableSimple(["Signal", "Rendement moyen à 12 mois", "Part en baisse à 12 mois", "Actions par mois"], s.index.map((sig, i) => [pastille(sig), fPct(s.valeurs[i][0], 1), fPct(s.valeurs[i][1], 1), fNb(s.valeurs[i][2], 0)]))));
    }
    if (b.facteurs) {
      analyse.push(el("div", { class: "bloc" }, el("h3", null, "Pouvoir prédictif de chaque famille de facteurs"),
        el("p", { class: "petit second" }, "IC = corrélation de rang entre le facteur et le rendement futur, mois par mois. Un IC moyen de 0,02 à 0,05 est déjà intéressant ; une t-stat au-dessus de 2 (idéalement 3) indique un effet probablement réel."),
        tableSimple(["Facteur", "IC moyen à 1 mois", "t-stat", "Mois avec IC > 0", "IC moyen à 12 mois", "t-stat à 12 mois"],
          b.facteurs.map((f) => [f["Facteur"], fNb(f["IC moyen à 1 mois"], 3), fNb(f["t-stat (1 mois)"], 1), fPct(f["Mois avec IC > 0"], 0), fNb(f["IC moyen à 12 mois"], 3), fNb(f["t-stat (12 mois, sans chevauchement)"], 1)]))));
    }
    const sy = b.synthese;
    const synthese = el("div", { class: "tuiles" },
      el("div", { class: "tuile" }, el("span", { class: "lib" }, "Rotation annuelle (achats + ventes)"), el("span", { class: "val" }, fPct(sy["Rotation annuelle moyenne"], 0))),
      el("div", { class: "tuile" }, el("span", { class: "lib" }, "Frais cumulés"), el("span", { class: "val" }, fPct(sy["Frais cumulés (% du capital)"], 1))),
      el("div", { class: "tuile" }, el("span", { class: "lib" }, "Lignes en moyenne"), el("span", { class: "val" }, fNb(sy["Lignes en moyenne"], 1))),
      el("div", { class: "tuile" }, el("span", { class: "lib" }, "Liquidités moyennes"), el("span", { class: "val" }, fPct(sy["Liquidités moyennes"], 1))),
      el("div", { class: "tuile" }, el("span", { class: "lib" }, "Membres de l'indice avec données"), el("span", { class: "val" }, fPct(sy["Couverture des données (moyenne)"], 0))));

    const j = b.journal.slice().reverse();
    const visibles = S.journalComplet ? j : j.slice(0, 12);
    const journal = el("section", { class: "bloc" },
      el("header", null, el("h2", null, "Journal des décisions"), el("p", null, j.length + " fins de mois, de la plus récente à la plus ancienne")),
      tableSimple(["Date", "Type", "Lignes", "Achats", "Ventes", "Rotation", "Liquidités"], visibles.map((x) => [fDate(x.date),
        x.rebalancement ? "Rebalancement" : (x.ventes.length ? "Ventes d'urgence" : "Suivi"), fNb(x.positions),
        el("span", { class: "texte-long" }, x.achats.join(", ") || "—"), el("span", { class: "texte-long" }, x.ventes.join(", ") || "—"),
        fPct(x.rotation, 0), fPct(x.liquidites, 0)]), 2),
      j.length > 12 ? el("button", { type: "button", class: "bouton voir-plus", onclick: () => { S.journalComplet = !S.journalComplet; rendre(); } }, S.journalComplet ? "Afficher seulement les 12 derniers mois" : "Afficher les " + j.length + " mois") : null);
    const cv = b.couverture;
    const figCouv = figure("Part des membres de l'indice avec des cours", "Les sociétés rachetées ou disparues manquent chez Yahoo : elles ne peuvent pas être détenues dans le backtest, ce qui l'embellit un peu.", (corps) =>
      graphLignes(corps, { dates: cv.dates, series: [{ nom: "Couverture", court: "", valeurs: cv.valeurs, cls: "s1" }], hauteur: 160, min: 0, max: 1, etiquettesFin: false, titre: "Couverture des données", fmtAxe: (v) => fPct(v, 0), fmtValeur: (v) => fPct(v, 1) }));
    return [
      outils, tuiles, figValeur, figBaisse, figAn, tableMetriques,
      el("section", { class: "bloc" }, el("header", null, el("h2", null, "Le score prédit-il quelque chose ?"),
        el("p", null, "Chaque mois, les actions sont rangées en cinq groupes selon leur score, puis suivies sur 12 mois")), analyse),
      el("section", { class: "bloc" }, el("h2", null, "Coûts et exposition"), synthese),
      journal, figCouv,
      el("div", { class: "avert" }, el("strong", null, "À lire avant d'y croire. "), "Un backtest décrit le passé, pas l'avenir. Les sociétés disparues manquent (biais favorable), les impôts ne sont pas déduits, et chaque réglage modifié après avoir vu ces résultats rend le prochain backtest plus optimiste qu'il ne devrait. Seule la période de validation, jamais retouchée, donne une idée honnête."),
      el("p", { class: "petit muet" }, "Calculé le " + L.fDateHeure(b.genere_le) + ", du " + fDate(b.debut) + " au " + fDate(b.fin) + "."),
    ];
  }

  function tableMensuelle(dates, series, fmt) {
    const idx = [];
    for (let i = 0; i < dates.length; i++) if (i === dates.length - 1 || dates[i].slice(0, 7) !== dates[i + 1].slice(0, 7)) idx.push(i);
    return tableSimple(["Fin de mois"].concat(series.map((s) => s.nom)), idx.map((i) => [dates[i]].concat(series.map((s) => fmt(s.valeurs[i])))));
  }

  // ================================================================== vue : méthode, réglages, sources
  const LIBELLES = {
    mode: ["Mode", (v) => (v === "complet" ? "cours et comptes" : "cours seulement")],
    n_positions: ["Lignes du portefeuille", (v) => fNb(v)], max_par_secteur: ["Part maximale d'un secteur", (v) => fPct(v, 0)],
    seuil_achat: ["ACHETER : score d'au moins", (v) => fNb(v)], robustesse_min_achat: ["… et robustesse d'au moins", (v) => fNb(v)],
    seuil_garder: ["GARDER : score d'au moins", (v) => fNb(v)], seuil_vente: ["VENDRE : score sous", (v) => fNb(v)],
    poids_potentiel: ["Poids du potentiel dans le score", (v) => fPct(v, 0)], fscore_min: ["F-score de Piotroski minimum", (v) => fNb(v, 0) + " / 9"],
    couverture_min: ["Couverture des intérêts minimale", (v) => fMult(v)],
    couverture_min_secteurs: ["… exceptions par secteur", (v) => Object.entries(v || {}).map(([k, x]) => k + " " + fMult(x)).join(", ") || "aucune"],
    exclusion_levier_secteur: ["Exclusion des plus endettés du secteur", (v) => fPct(v, 0)],
    exclusion_accruals_secteur: ["Exclusion des pires accruals du secteur", (v) => fPct(v, 0)],
    exclusion_volatilite: ["Exclusion des plus volatiles de l'indice", (v) => fPct(v, 0)],
    secteurs_sans_filtre_fcf: ["Secteurs dispensés du filtre free cash-flow", (v) => (v || []).join(", ") || "aucun"],
    beneish_exclut: ["M-score de Beneish éliminatoire", (v) => (v ? "oui" : "non, simple alerte")],
    debut_backtest: ["Début du backtest", (v) => fDate(v)], debut_validation: ["Début de la période de validation", (v) => fDate(v)],
    frais: ["Frais par transaction", (v) => fPct(v, 2)], rebalancement: ["Rebalancement", (v) => v],
    ventes_urgence: ["Ventes d'urgence entre deux rebalancements", (v) => (v ? "oui" : "non")],
    revisions_analystes: ["Révisions des analystes", (v) => (v ? "utilisées" : "ignorées")],
  };

  function vueMethode() {
    const c = S.classement;
    const reg = c.reglages;
    const e = S.etat || {};
    const liens = e.liens || {};
    const so = e.sources || {};
    const methode = el("section", { class: "bloc" }, el("h2", null, "Comment le classement est construit"),
      el("div", { class: "texte" }, el("ul", null,
        el("li", null, el("strong", null, "Filtres de sécurité éliminatoires. "), "F-score de Piotroski d'au moins " + fNb(reg.fscore_min, 0) + "/9 ; couverture des intérêts d'au moins " + fMult(reg.couverture_min) + " ; pas parmi les " + fPct(reg.exclusion_levier_secteur, 0) + " les plus endettés de son secteur ; free cash-flow positif sur 3 ans ; accruals hors des " + fPct(reg.exclusion_accruals_secteur, 0) + " pires du secteur lorsqu'ils sont positifs (bénéfice supérieur au cash-flow d'exploitation) ; hors des " + fPct(reg.exclusion_volatilite, 0) + " d'actions les plus volatiles de l'indice."),
        el("li", null, el("strong", null, "Potentiel. "), "Momentum sur 12 mois hors dernier mois, dynamique des résultats (bénéfice trimestriel comparé à l'an passé, révisions des analystes sur 90 jours) et valorisation (rendement du free cash-flow, EBIT rapporté à la valeur d'entreprise, rendement des bénéfices)."),
        el("li", null, el("strong", null, "Robustesse. "), "Qualité (rentabilité brute, ROA, flux de trésorerie, stabilité, endettement) et faible risque (volatilité, bêta, perte maximale sur un an)."),
        el("li", null, el("strong", null, "Comparaison au secteur. "), "Chaque indicateur devient un rang parmi les actions du même secteur ; le score final est un rang de 0 à 100 sur tout l'indice."),
        el("li", null, el("strong", null, "Comptes datés au jour de leur publication. "), "Les chiffres viennent des dépôts officiels à la SEC, tels que publiés la première fois : le backtest n'utilise jamais une information qui n'était pas encore connue."),
        el("li", null, el("strong", null, "Comptes incomplets. "), "Le F-score est ramené sur 9 quand un critère n'est pas mesurable, à condition d'en mesurer au moins 6 (5 pour les financières, sans ratio de liquidité ni marge brute). Si le dernier rapport est incomplet (scission récente, changement de date de clôture), le précédent rapport complet reste en vigueur pendant 400 jours au plus ; une société passée sous une nouvelle holding garde l'historique de l'ancienne.")),
      ));
    const signaux = el("section", { class: "bloc" }, el("h2", null, "Les signaux"),
      tableSimple(["Signal", "Règle", "Ce que tu en fais"], [
        [pastille("ACHETER"), "Score d'au moins " + reg.seuil_achat + ", robustesse d'au moins " + reg.robustesse_min_achat + ", tous les filtres passés", "Candidate à l'achat"],
        [pastille("GARDER"), "Score d'au moins " + reg.seuil_garder, "La conserver si tu l'as ; pas prioritaire à l'achat"],
        [pastille("SURVEILLER"), "Score de " + reg.seuil_vente + " à " + reg.seuil_garder, "La conserver, en la surveillant"],
        [pastille("VENDRE"), "Score sous " + reg.seuil_vente + ", ou un filtre de sécurité échoué", "Vendre ou éviter (le motif est indiqué)"],
        [pastille("DONNÉES INSUFFISANTES"), "Moins de 200 séances de cours, ou comptes trop incomplets pour le F-score (le motif précise la cause)", "Pas d'avis"],
      ], 3),
      el("p", { class: "petit second" }, "La zone GARDER et SURVEILLER sert de tampon : on n'achète que le haut du classement mais on ne vend qu'en cas de vraie dégradation, ce qui limite les allers-retours, donc les frais et l'impôt sur les plus-values."));
    const lignesReg = Object.entries(LIBELLES).filter(([k]) => k in reg).map(([k, [lib, f]]) => [el("dt", null, lib), el("dd", null, f(reg[k]))]);
    const reglagesBloc = el("section", { class: "bloc reglages" }, el("header", null, el("h2", null, "Réglages en vigueur"), el("p", null, "Fichier reglages.json de ton dépôt GitHub")),
      el("div", { class: "panneau" }, el("dl", null, lignesReg),
        el("div", { class: "texte petit" }, el("p", null, "Pour les modifier, change le fichier reglages.json sur GitHub puis enregistre (Commit changes) : le site se recalcule tout seul, backtest compris, en 20 à 40 minutes."),
          el("p", null, el("strong", null, "Règle d'or : "), "fixe tes réglages avant de regarder le backtest. Les ajuster jusqu'à obtenir une belle courbe rend le backtest trompeur.")),
        el("div", { class: "actions-fiche" }, liens.reglages ? externe(liens.reglages, "Modifier les réglages sur GitHub", "bouton principal") : null)));
    const lst = [];
    if (so.cours) lst.push(["Cours (Yahoo Finance)", so.cours.obtenus + " titres sur " + so.cours.demandes + (so.cours.par_alpaca && so.cours.par_alpaca.length ? ", dont " + so.cours.par_alpaca.length + " par Alpaca" : "") + ", dernière séance le " + fDate(so.cours.derniere_seance)]);
    if (so.sec) lst.push(["Comptes officiels (SEC EDGAR)", so.sec.exploitables + " sociétés exploitables sur " + so.sec.societes + (so.sec.rapports_edgar ? " ; " + so.sec.rapports_edgar + " rapport" + (so.sec.rapports_edgar > 1 ? "s" : "") + " récent" + (so.sec.rapports_edgar > 1 ? "s" : "") + " encore absent" + (so.sec.rapports_edgar > 1 ? "s" : "") + " de l'API XBRL de la SEC, lu" + (so.sec.rapports_edgar > 1 ? "s" : "") + " directement dans les dépôts" : "")]);
    if (so.revisions) lst.push(["Révisions d'analystes (Yahoo Finance)", so.revisions.obtenues + " titres sur " + so.revisions.demandes]);
    if (so.univers) lst.push(["Composition de l'indice", so.univers]);
    if (so.taux) lst.push(["Taux sans risque du backtest", so.taux.source]);
    const sourcesBloc = el("section", { class: "bloc reglages" }, el("header", null, el("h2", null, "Actualisation et sources"),
      el("p", null, e.genere_le ? "Dernière actualisation le " + L.fDateHeure(e.genere_le) + (fini(e.duree_s) ? " en " + Math.max(1, Math.round(e.duree_s / 60)) + " min" : "") : "")),
      el("div", { class: "panneau" },
        el("p", { class: "petit second" }, "Le calcul tourne sur GitHub Actions chaque soir de bourse vers 23 h 20 UTC (1 h 20 à Paris en été), après la clôture de New York, et le samedi pour le backtest. Il ne dépend ni de ton navigateur ni de ton ordinateur."),
        el("dl", { class: "empile" }, lst.map(([k, v]) => [el("dt", null, k), el("dd", null, v)])),
        (e.avertissements || []).length ? el("div", { class: "texte petit" }, el("strong", null, "Avertissements de la dernière actualisation"), el("ul", null, e.avertissements.map((a) => el("li", null, a)))) : null,
        el("div", { class: "actions-fiche" },
          liens.actions ? externe(liens.actions, "Lancer une actualisation maintenant", "bouton") : null,
          liens.execution ? externe(liens.execution, "Journal de la dernière actualisation", "bouton") : null)));
    const fichiers = [["rapports/classement.xlsx", "Classement complet (Excel)"], ["rapports/classement.html", "Rapport du jour (page HTML)"],
      ["rapports/backtest.xlsx", "Backtest détaillé (Excel)"], ["rapports/backtest.html", "Rapport du backtest (page HTML)"]].filter(([f]) => (e.rapports || []).includes(f.split("/")[1]));
    const telech = el("section", { class: "bloc" }, el("h2", null, "Téléchargements"),
      e.demo ? el("p", { class: "petit second" }, "Les fichiers Excel et les rapports seront disponibles sur ton site.") : null,
      el("div", { class: "telechargements" }, fichiers.map(([f, nom]) => el("a", { class: "bouton", href: f, download: f.split("/")[1] }, nom)),
        el("button", { type: "button", class: "bouton", onclick: () => exporterClassement(c.rows) }, "Classement (CSV)")));
    const securite = el("section", { class: "bloc" }, el("h2", null, "Confidentialité et sécurité"),
      el("div", { class: "texte" }, el("ul", null,
        el("li", null, "Le site est un ensemble de fichiers statiques servis en HTTPS par GitHub Pages : pas de serveur à pirater, pas de base de données, pas de compte."),
        el("li", null, "Aucun script externe ni traceur : tout ce que la page exécute vient de ton dépôt."),
        el("li", null, "Tes positions et ton montant restent dans ce navigateur. Ils ne sont envoyés nulle part ; exporte-les pour les retrouver sur un autre appareil."),
        el("li", null, "L'adresse e-mail exigée par la SEC est un secret GitHub chiffré : elle n'apparaît ni sur le site ni dans les fichiers téléchargeables."),
        el("li", null, "Le site est public pour qui connaît son adresse et n'est pas référencé par les moteurs de recherche. Il ne contient que des données de marché publiques."))));
    const limites = el("section", { class: "bloc" }, el("h2", null, "Limites à connaître"),
      el("div", { class: "texte" }, el("ul", null,
        el("li", null, "Yahoo Finance est une source gratuite non officielle : en cas de panne, l'actualisation échoue proprement et le site garde les données précédentes, avec un message."),
        el("li", null, "Les comptes XBRL de la SEC sont bruts : quand une société utilise une étiquette inhabituelle, l'indicateur manque plutôt que d'être inventé."),
        el("li", null, "Aucun score ne garantit qu'une action ne baissera pas : même l'indice recule en moyenne d'environ 14 % à un moment de l'année."),
        el("li", null, "Chaque vente peut déclencher de l'impôt sur la plus-value ; le backtest ne le déduit pas."))));
    return [el("div", { class: "titre-page" }, el("h1", null, "Méthode"), el("p", { class: "chapo" }, "Comment le screener note les actions, d'où viennent les données, et comment changer ses réglages.")),
      el("div", { class: "deux-colonnes" }, el("div", { class: "colonne" }, methode, signaux, securite, limites), el("div", { class: "colonne" }, reglagesBloc, sourcesBloc, telech))];
  }

  // ================================================================== exports
  function telecharger(nom, contenu, type) {
    if (S.etat && S.etat.demo) {
      montrerMessage("Le téléchargement n'est pas disponible dans l'aperçu ; il fonctionnera sur ton site.");
      return;
    }
    try {
      const url = URL.createObjectURL(new Blob([contenu], { type: type + ";charset=utf-8" }));
      const a = el("a", { href: url, download: nom });
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (e) {
      montrerMessage("Le téléchargement a échoué : " + e.message);
    }
  }
  function montrerMessage(texte) {
    const zone = document.getElementById("vue");
    const b = bandeau("attention", texte);
    zone.prepend(b);
    setTimeout(() => b.remove(), 6000);
  }
  function exporterClassement(rows) {
    const cols = [["t", "Ticker"], ["nom", "Société"], ["secteur_fr", "Secteur"], ["signal", "Signal"], ["score", "Score"], ["potentiel", "Potentiel"],
      ["robustesse", "Robustesse"], ["mom", "Momentum 12-1"], ["vol", "Volatilité 1 an"], ["beta", "Bêta"], ["mdd", "Perte max 1 an"],
      ["revision", "Révision BPA 90 j"], ["rend_fcf", "Rendement FCF"], ["ebit_ve", "EBIT / VE"], ["rend_benef", "Rendement bénéfices"],
      ["fscore_9", "F-score /9"], ["couverture", "Couverture intérêts"], ["dette_ebitda", "Dette nette / EBITDA"], ["accruals", "Accruals"],
      ["beneish", "M-score Beneish"], ["capitalisation", "Capitalisation ($)"], ["cours", "Cours ($)"], ["motif", "Motif"], ["alertes", "Alertes"]];
    const contenu = L.csv(rows.map((r) => cols.map(([k]) => (k === "motif" ? motifAffiche(r) : r[k]))), cols.map(([, t]) => t));
    telecharger("classement_" + S.classement.date + ".csv", contenu, "text/csv");
  }

  // ================================================================== démarrage
  async function demarrer() {
    S.route = routeDepuisAdresse();
    const main = document.getElementById("vue");
    try {
      const [c, e, h] = await Promise.all([charger("data/classement.json"), charger("data/etat.json", true), charger("data/historique.json", true)]);
      S.classement = L.preparerClassement(c);
      S.etat = e;
      S.historique = h;
      S.positions = S.positions.map(L.normaliserTicker).filter(Boolean);
    } catch (err) {
      vider(main);
      main.append(el("div", { class: "titre-page" }, el("h1", null, "Les données ne sont pas encore disponibles"),
        el("p", { class: "chapo" }, "La première actualisation prend 20 à 40 minutes après la mise en place. Si elle est terminée, ouvre l'onglet Actions de ton dépôt GitHub pour voir ce qui s'est passé."),
        el("p", { class: "muet petit" }, "Détail : " + err.message)));
      majEtatEntete();
      return;
    }
    majEtatEntete();
    rendre();
    setInterval(majEtatEntete, 60000);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", demarrer);
  else demarrer();
})();
