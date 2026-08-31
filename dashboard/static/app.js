"use strict";
/* =====================================================================
   weather · kalshi trading desk — vanilla frontend (zero build)
   Talks to the FastAPI JSON API (dashboard/app.py). Render functions build
   HTML strings → innerHTML; state lives in module globals; the backtest sim
   runs entirely client-side (jsComputeSim, ported verbatim from the former
   React app.jsx so tests/test_sim_parity.py stays green).
   ===================================================================== */

/* ---------- animation timing (tunable; user-signed-off prototype values) ----------
   Override note: 2400 forced a wait to read live P&L on a glance tool reopened
   all day; 900 keeps the entrance "moment" without stalling the read. */
const LOAD_MS = 900;    // entrance count-up from 0 — the hero "moment"
const TICK_MS = 400;    // live-poll prev→new tween
const easeOutExpo  = t => t >= 1 ? 1 : 1 - Math.pow(2, -10 * t);   // load easing
const easeOutCubic = t => 1 - Math.pow(1 - t, 3);                  // tick easing
const easeOutQuint = t => 1 - Math.pow(1 - t, 5);                  // softer tick alt
const RM = matchMedia('(prefers-reduced-motion: reduce)');

/* ---------- formatters (ported from components.jsx) ---------- */
function money(v, opts) {
  opts = opts || {};
  const sign = opts.sign === undefined ? true : opts.sign;
  const dp = opts.dp === undefined ? 2 : opts.dp;
  if (v === null || v === undefined) return "—";
  const s = v < 0 ? "−" : (sign ? "+" : "");
  return s + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}
function moneyPlain(v) {
  if (v === null || v === undefined) return "—";
  return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function pct(v, dp) {
  if (dp === undefined) dp = 1;
  if (v === null || v === undefined) return "—";
  const s = v < 0 ? "−" : "+";
  return s + Math.abs(v).toFixed(dp) + "%";
}
function cls(v) { return v > 0 ? "pos" : v < 0 ? "neg" : "muted"; }
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
let _uid = 0;

/* ---------- animation engine (shared; E2/E3 consume these) ----------
   rampClock = ONE requestAnimationFrame loop off a single performance.now()
   start, so all hero numbers AND the chart draw finish on the SAME frame.
   E2 calls it once on first paint:
     rampClock(LOAD_MS, easeOutExpo, e => { heroNumber = target * e (formatted);
                                            pnl-chart draw progress = e; });
   countUp drives INDIVIDUAL live ticks (TICK_MS) from the PREVIOUS value via
   prevLive — never from 0. snapshot(d) flattens a /api/live payload to the
   scalar set E2 diffs across polls. */
function rampClock(durationMs, easeFn, onFrame, onDone) {
  easeFn = easeFn || (t => t);
  if (RM.matches || document.hidden) {          // reduced-motion / background tab → jump to end
    if (onFrame) onFrame(1);
    if (onDone) onDone();
    return;
  }
  const start = performance.now();
  function frame(now) {
    const t = Math.min(1, (now - start) / durationMs);
    if (onFrame) onFrame(easeFn(t));
    if (t < 1) requestAnimationFrame(frame);
    else if (onDone) onDone();
  }
  requestAnimationFrame(frame);
}

// Tween one element's text. mode "load" = 0→to over LOAD_MS (easeOutExpo);
// "update" = from→to over TICK_MS (easeOutCubic). Honors reduced-motion/hidden
// (sets the final text instantly). CSS uses tabular-nums so width never jitters.
function countUp(el, fromVal, toVal, fmtFn, mode) {
  if (!el) return;
  fmtFn = fmtFn || (v => String(v));
  mode = mode || "update";
  const from = mode === "load" ? 0 : (fromVal == null ? toVal : fromVal);
  if (from === toVal) { el.textContent = fmtFn(toVal); return; }
  const dur  = mode === "load" ? LOAD_MS : TICK_MS;
  const ease = mode === "load" ? easeOutExpo : easeOutCubic;
  rampClock(dur, ease,
    e  => { el.textContent = fmtFn(from + (toVal - from) * e); },
    () => { el.textContent = fmtFn(toVal); });
}

// Flatten a /api/live payload to the scalar values E2's diff pass compares
// (prevLive → LIVE) to decide which numbers tick and which way they flash.
function snapshot(d) {
  if (!d) return null;
  const t = d.today || {}, c = d.cumulative || {};
  const marks = {};
  (d.positions || []).forEach(p => { marks[p.ticker] = p.mark; });
  return {
    balance: d.venueBalances ? d.venueBalances.total : d.balance,
    todayTotal: t.total, todayRealized: t.realized, todayUnrealized: t.unrealized,
    cumTotal: c.total, cumReturn: c.returnPct, winRate: c.winRate, nSettled: c.nSettled,
    marks,
  };
}

/* ---------- chart math (erf/normPdf used by the ensemble chart) ---------- */
function erf(x) {
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return x >= 0 ? y : -y;
}
const normPdf = (x, mu, s) => Math.exp(-0.5 * ((x - mu) / s) ** 2) / (s * Math.sqrt(2 * Math.PI));

/* ---------- SVG chart builders (static; viewBox scales to width) ---------- */
function sparkSVG(data, color) {
  if (!data || data.length < 2) return "";
  const w = 132, h = 34;
  const vals = data.map(d => d.v);
  const min = Math.min(0, ...vals), max = Math.max(0, ...vals);
  const span = (max - min) || 1;
  const x = i => (i / (data.length - 1)) * w;
  const y = v => h - ((v - min) / span) * h;
  const line = data.map((d, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(d.v).toFixed(1)}`).join(" ");
  const area = `${line} L${w},${h} L0,${h} Z`;
  const last = vals[vals.length - 1];
  const c = color || (last >= 0 ? "var(--up)" : "var(--down)");
  const gid = "sg" + (++_uid);
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c}" stop-opacity="0.22"/><stop offset="1" stop-color="${c}" stop-opacity="0"/></linearGradient></defs><path d="${area}" fill="url(#${gid})"/><path d="${line}" fill="none" stroke="${c}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}

function pnlChartSVG(data) {
  if (!data || data.length < 2) { CHARTS.pnl = null; return `<div class="loading">No P&amp;L series.</div>`; }
  const w = 720, height = 232;
  const padL = 14, padR = 58, padT = 14, padB = 26;
  const iw = w - padL - padR, ih = height - padT - padB;
  const vals = data.map(d => d.v);
  let min = Math.min(0, ...vals), max = Math.max(0, ...vals);
  const pad = (max - min) * 0.12 || 1; min -= pad; max += pad;
  const span = (max - min) || 1;
  const X = i => padL + (i / (data.length - 1)) * iw;
  const Y = v => padT + (1 - (v - min) / span) * ih;
  const tickVals = Array.from({ length: 5 }, (_, i) => min + (span * i) / 4);
  const zeroY = Y(0);
  const last = vals[vals.length - 1];
  const c = last >= 0 ? "var(--up)" : "var(--down)";
  const line = data.map((d, i) => `${i === 0 ? "M" : "L"}${X(i).toFixed(1)},${Y(d.v).toFixed(1)}`).join(" ");
  const area = `${line} L${X(data.length - 1)},${zeroY} L${X(0)},${zeroY} Z`;
  // Rolling series: ~6 evenly-spaced date ticks (each point carries t='YYYY-MM-DD').
  const nLab = Math.min(6, data.length);
  const labIdx = Array.from({ length: nLab }, (_, k) => Math.round(k * (data.length - 1) / (nLab - 1)));
  const grid = tickVals.map(tv =>
    `<line x1="${padL}" x2="${padL + iw}" y1="${Y(tv)}" y2="${Y(tv)}" stroke="var(--border)" stroke-width="1" stroke-dasharray="${Math.abs(tv) < 1e-6 ? "0" : "2 4"}"/><text x="${padL + iw + 8}" y="${Y(tv) + 3.5}" fill="var(--text-faint)" style="font:500 10px var(--mono)">${(tv >= 0 ? "" : "−") + "$" + Math.abs(Math.round(tv))}</text>`).join("");
  const xlab = labIdx.map(i => `<text x="${X(i)}" y="${height - 8}" text-anchor="middle" fill="var(--text-faint)" style="font:500 9.5px var(--mono)">${(data[i].t || "").slice(5)}</text>`).join("");
  // hover overlay builder (crosshair + dot + cumulative-P&L tooltip)
  CHARTS.pnl = { W: w, n: data.length, X, build: (i) =>
    `<line x1="${X(i).toFixed(1)}" x2="${X(i).toFixed(1)}" y1="${padT}" y2="${padT + ih}" stroke="var(--border-strong)" stroke-width="1"/><circle cx="${X(i).toFixed(1)}" cy="${Y(data[i].v).toFixed(1)}" r="3.5" fill="${c}" stroke="var(--bg-1)" stroke-width="2"/><g transform="translate(${Math.min(X(i) + 8, padL + iw - 78).toFixed(1)},${padT + 2})"><rect width="74" height="20" rx="4" fill="var(--bg-3)" stroke="var(--border-strong)"/><text x="8" y="14" fill="var(--text-hi)" style="font:600 11px var(--mono)">${money(data[i].v, { sign: true, dp: 0 })}</text></g>`
  };
  return `<svg width="${w}" height="${height}" viewBox="0 0 ${w} ${height}" data-chart="pnl" role="img" aria-label="Cumulative realized P&amp;L, since first live trade"><defs><linearGradient id="pnlfill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c}" stop-opacity="0.20"/><stop offset="1" stop-color="${c}" stop-opacity="0.01"/></linearGradient><clipPath id="pnlrev" clipPathUnits="userSpaceOnUse"><rect class="chart-fill-reveal" x="${padL}" y="${padT}" width="${iw}" height="${ih}"/></clipPath></defs>${grid}<line x1="${padL}" x2="${padL + iw}" y1="${zeroY}" y2="${zeroY}" stroke="var(--border-strong)" stroke-width="1"/><path d="${area}" fill="url(#pnlfill)" clip-path="url(#pnlrev)"/><path class="chart-line" d="${line}" fill="none" stroke="${c}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>${xlab}<g class="cx"></g></svg>`;
}

function ensembleChartSVG(d) {
  const w = 760, height = 248;
  if (!d.members || d.members.length === 0)
    return `<div style="padding:24px;color:var(--text-lo);text-align:center">No ensemble data for ${esc(d.date)}.</div>`;
  const padL = 16, padR = 16, padT = 16, padB = 30;
  const iw = w - padL - padR, ih = height - padT - padB;
  // FIX 1: d.observed is truthful now — null EXACTLY when the day isn't resolved
  // (every bracket then reads "PEND"), a real high otherwise. So `observed != null`
  // IS the resolution signal, and it stays correct even on resolved dates that have
  // no bracket/contract rows (where a brackets-only check would wrongly hide a real
  // high — failing the regression guard). Centering falls back to ensMean via `??`
  // when unresolved (the `??` keeps a genuine 0° observed from being swallowed) —
  // never for the resolved-high label or the green line below.
  const resolved = d.observed != null;
  const center = d.observed ?? d.ensMean;
  const lo = Math.floor(Math.min(...d.members, center) - 1.5);
  const hi = Math.ceil(Math.max(...d.members, center) + 1.5);
  const X = t => padL + ((t - lo) / (hi - lo)) * iw;
  const bins = {};
  for (let t = lo; t <= hi; t++) bins[t] = 0;
  d.members.forEach(m => { const b = Math.round(m); if (bins[b] !== undefined) bins[b]++; });
  const maxCount = Math.max(...Object.values(bins), 1);
  const barW = iw / (hi - lo) * 0.82;
  // THERMAL RAMP gradient (cold→hot mapped across the temperature axis) — the ★ signature.
  const gid = "thm" + (++_uid);
  const thermalDef = `<defs><linearGradient id="${gid}" gradientUnits="userSpaceOnUse" x1="${padL}" y1="0" x2="${padL + iw}" y2="0"><stop offset="0" stop-color="var(--cold)"/><stop offset="0.28" stop-color="var(--cool)"/><stop offset="0.5" stop-color="var(--temperate)"/><stop offset="0.72" stop-color="var(--warm)"/><stop offset="0.9" stop-color="var(--hot)"/><stop offset="1" stop-color="var(--extreme)"/></linearGradient></defs>`;
  const pdfPeak = (d.emosSigma > 0) ? normPdf(d.emosMu, d.emosMu, d.emosSigma) : 1;
  let curve = "";
  if (d.emosSigma > 0) {
    const pts = [];
    for (let i = 0; i <= 80; i++) {
      const t = lo + (hi - lo) * (i / 80);
      const yv = (normPdf(t, d.emosMu, d.emosSigma) / pdfPeak) * (maxCount * 0.92);
      pts.push(`${i === 0 ? "M" : "L"}${X(t).toFixed(1)},${(padT + ih - (yv / maxCount) * ih).toFixed(1)}`);
    }
    curve = `<path d="${pts.join(" ")}" fill="none" stroke="url(#${gid})" stroke-width="2"/>`;
  }
  const boundaries = [...new Set((d.brackets || []).flatMap(b => [b.lo, b.hi]).filter(v => v > lo && v < hi && Math.abs(v) < 90))];
  const bnd = boundaries.map(bv => `<line x1="${X(bv + 0.5)}" x2="${X(bv + 0.5)}" y1="${padT}" y2="${padT + ih}" stroke="url(#${gid})" stroke-opacity="0.5" stroke-width="1" stroke-dasharray="2 4"/>`).join("");
  const bars = Object.entries(bins).map(([t, c]) => c > 0 ? `<rect x="${X(+t) - barW / 2}" y="${padT + ih - (c / maxCount) * ih}" width="${barW}" height="${(c / maxCount) * ih}" rx="1.5" fill="url(#${gid})"/>` : "").join("");
  // faint thermal bands behind the histogram, one per finite bracket region.
  const bracketFills = (d.brackets || []).map(b => {
    if (b.lo == null || b.hi == null) return "";
    const x0 = X(Math.max(b.lo, lo) - 0.5), x1 = X(Math.min(b.hi, hi) + 0.5);
    if (!(x1 > x0)) return "";
    return `<rect x="${x0.toFixed(1)}" y="${padT}" width="${(x1 - x0).toFixed(1)}" height="${ih}" fill="url(#${gid})" opacity="0.05"/>`;
  }).join("");
  const mean = d.ensMean > 0 ? `<line x1="${X(d.ensMean)}" x2="${X(d.ensMean)}" y1="${padT}" y2="${padT + ih}" stroke="var(--text-lo)" stroke-width="1" stroke-dasharray="3 3"/>` : "";
  let obs = "";
  // Only draw the green observed line on a genuinely resolved day. On PEND days
  // d.observed is null (resolved===false) — drawing would place the line at
  // X(null)=NaN and imply a high that doesn't exist yet.
  if (resolved) {
    obs = `<line x1="${X(d.observed)}" x2="${X(d.observed)}" y1="${padT - 2}" y2="${padT + ih}" stroke="var(--up)" stroke-width="2"/><g transform="translate(${Math.min(X(d.observed) + 6, padL + iw - 70)},${padT + 4})"><rect width="64" height="18" rx="4" fill="var(--up-dim)" stroke="var(--up-line)"/><text x="7" y="13" fill="var(--up)" style="font:600 10px var(--mono)">obs ${d.observed}°</text></g>`;
  }
  const xlab = Array.from({ length: hi - lo + 1 }, (_, i) => lo + i).filter(t => t % 2 === 0).map(t => `<text x="${X(t)}" y="${height - 9}" text-anchor="middle" class="chart-axis-x">${t}°</text>`).join("");
  return `<svg width="${w}" height="${height}" viewBox="0 0 ${w} ${height}" role="img" aria-label="Ensemble high-temperature distribution with EMOS overlay">${thermalDef}${bracketFills}${bnd}${bars}${curve}${mean}${obs}${xlab}</svg>`;
}

function balanceChartSVG(curve, filledTrades) {
  const w = 720, height = 300;
  if (!curve || curve.length < 2) { CHARTS.bal = null; return `<div style="padding:24px;color:var(--text-lo);text-align:center">No simulation curve.</div>`; }
  const padL = 14, padR = 64, padT = 14, padB = 26;
  const iw = w - padL - padR, ih = height - padT - padB;
  const start = curve[0];
  const rawMin = Math.min(...curve, start), rawMax = Math.max(...curve, start);
  function niceStep(range, targetTicks) {
    const rough = range / targetTicks;
    const exp = Math.pow(10, Math.floor(Math.log10(rough)));
    const norm = rough / exp;
    let step;
    if (norm < 1.5) step = 1; else if (norm < 3) step = 2; else if (norm < 7) step = 5; else step = 10;
    return step * exp;
  }
  const step = niceStep((rawMax - rawMin) || 1, 4);
  const min = Math.floor(rawMin / step) * step, max = Math.ceil(rawMax / step) * step;
  const span = (max - min) || 1;
  const X = i => padL + (i / (curve.length - 1)) * iw;
  const Y = v => padT + (1 - (v - min) / span) * ih;
  const last = curve[curve.length - 1];
  const c = last >= start ? "var(--up)" : "var(--down)";
  const line = curve.map((v, i) => `${i === 0 ? "M" : "L"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const tickVals = []; for (let v = min; v <= max + step * 0.01; v += step) tickVals.push(v);
  const grid = tickVals.map(tv => {
    const labelTxt = Math.abs(tv) >= 1000
      ? (tv < 0 ? "−$" : "$") + (Math.abs(tv) / 1000).toFixed(Math.abs(tv) >= 10000 ? 0 : 1) + "k"
      : (tv < 0 ? "−$" : "$") + Math.abs(Math.round(tv));
    return `<line x1="${padL}" x2="${padL + iw}" y1="${Y(tv)}" y2="${Y(tv)}" stroke="var(--border)" stroke-width="1" stroke-dasharray="2 4"/><text x="${padL + iw + 8}" y="${Y(tv) + 3.5}" fill="var(--text-faint)" style="font:500 10px var(--mono)">${labelTxt}</text>`;
  }).join("");
  const ft = filledTrades || [];
  const xlab = [0, Math.floor(curve.length * 0.25), Math.floor(curve.length * 0.5), Math.floor(curve.length * 0.75), curve.length - 1].map(i => {
    let label;
    if (i === 0) label = "start";
    else if (ft[i - 1] && ft[i - 1].date) label = ft[i - 1].date;
    else label = "t" + i;
    return `<text x="${X(i)}" y="${height - 8}" text-anchor="middle" fill="var(--text-faint)" style="font:500 9.5px var(--mono)">${esc(label)}</text>`;
  }).join("");
  // hover overlay builder (crosshair + dot + per-trade tooltip)
  const m2 = v => v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  CHARTS.bal = { W: w, n: curve.length, X, build: (i) => {
    const tradeAt = i > 0 ? ft[i - 1] : null;
    const cumPnl = curve[i] - start;
    const tw = 220, th = 88;
    let tx = Math.min(X(i) + 10, padL + iw - tw - 2); if (tx < padL + 2) tx = padL + 2;
    const ty = padT + 6;
    let rows = `<text x="10" y="16" fill="var(--text-hi)" style="font:600 11px var(--mono)">${tradeAt ? esc(tradeAt.date + " · " + tradeAt.bracket) : "Starting bankroll"}</text>`;
    if (tradeAt) {
      // executed side: blend/union can flip the raw model side — match the trade table + the P&L numbers
      const sideLbl = tradeAt.stratSide ? (tradeAt.stratSide === "BUY_YES" ? "YES" : "NO") : tradeAt.side;
      rows += `<text x="10" y="32" fill="var(--text-mid)" style="font:500 10.5px var(--mono)">${esc(sideLbl)} @ ${tradeAt.entry}¢ · qty ${tradeAt.computedQty}</text>`;
    }
    rows += `<text x="10" y="${tradeAt ? 50 : 32}" fill="var(--text-lo)" style="font:500 10px var(--mono)">BALANCE</text><text x="78" y="${tradeAt ? 50 : 32}" fill="var(--text-hi)" style="font:600 11px var(--mono)">$${m2(curve[i])}</text>`;
    if (tradeAt) rows += `<text x="10" y="66" fill="var(--text-lo)" style="font:500 10px var(--mono)">TRADE P&amp;L</text><text x="78" y="66" fill="${tradeAt.computedPnl >= 0 ? "var(--up)" : "var(--down)"}" style="font:600 11px var(--mono)">${tradeAt.computedPnl >= 0 ? "+" : "−"}$${m2(Math.abs(tradeAt.computedPnl))}</text><text x="10" y="80" fill="var(--text-lo)" style="font:500 10px var(--mono)">CUMULATIVE</text><text x="78" y="80" fill="${cumPnl >= 0 ? "var(--up)" : "var(--down)"}" style="font:600 11px var(--mono)">${cumPnl >= 0 ? "+" : "−"}$${m2(Math.abs(cumPnl))}</text>`;
    return `<line x1="${X(i).toFixed(1)}" x2="${X(i).toFixed(1)}" y1="${padT}" y2="${padT + ih}" stroke="var(--border-strong)" stroke-width="1"/><circle cx="${X(i).toFixed(1)}" cy="${Y(curve[i]).toFixed(1)}" r="4" fill="${c}" stroke="var(--bg-1)" stroke-width="2"/><g transform="translate(${tx.toFixed(1)},${ty})"><rect width="${tw}" height="${th}" rx="5" fill="var(--bg-3)" stroke="var(--border-strong)"/>${rows}</g>`;
  } };
  // drawdown shading — the area between the running peak and the equity curve is
  // time spent underwater. Shares the reveal clip so it sweeps in with the fill.
  let pk = curve[0]; const peaks = curve.map(v => (pk = Math.max(pk, v)));
  let dd = "";
  for (let i = 0; i < curve.length; i++) dd += (i === 0 ? "M" : "L") + X(i).toFixed(1) + "," + Y(peaks[i]).toFixed(1) + " ";
  for (let i = curve.length - 1; i >= 0; i--) dd += "L" + X(i).toFixed(1) + "," + Y(curve[i]).toFixed(1) + " ";
  const ddPath = `<path d="${dd}Z" fill="var(--down)" opacity="0.1" clip-path="url(#balrev)"/>`;
  return `<svg width="${w}" height="${height}" viewBox="0 0 ${w} ${height}" data-chart="bal" role="img" aria-label="Simulated equity curve"><defs><linearGradient id="balfill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c}" stop-opacity="0.16"/><stop offset="1" stop-color="${c}" stop-opacity="0.01"/></linearGradient><clipPath id="balrev" clipPathUnits="userSpaceOnUse"><rect class="chart-fill-reveal" x="${padL}" y="${padT}" width="${iw}" height="${ih}"/></clipPath></defs>${grid}<line x1="${padL}" x2="${padL + iw}" y1="${Y(start)}" y2="${Y(start)}" stroke="var(--border-strong)" stroke-width="1.5"/><text x="${padL + iw + 8}" y="${Y(start) - 4}" fill="var(--text-lo)" style="font:600 9.5px var(--mono)">start</text><path d="${line} L${X(curve.length - 1)},${Y(min)} L${X(0)},${Y(min)} Z" fill="url(#balfill)" clip-path="url(#balrev)"/>${ddPath}<path class="chart-line" d="${line}" fill="none" stroke="${c}" stroke-width="2" stroke-linejoin="round"/>${xlab}<g class="cx"></g></svg>`;
}

// Attach hover handlers to every chart with a data-chart attr. Called after each
// render (innerHTML replacement drops old listeners, so re-wiring is clean).
function wireCharts(rootEl) {
  if (!rootEl) return;
  rootEl.querySelectorAll("svg[data-chart]").forEach(svg => {
    const key = svg.getAttribute("data-chart");
    svg.addEventListener("mousemove", e => {
      const ch = CHARTS[key]; if (!ch) return;
      const rect = svg.getBoundingClientRect();
      const px = (e.clientX - rect.left) * (ch.W / rect.width);
      let best = 0, bd = 1e9;
      for (let i = 0; i < ch.n; i++) { const dd = Math.abs(ch.X(i) - px); if (dd < bd) { bd = dd; best = i; } }
      const ov = svg.querySelector(".cx"); if (ov) ov.innerHTML = ch.build(best);
    });
    svg.addEventListener("mouseleave", () => { const ov = svg.querySelector(".cx"); if (ov) ov.innerHTML = ""; });
  });
}

function edgeCell(edge) {
  const positive = edge >= 0;
  const w = Math.min(100, Math.abs(edge) / 0.4 * 100);
  return `<span class="edge-cell"><span class="${positive ? "pos" : "neg"}">${(edge >= 0 ? "+" : "−") + (Math.abs(edge) * 100).toFixed(0) + "%"}</span><span class="edge-bar"><span style="width:${w / 2}%;${positive ? "left" : "right"}:50%;background:${positive ? "var(--up)" : "var(--down)"}"></span></span></span>`;
}

// ====================================================================
// P&L SIM — ported VERBATIM from the former app.jsx so the V8 parity test
// (tests/test_sim_parity.py) keeps the JS and Python sims in lockstep.
// Do not reformat: the test slices [POST_INSIDE_FILL_RATE .. BTMetric].
// ====================================================================
const POST_INSIDE_FILL_RATE = 0.75;
// Deterministic [0,1) hash (FNV-1a) so the modeled fill outcome is stable
// across reruns — same trade always fills-or-misses identically.
function hashUnit(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return ((h >>> 0) % 100000) / 100000;
}
function kalshiFeeCents(entry, maker) {
  // Byte-mirror of dashboard/sim_python.py kalshi_fee_cents (parity-tested).
  // taker = 0.07·P·(1−P); maker (post-only/resting) = ¼ that rate (0.0175).
  if (entry <= 0 || entry >= 100) return 0;
  const p = entry / 100;
  const rate = maker ? 0.0175 : 0.07;
  return Math.max(1, Math.ceil(rate * p * (1 - p) * 100));
}
function kellyFraction(pWin, entry) {
  if (entry <= 0 || entry >= 100) return 0;
  const b = (100 - entry) / entry;
  return Math.max(0, pWin - (1 - pWin) / b);
}
function applyStakeCap(rawStake, balance, maxPct, maxDollars) {
  const pctCap = maxPct != null ? balance * maxPct : Infinity;
  const dolCap = maxDollars != null ? maxDollars : Infinity;
  return Math.min(rawStake, pctCap, dolCap);
}
function jsComputeSim(trades, params) {
  const { sizing, edgeFilter, minEntry, amountDollars, depthCap, execution,
          startingBankroll, kellyFraction: kf = 0.5, scalingPct = 0.05,
          strategy = "raw",
          maxSignals = 0,                            // 0 = no cap (legacy)
          edgeCap = 0,                               // 0 = no cap (legacy)
        } = params;
  const useBlend = strategy === "blend";
  const useUnion = strategy === "union";
  // For UNION: edgeFilter = raw threshold; blend threshold scales at 0.4×
  // (so 25% raw → 10% blend, matching live KORD config).
  const rawThreshold = edgeFilter;
  const blendThreshold = edgeFilter * 0.4;

  // RISK CONTROL B — anti-stacking (added 2026-06-10):
  // Pre-process trades to keep only top N signals per day (by |edge|). Mark
  // dropped trades so the trade table can show them as "anti-stacking".
  // Done as a Set lookup to keep the main loop's structure intact.
  let droppedByStacking = new Set();
  if (maxSignals > 0) {
    const byDate = {};
    for (const t of trades) {
      // Compute the same edge that the main loop would use, for stack-ranking.
      let edgeForRank;
      if (useUnion) {
        const r = Math.abs(t.modelP - t.mktP);
        const b = t.blendP != null ? Math.abs(t.blendP - t.mktP) : 0;
        edgeForRank = Math.max(r, b);
      } else if (useBlend && t.blendP != null) {
        edgeForRank = Math.abs(t.blendP - t.mktP);
      } else {
        edgeForRank = Math.abs(t.modelP - t.mktP);
      }
      // Only consider trades that would fire under the chosen strategy/edge
      // filter — otherwise we'd be ranking already-filtered noise.
      const fires = (useUnion
        ? (Math.abs(t.modelP - t.mktP) >= rawThreshold ||
           (t.blendP != null && Math.abs(t.blendP - t.mktP) >= blendThreshold))
        : edgeForRank >= edgeFilter);
      if (!fires) continue;
      (byDate[t.date] ||= []).push({ trade: t, edge: edgeForRank });
    }
    for (const dateStr in byDate) {
      const arr = byDate[dateStr];
      arr.sort((a, b) => b.edge - a.edge);          // desc by edge
      for (let i = maxSignals; i < arr.length; i++) {
        // Use a stable per-trade key — date + ticker is unique
        droppedByStacking.add(arr[i].trade.date + "|" + arr[i].trade.bracket);
      }
    }
  }

  let balance = startingBankroll;
  let peak = startingBankroll;
  let maxDD = 0;          // worst peak-to-trough as % of peak
  let maxDDDollars = 0;   // worst peak-to-trough in $ (negative)
  let nFiltered = 0, nFilled = 0, nWon = 0, nPending = 0, nTotal = 0, nMissed = 0;
  const pnls = [];
  const curve = [startingBankroll];
  // Per-trade computed records — drives Trade-by-trade detail table so qty/PnL
  // shown in the table match the active sim parameters exactly.
  const tradeRecords = [];
  for (const t of trades) {
    nTotal++;
    // STRATEGY: select edge + probability.
    //   raw    → use modelP, filter at edgeFilter
    //   blend  → use blendP (fallback modelP), filter at edgeFilter
    //   union  → fire if |raw_edge| ≥ rawThreshold OR |blend_edge| ≥ blendThreshold
    let pSel, edgeSel;
    if (useUnion) {
      const rawEdge = t.modelP - t.mktP;
      const blendEdge = (t.blendP != null) ? (t.blendP - t.mktP) : null;
      const rawFires = Math.abs(rawEdge) >= rawThreshold;
      const blendFires = (blendEdge != null) && (Math.abs(blendEdge) >= blendThreshold);
      if (!rawFires && !blendFires) {
        tradeRecords.push({ ...t, fill: "filtered", computedQty: 0, computedPnl: 0,
                            stratEdge: rawEdge, stratP: t.modelP, unionSource: "neither" });
        continue;
      }
      // When both fire (or only raw), use raw probability/edge.
      // When only blend fires, use blend.
      if (rawFires) {
        pSel = t.modelP; edgeSel = rawEdge;
      } else {
        pSel = t.blendP; edgeSel = blendEdge;
      }
    } else if (useBlend) {
      // Blend strategy: you can't run a blend before it's been fit. The
      // walk-forward fit sets blendP=null for trades before MIN_N_FIT prior
      // samples exist — skip those (don't silently fall back to raw, which
      // would overstate the blend strategy's trade count and returns).
      if (t.blendP == null) {
        tradeRecords.push({ ...t, fill: "no-blend", computedQty: 0, computedPnl: 0,
                            stratEdge: 0, stratP: t.modelP });
        continue;
      }
      pSel = t.blendP;
      edgeSel = pSel - t.mktP;
      if (Math.abs(edgeSel) < edgeFilter) {
        tradeRecords.push({ ...t, fill: "filtered", computedQty: 0, computedPnl: 0,
                            stratEdge: edgeSel, stratP: pSel });
        continue;
      }
    } else {
      // Raw strategy: always available (no fit needed).
      pSel = t.modelP;
      edgeSel = pSel - t.mktP;
      if (Math.abs(edgeSel) < edgeFilter) {
        tradeRecords.push({ ...t, fill: "filtered", computedQty: 0, computedPnl: 0,
                            stratEdge: edgeSel, stratP: pSel });
        continue;
      }
    }
    // For blend / union mode, recompute the side from sign of selected edge.
    // t.pos was the raw model's decision and may flip.
    const stratSide = edgeSel > 0 ? "BUY_YES" : "BUY_NO";
    const crossEntry = t.entry;
    if (crossEntry < minEntry) {
      tradeRecords.push({ ...t, fill: "below-min", computedQty: 0, computedPnl: 0,
                          stratEdge: edgeSel, stratP: pSel });
      continue;
    }
    // RISK CONTROL B — anti-stacking drop. Trade passed the edge filter but
    // there are higher-|edge| signals on the same day; we cap.
    if (maxSignals > 0 && droppedByStacking.has(t.date + "|" + t.bracket)) {
      tradeRecords.push({ ...t, fill: "anti-stack", computedQty: 0, computedPnl: 0,
                          stratEdge: edgeSel, stratP: pSel });
      continue;
    }
    if (t.won === null || t.won === undefined) {
      nPending++;
      tradeRecords.push({ ...t, fill: "pending", computedQty: 0, computedPnl: 0,
                          stratEdge: edgeSel, stratP: pSel });
      continue;
    }
    nFiltered++;
    // Execution: pick entry price.
    //   crossEntry = t.entry which is already the cross price (ask for BUY_YES,
    //   100−bid for BUY_NO) from paper_trades.
    //   - post_inside_spread: post a limit order 1¢ inside the bid-ask spread.
    //     Saves up to spread−1 cents; assumes 100% fill (optimistic).
    //   - market: just buy at the ask (cross the spread). No improvement.
    //   - market_plus_1: pay ask + 1¢. Slippage model for aggressive market
    //     orders that eat through thin top-of-book depth.
    //   - market_plus_2: ask + 2¢. Very aggressive.
    let entry = crossEntry;
    if (execution === "post_inside_spread") {
      const bid = t.marketYesBid, ask = t.marketYesAsk;
      if (bid != null && ask != null && ask > bid + 1) {
        entry = Math.max(1, crossEntry - (ask - bid - 1));
      }
    } else if (execution === "market_plus_1") {
      entry = Math.min(99, crossEntry + 1);
    } else if (execution === "market_plus_2") {
      entry = Math.min(99, crossEntry + 2);
    }
    // "market" mode is the default: entry = crossEntry already
    if (entry <= 0 || entry >= 100) {
      tradeRecords.push({ ...t, fill: "skipped", computedQty: 0, computedPnl: 0,
                          stratEdge: edgeSel, stratP: pSel });
      continue;
    }
    // REALISTIC FILL MODEL: a maker order posted inside the spread (entry below
    // the cross price) only fills ~POST_INSIDE_FILL_RATE of the time. Missed
    // fills = no position, no P&L (not free money). Deterministic per trade.
    // Only applies when we actually improved on the cross (entry < crossEntry);
    // if the spread was 1¢ there was no room to post inside, so it crosses and
    // fills. Taker modes never hit this branch.
    if (execution === "post_inside_spread" && entry < crossEntry &&
        hashUnit(t.date + "|" + t.bracket + "|" + t.side) >= POST_INSIDE_FILL_RATE) {
      nMissed++;
      tradeRecords.push({ ...t, fill: "missed", computedQty: 0, computedPnl: 0,
                          stratEdge: edgeSel, stratP: pSel });
      continue;
    }
    // Re-derive whether this trade WON given the strategy-determined side.
    // t.won was set against t.pos (raw model side); in blend mode the side
    // may flip, in which case the win/loss flips with it.
    const recordedSide = t.pos;   // "BUY_YES" or "BUY_NO"
    const sideFlipped = stratSide !== recordedSide;
    const won = sideFlipped ? !t.won : !!t.won;
    // Maker fee only when we rested strictly inside the cross (post_inside &
    // entry < crossEntry); same condition as the missed-fill model above.
    const isMaker = (execution === "post_inside_spread" && entry < crossEntry);
    const feePer = kalshiFeeCents(entry, isMaker) / 100;
    // RISK CONTROL C — edge cap for sizing. Edges above edgeCap get sized as
    // if they were edgeCap. Doesn't change which trades fire — only sizing.
    // Live config: 0.40 in both cities.
    const edgeScale = (edgeCap > 0)
      ? Math.min(1, edgeCap / Math.max(Math.abs(edgeSel), 0.01))
      : 1;
    let contracts, stakeDollars;
    if (sizing === "unit") {
      contracts = Math.floor(amountDollars * edgeScale);
      stakeDollars = contracts * entry / 100;
    } else if (sizing === "amount") {
      stakeDollars = amountDollars * edgeScale;
      contracts = Math.floor(stakeDollars / (entry / 100));
    } else if (sizing === "scaling") {
      const raw = balance * scalingPct * edgeScale;
      stakeDollars = applyStakeCap(raw, balance, null, null);
      contracts = Math.floor(stakeDollars / (entry / 100));
    } else { // kelly — uses STRATEGY-chosen probability
      const pWin = stratSide === "BUY_YES" ? pSel : (1 - pSel);
      const f = kellyFraction(pWin, entry) * kf;
      const raw = balance * f * edgeScale;
      stakeDollars = applyStakeCap(raw, balance, null, null);
      contracts = Math.floor(stakeDollars / (entry / 100));
    }
    if (depthCap && contracts > depthCap) contracts = depthCap;
    if (contracts < 1) {
      tradeRecords.push({ ...t, fill: "skipped", computedQty: 0, computedPnl: 0,
                          stratEdge: edgeSel, stratP: pSel });
      continue;
    }
    const totalFee = contracts * feePer;
    const grossPnl = contracts * (won ? (100 - entry) : -entry) / 100;
    const tradePnl = grossPnl - totalFee;
    pnls.push(tradePnl);
    balance += tradePnl;
    nFilled++;
    if (won) nWon++;
    peak = Math.max(peak, balance);
    const ddPct = (balance - peak) / peak * 100;
    if (ddPct < maxDD) { maxDD = ddPct; maxDDDollars = balance - peak; }
    curve.push(Math.round(balance * 100) / 100);
    tradeRecords.push({
      ...t,
      entry,                                              // post-spread-adjusted entry
      computedQty: contracts,
      computedPnl: Math.round(tradePnl * 100) / 100,
      fill: "filled",
      stratEdge: edgeSel,
      stratP: pSel,
      stratSide,
      stratWon: won,
    });
  }
  const ret = ((balance - startingBankroll) / startingBankroll) * 100;
  const win = nFilled ? nWon / nFilled : 0;
  let sharpe = 0;
  if (pnls.length > 1) {
    const m = pnls.reduce((s, x) => s + x, 0) / pnls.length;
    const v = pnls.reduce((s, x) => s + (x - m) ** 2, 0) / (pnls.length - 1);
    const sd = Math.sqrt(v);
    if (sd > 0) sharpe = (m / sd) * Math.sqrt(252);
  }
  return {
    final: Math.round(balance * 100) / 100,
    ret: Math.round(ret * 10) / 10,
    sharpe: Math.round(sharpe * 100) / 100,
    maxDD: Math.round(maxDD * 10) / 10,
    maxDDDollars: Math.round(maxDDDollars * 100) / 100,
    win: Math.round(win * 1000) / 1000,
    n: nFilled, filled: nFilled, pending: nPending, total: nTotal, missed: nMissed,
    avg: pnls.length ? Math.round((pnls.reduce((s, x) => s + x, 0) / pnls.length) * 100) / 100 : 0,
    curve,
    tradeRecords,
  };
}

// Find the best (strategy, edge) for a city's trades by sweeping the grid with
// the SAME sim the dashboard runs (so the auto-loaded config matches what's
// shown). Objective: highest annualized Sharpe among configs with >= MIN_TRADES
// filled — the trade floor avoids picking a tiny lucky high-edge slice. Uses
// unit-500 + market execution (the realistic defaults).
function findBestParams(trades) {
  if (!trades || !trades.length) return null;
  const MIN_TRADES = 15;
  const edges = [0.05, 0.07, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30];
  let best = null;
  for (const strategy of ["raw", "blend", "union"]) {
    for (const edge of edges) {
      const r = jsComputeSim(trades, {
        sizing: "unit", amountDollars: 500, edgeFilter: edge, minEntry: 0,
        depthCap: 0, execution: "market", startingBankroll: 3000,
        strategy, maxSignals: 0, edgeCap: 0,
      });
      if ((r.filled || 0) >= MIN_TRADES && (best === null || r.sharpe > best.sharpe)) {
        best = { strategy, edge, sharpe: r.sharpe, n: r.filled };
      }
    }
  }
  return best;   // null if no config cleared MIN_TRADES
}

// ====================================================================
// (parity-test slice boundary: the marker below ends the JS sim extract)
// ====================================================================
function BTMetric(label, value, sub, tone) {
  return `<div class="m"><div class="ml">${esc(label)}</div><div class="mv ${tone || ""}">${value}</div>${sub != null ? `<div class="ms">${esc(sub)}</div>` : ""}</div>`;
}

// ====================================================================
// STATE
// ====================================================================
let LIVE = null;
let prevLive = null;       // previous snapshot() result — animateLiveDeltas diffs it vs snapshot(d) directly (never re-snapshot)
let liveIntroDone = false; // gates the one-shot entrance ramp (rampClock) on first live paint
let BT = null;            // current city's backtest payload
let BT_CITIES = [];       // [{code,label,lat,lon}]
let activeTab = "live";
let liveTimer = null;
const autoedCities = new Set();
const bestByCity = {};    // code -> {strategy,edge,sharpe,n} | null (computed, no edge) | undefined (not yet)
const CHARTS = {};        // chart key -> {W,n,X,build(i)} for hover overlays
let btIntroDone = false;  // gates the one-shot first-open entrance ramp on the Backtest tab
const bt = {              // backtest control state
  cityCode: null, date: null,
  strategy: "raw",        // SIGNAL strategy — drives the bracket ladder + trade table
  simStrategy: null,      // PnL-SIM strategy — null = mirror the signal strategy until the user overrides it
  bracketEdge: 0.10, simEdge: 0.10, minEntry: 0,
  sizing: "unit", amount: 500, depth: 500, exec: "market",
  bankroll: 3000, maxSignals: 0, edgeCap: 0,
};

// ====================================================================
// LIVE TAB render functions
// ====================================================================
// Per-venue cash. Each venue answers for itself, so one unreachable gateway
// shows as an error row instead of blanking the panel — and the headline says
// "partial" so a total missing a venue can't read as the whole book.
function venueBalanceRows(d) {
  const vb = d.venueBalances;
  if (!vb) {
    return `<div class="vbal"><div class="vrow"><span class="pill-status venue K">K</span><span class="vn">Kalshi</span><span class="vt">${moneyPlain(d.balance)}</span><span class="vs">cash ${moneyPlain(d.cashBalance)}</span></div></div>`;
  }
  return `<div class="vbal">${vb.venues.map(v => `<div class="vrow${v.error ? " err" : ""}"><span class="pill-status venue ${esc(v.venue)}" title="${esc(VENUE_NAME[v.venue] || v.venue)}">${esc(v.venue)}</span><span class="vn">${esc(v.name)}</span><span class="vt">${v.total === null ? "—" : moneyPlain(v.total)}</span><span class="vs">${v.error ? esc(v.error) : (v.cash === null ? esc(v.note || "") : `${moneyPlain(v.cash)} free · ${moneyPlain(v.positions)} held`)}</span></div>`).join("")}</div>`;
}

function liveHero(d) {
  const t = d.today, c = d.cumulative;
  return `<div class="hero">
    <div>
      <div class="k">Today's P&amp;L</div>
      <div class="v ${cls(t.total)}" id="hero-today">${money(t.total)}</div>
      <div style="font:600 11px/1 var(--mono);color:var(--text-lo);text-transform:uppercase;letter-spacing:.06em;padding:6px 0 8px"><span>realized <b class="${cls(t.realized)}" id="hero-today-real">${money(t.realized)}</b></span><span>unrealized <b class="${cls(t.unrealized)}" id="hero-today-unreal">${money(t.unrealized)}</b></span><span><b>${t.trades}</b> trades · <b>${t.open}</b> open</span></div>
    </div>
    <div>
      <div class="k">Cumulative P&amp;L <span class="tag-pill">since first live trade</span></div>
      <div class="v ${cls(c.total)}" id="hero-cum">${money(c.total)}</div>
      <div style="font:600 11px/1 var(--mono);color:var(--text-lo);text-transform:uppercase;letter-spacing:.06em;padding:6px 0 8px"><span>return <b class="${cls(c.returnPct)}" id="hero-cum-ret">${pct(c.returnPct)}</b></span><span>win rate <b id="hero-winrate">${(c.winRate * 100).toFixed(0)}%</b></span><span><b>${c.nSettled}</b> settled</span></div>
      <div class="spark">${sparkSVG(d.series)}</div>
    </div>
    <div>
      <div class="k">Account balance <span class="tag-pill">${(d.venueBalances && d.venueBalances.complete === false) ? "partial" : "all venues"}</span></div>
      <div class="v sm" id="hero-balance" style="color:var(--text-hi)">${moneyPlain(d.venueBalances ? d.venueBalances.total : d.balance)}</div>
      ${venueBalanceRows(d)}
      ${d.reconcile ? `<div class="sub recon" title="Verified 2026-06-21: deposits + settled trading P&amp;L + referral credit = account equity (when flat)"><span>${moneyPlain(d.reconcile.deposits)} dep</span><span>${money(d.reconcile.realized)} P&amp;L</span><span>${money(d.reconcile.credit)} ref</span><span class="eq">= ${moneyPlain(d.reconcile.reconciledEquity)}</span></div>` : ""}
    </div>
  </div>`;
}

function formatCountdown(d) {
  if (!d || !d.nextCron || d.nextCron.inMin == null) return "—";
  const elapsed = (Date.now() - (d._loadedAt || Date.now())) / 1000;
  const total = Math.max(0, d.nextCron.inMin * 60 - elapsed);
  const m = Math.floor(total / 60), s = Math.floor(total % 60);
  return m + "m " + String(s).padStart(2, "0") + "s";
}

// Feed freshness (not just connectivity): a connected WS whose marks stopped
// updating is STALE and must not read as healthy green on a real-money feed.
function liveFeedState(lv) {
  lv = lv || {};
  const ageS = lv.ageMs != null ? Math.round(lv.ageMs / 1000) : null;
  if (!lv.connected)              return { ico: "warn", dot: "stale", tag: "",      ageS };
  if (ageS != null && ageS > 600) return { ico: "err",  dot: "dead",  tag: "dead",  ageS };
  if (ageS != null && ageS > 120) return { ico: "warn", dot: "stale", tag: "stale", ageS };
  return { ico: "ok", dot: "live", tag: "", ageS };
}

function statusStrip(d) {
  const killOk = d.killArmed;
  const liveCities = d.cities.filter(c => c.status === "active").length;
  const lv = d.live || {};
  const src = lv.source || "—";
  // Live-feed chip freshness mirrors the topbar dot (liveFeedState): connected
  // but stale marks show amber/red, never healthy green.
  const fs = liveFeedState(lv);
  const srcIco = fs.ico;
  return `<div class="status-strip">
    <div class="chip"><span class="ico ${killOk ? "ok" : "err"}"></span><span class="txt"><span class="l">Kill switch</span><span class="d" style="color:${killOk ? "var(--up)" : "var(--down)"}">${killOk ? "ARMED" : "TRIGGERED"}</span></span></div>
    <div class="chip"><span class="ico ${d.nextCron.inMin === null ? "err" : "ok"}"></span><span class="txt"><span class="l">Next cron · ${esc(d.nextCron.label)}</span><span class="d">${esc(d.nextCron.at)} ${d.nextCron.inMin !== null ? `<small>· in <span id="cron-countdown">${formatCountdown(d)}</span></small>` : ""}</span></span></div>
    <div class="chip"><span class="ico ${d.openOrders.count > 0 ? "ok" : ""}"></span><span class="txt"><span class="l">Open orders</span><span class="d">${d.openOrders.count} resting <small>· ${d.openOrders.contracts.toLocaleString()} contracts</small></span></span></div>
    <div class="chip"><span class="ico ${d.hrrr.status === "ok" ? "ok" : "warn"}"></span><span class="txt"><span class="l">HRRR data</span><span class="d" style="color:${d.hrrr.status === "ok" ? "var(--text-hi)" : "var(--warn)"}">${d.hrrr.status === "ok" ? "fresh" : "stale"} <small>· ${esc(d.hrrr.age)} ago</small></span></span></div>
    <div class="chip"><span class="ico ok"></span><span class="txt"><span class="l">Positions</span><span class="d">${d.positions.length} open <small>· ${liveCities}/${d.cities.length} cities live</small></span></span></div>
    <div class="chip"><span class="ico ${srcIco}"></span><span class="txt"><span class="l">Live feed</span><span class="d">${esc(src)}<small>${lv.marks != null ? ` · ${lv.marks} marks` : ""}${fs.tag ? ` · <span style="color:${fs.dot === "dead" ? "var(--down)" : "var(--warn)"}">${fs.tag}</span>` : ""}</small></span></span></div>
  </div>`;
}

function killBanner(d) {
  if (d.killArmed) return "";
  return `<div class="alert"><span class="bang">⛔</span><div class="body"><div class="t">Kill switch triggered — all trading halted</div><div class="d">${esc(d.killReason || "Cumulative drawdown breached the aggregate kill threshold.")}</div></div><span class="ts">${esc(d.asOf || "")}</span></div>`;
}

function riskBar(name, used, limit) {
  const r = Math.min(1, limit ? used / limit : 0);
  const lvl = r >= 0.8 ? "err" : r >= 0.5 ? "warn" : "ok";
  return `<div class="riskrow"><div class="rl"><span class="name">${esc(name)}</span><span class="val">$${used.toFixed(0)} <span style="color:var(--text-faint)">/ $${limit.toFixed(0)}</span></span></div><div class="bar"><span class="${lvl}" style="transform:scaleX(${r.toFixed(3)})"></span></div></div>`;
}

function dialHTML(used, limit) {
  const r = Math.min(1, limit ? used / limit : 0);
  const pctv = Math.round(r * 100);
  const col = r >= 0.8 ? "var(--extreme)" : r >= 0.5 ? "var(--warm)" : "var(--temperate)";
  return `<span class="dial" title="${pctv}% of cumulative kill used" style="background:conic-gradient(${col} ${pctv}%, var(--bg-3) 0)"><span class="inner">${pctv}%</span></span>`;
}

// Venue tag for the multi-venue live tables. K = Kalshi, PM = Polymarket,
// FX = ForecastEx (via IBKR). Rows without one predate the union and read as K.
const VENUE_NAME = { K: "Kalshi", PM: "Polymarket", FX: "ForecastEx (IBKR)" };
function venueCell(v) {
  v = v || "K";
  return `<td><span class="pill-status venue ${esc(v)}" title="${esc(VENUE_NAME[v] || v)}">${esc(v)}</span></td>`;
}
function venueMeta(rows) {
  const n = {};
  rows.forEach(r => { const v = r.venue || "K"; n[v] = (n[v] || 0) + 1; });
  return Object.keys(n).map(v => `${n[v]} ${v}`).join(" · ") || "none";
}

function cityCard(c) {
  return `<div class="panel city">
    <div class="ch"><span class="nm">${esc(c.name)}</span><span class="pill-status venue ${esc(c.venue || "K")}" title="${esc(VENUE_NAME[c.venue] || "Kalshi")}">${esc(c.venue || "K")}</span><span class="code">${esc(c.code)}</span><span class="badge ${c.status === "active" ? "active" : "halted"}">${esc(c.status)}</span>${dialHTML(c.risk.cumUsed, c.risk.cumKill)}<span class="model" title="${esc(c.model)}">${esc(c.model)}</span></div>
    <div class="cbody">
      <div class="m"><div class="ml">Realized</div><div class="mv ${cls(c.realized)}">${money(c.realized)}</div><div class="ms">settled</div></div>
      <div class="m"><div class="ml">Unrealized</div><div class="mv ${cls(c.unrealized)}">${money(c.unrealized)}</div><div class="ms">open mark</div></div>
      <div class="m"><div class="ml">Today</div><div class="mv ${cls(c.today)}">${money(c.today)}</div><div class="ms">${c.orders} orders</div></div>
    </div>
    <div class="cfoot">${c.haltNote ? `<div class="halt-note">${esc(c.haltNote)}</div>` : `<div class="activity"><span>budget <b>$${c.budget}</b></span><span><b>${c.contracts.toLocaleString()}</b> contracts</span><span>edge ≥ <b>${esc(c.edgeThresh)}</b></span><span>size <b>${esc(c.stake)}</b></span></div>`}${riskBar("Cumulative", c.risk.cumUsed, c.risk.cumKill)}${riskBar(c.risk.todayLabel || "Today", c.risk.todayUsed, c.risk.todayKill)}</div>
  </div>`;
}

function otherCitiesCard(c) {
  return `<div class="panel city other">
    <div class="ch"><span class="nm">${esc(c.name)}</span><span class="code">${esc(c.code)}</span><span class="badge other">manual</span><span class="model">${esc(c.model)}</span></div>
    <div class="cbody">
      <div class="m"><div class="ml">Realized</div><div class="mv ${cls(c.realized)}">${money(c.realized)}</div><div class="ms">settled</div></div>
      <div class="m"><div class="ml">Unrealized</div><div class="mv ${cls(c.unrealized)}">${money(c.unrealized)}</div><div class="ms">open mark</div></div>
      <div class="m"><div class="ml">Today</div><div class="mv ${cls(c.today)}">${money(c.today)}</div><div class="ms">${c.n} settled</div></div>
    </div>
    <div class="cfoot"><div class="activity"><span>includes <b>${esc(c.sub)}</b></span></div></div>
  </div>`;
}

function aggRisk(d) {
  const a = d.agg;
  const cumUsed = a.cumPnl < 0 ? Math.abs(a.cumPnl) : 0;
  const todayUsed = a.todayPnl < 0 ? Math.abs(a.todayPnl) : 0;
  const lvl = (u, k) => (k && u / k >= 0.8) ? "err" : (k && u / k >= 0.5) ? "warn" : "ok";
  return `<div class="panel" style="display:flex;flex-direction:column"><div class="panel-h"><h3>Aggregate risk envelope</h3><span class="meta">cross-city</span></div>
    <div class="panel-b aggm" style="flex:1">
      <div class="a"><div class="top"><span class="lbl">Cumulative drawdown</span><span class="num ${cls(a.cumPnl)}">${money(a.cumPnl)}</span></div><div class="bar"><span class="${lvl(cumUsed, a.cumKill)}" style="transform:scaleX(${(a.cumKill ? Math.min(1, cumUsed / a.cumKill) : 0).toFixed(3)})"></span></div><span class="cap">kill at −$${a.cumKill} · ${(a.cumKill ? cumUsed / a.cumKill * 100 : 0).toFixed(0)}% used</span></div>
      <div class="a"><div class="top"><span class="lbl">Daily loss</span><span class="num ${cls(a.todayPnl)}">${money(a.todayPnl)}</span></div><div class="bar"><span class="${lvl(todayUsed, a.dailyKill)}" style="transform:scaleX(${(a.dailyKill ? Math.min(1, todayUsed / a.dailyKill) : 0).toFixed(3)})"></span></div><span class="cap">halt at −$${a.dailyKill} · ${(a.dailyKill ? todayUsed / a.dailyKill * 100 : 0).toFixed(0)}% used</span></div>
      <div class="a"><div class="top"><span class="lbl">Open contracts</span><span class="num">${a.openContracts.toLocaleString()}</span></div><div class="bar"><span class="ok" style="transform:scaleX(${(a.contractCap ? Math.min(1, a.openContracts / a.contractCap) : 0).toFixed(3)})"></span></div><span class="cap">cap ${a.contractCap.toLocaleString()} (sum of city caps)</span></div>
    </div>
  </div>`;
}

function positionsTable(rows) {
  const body = rows.length === 0
    ? `<tr><td class="l muted" colspan="8" style="padding:20px 12px">No open positions — all flat.</td></tr>`
    : rows.map(r => `<tr data-pos-ticker="${esc(r.ticker)}"><td class="l hi">${esc(r.ticker)}</td><td class="l">${esc(r.bracket)}</td><td><span class="side ${r.side === "YES" ? "yes" : "no"}">${esc(r.side)}</span></td><td>${r.qty}</td><td>${r.avg}¢</td><td class="hi" data-mark-ticker="${esc(r.ticker)}">${r.mark}¢${r.live ? ` <span class="live-dot" title="live WS mark">●</span>` : ""}</td><td class="${cls(r.unreal)}">${money(r.unreal)}</td><td class="${cls(r.unreal)}">${pct(r.unrealPct)}</td></tr>`).join("");
  const liveN = rows.filter(r => r.live).length;
  return `<div class="panel"><div class="panel-h"><h3>Current positions</h3><span class="meta">mark = side-adjusted bid · ${rows.length} open${liveN ? ` · ${liveN} live ●` : ""}</span></div><div class="tbl-scroll" data-scroll-key="positions"><table class="dt"><thead><tr><th class="l">Ticker</th><th class="l">Bracket</th><th>Side</th><th>Qty</th><th>Avg</th><th>Mark</th><th>Unreal</th><th>%</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
}

function signalsTable(rows) {
  const body = rows.length === 0
    ? `<tr><td class="l muted" colspan="10" style="padding:18px 12px">No signals logged today.</td></tr>`
    : rows.map(r => `<tr>${venueCell(r.venue)}<td class="l hi">${esc(r.ticker)}</td><td class="l">${esc(r.bracket)}</td><td>${(r.modelP * 100).toFixed(0)}%</td><td>${(r.mktP * 100).toFixed(0)}%</td><td>${edgeCell(r.edge)}</td><td><span class="side ${r.side === "YES" ? "yes" : "no"}">BUY ${esc(r.side)}</span></td><td><span class="pill-status ${r.placed === "placed" ? "placed" : "skipped"}">${esc(r.placed)}</span></td><td><span class="pill-status ${esc(r.fill)}">${esc(r.fill)}</span></td><td class="${r.pnl === null ? "muted" : cls(r.pnl)}">${r.pnl === null ? "—" : money(r.pnl)}</td></tr>`).join("");
  return `<div class="panel"><div class="panel-h"><h3>Today's signals → fills</h3><span class="meta">all venues · ${venueMeta(rows)}</span></div><div class="tbl-scroll" data-scroll-key="signals"><table class="dt"><thead><tr><th>Venue</th><th class="l">Ticker</th><th class="l">Bracket</th><th>Model P</th><th>Market P</th><th>Edge</th><th>Signal</th><th>Order</th><th>Fill</th><th>P&amp;L</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
}

function ordersTable(rows) {
  const body = rows.length === 0
    ? `<tr><td class="l muted" colspan="8" style="padding:18px 12px">No orders placed today.</td></tr>`
    : rows.map(r => `<tr>${venueCell(r.venue)}<td class="l">${esc(r.time)}</td><td class="l hi">${esc(r.ticker)}</td><td><span class="side ${r.side === "YES" ? "yes" : "no"}">${esc(r.side)}</span></td><td>${r.qty}</td><td>${r.limit}¢</td><td class="hi">${r.fillPx === null ? "—" : r.fillPx + "¢"}</td><td><span class="pill-status ${esc(r.status)}">${esc(r.status)}</span></td></tr>`).join("");
  return `<div class="panel"><div class="panel-h"><h3>Today's live orders</h3><span class="meta">${venueMeta(rows)}</span></div><div class="tbl-scroll" style="max-height:240px" data-scroll-key="orders"><table class="dt"><thead><tr><th>Venue</th><th class="l">Time</th><th class="l">Ticker</th><th>Side</th><th>Qty</th><th>Limit</th><th>Fill</th><th>Status</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
}

function openOrders(rows) {
  const body = rows.length === 0
    ? `<tr><td class="l muted" colspan="6" style="padding:16px 12px">No resting orders.</td></tr>`
    : rows.map(r => `<tr>${venueCell(r.venue)}<td class="l hi">${esc(r.ticker)}</td><td><span class="side ${r.side === "YES" ? "yes" : "no"}">${esc(r.side)}</span></td><td>${r.qty}</td><td>${r.limit}¢</td><td class="muted">${esc(r.age)}</td></tr>`).join("");
  return `<div class="panel"><div class="panel-h"><h3>Working orders</h3><span class="meta" title="Kalshi is polled live; PM/FX are inferred from the DB (unfilled + unsettled)">${venueMeta(rows)}</span></div><div class="tbl-scroll" style="max-height:200px" data-scroll-key="openorders"><table class="dt"><thead><tr><th>Venue</th><th class="l">Ticker</th><th>Side</th><th>Qty</th><th>Limit</th><th>Age</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
}

function recentFills(rows) {
  const body = rows.length === 0
    ? `<tr><td class="l muted" colspan="7" style="padding:16px 12px">No fills in the last 7 days.</td></tr>`
    : rows.map(r => `<tr>${venueCell(r.venue)}<td class="l">${esc(r.date)}</td><td class="l hi">${esc(r.ticker)}</td><td><span class="side ${r.side === "YES" ? "yes" : "no"}">${esc(r.side)}</span></td><td>${r.qty}</td><td>${r.px}¢</td><td class="${r.pnl === null ? "muted" : cls(r.pnl)}">${r.pnl === null ? "open" : money(r.pnl)}</td></tr>`).join("");
  return `<div class="panel"><div class="panel-h"><h3>Recent fills (7 days)</h3><span class="meta">${venueMeta(rows)}</span></div><div class="tbl-scroll" style="max-height:200px" data-scroll-key="fills"><table class="dt"><thead><tr><th>Venue</th><th class="l">Date</th><th class="l">Ticker</th><th>Side</th><th>Qty</th><th>Px</th><th>Settled P&amp;L</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
}

function cronAlerts(d) {
  const dot = s => s === "ok" ? "var(--up)" : s === "error" ? "var(--down)" : "var(--warn)";
  const crons = d.crons.map(c => `<div style="display:flex;align-items:center;gap:10px"><span style="width:8px;height:8px;border-radius:50%;background:${dot(c.status)};flex:none"></span><span class="mono" style="font-size:12px;color:var(--text-hi);min-width:104px">${esc(c.name)}</span><span class="mono" style="font-size:11px;color:var(--text-lo)">${esc(c.last)}</span><span class="mono" style="font-size:11px;color:var(--text-faint);margin-left:auto">${esc(c.desc)}</span></div>`).join("");
  const alerts = d.alerts.map(a => `<div class="logline ${esc(a.lvl)}" style="display:flex;gap:9px"><span class="tt">${esc(a.ts)}</span><span style="color:${a.lvl === "err" ? "var(--down)" : a.lvl === "warn" ? "var(--warn)" : "var(--text-mid)"}">${esc(a.msg)}</span></div>`).join("");
  return `<div class="panel"><div class="panel-h"><h3>Cron health &amp; alerts</h3><span class="meta">${d.crons.length} daily jobs</span></div><div class="panel-b" style="display:grid;grid-template-columns:1fr 1fr;gap:18px"><div style="display:flex;flex-direction:column;gap:9px">${crons}</div><div style="border-left:1px solid var(--border);padding-left:18px;display:flex;flex-direction:column;gap:8px">${alerts}</div></div></div>`;
}

function paramsExpander(d) {
  const cities = d.cities.map(c => `<div>— <b style="color:var(--text-hi)">${esc(c.name)}</b> (${esc(c.code)}) — edge ≥ ${esc(c.edgeThresh)}, size ${esc(c.stake)}, daily $${c.risk.todayKill}, cumulative $${c.risk.cumKill}</div>`).join("");
  return `<details class="params"><summary data-focus-key="params-summary">Strategy parameters in effect (live from live_trade.py)</summary><div class="pbody"><div><b style="color:var(--text-hi)">Filter:</b> |edge| ≥ per-city threshold, no entry-price floor · <b style="color:var(--text-hi)">Execution:</b> <code>post_inside_spread</code></div><div><b style="color:var(--text-hi)">Aggregate kills:</b> daily loss −$${d.agg.dailyKill}, cumulative drawdown −$${d.agg.cumKill}, 4wk avg spread &gt; 5¢</div><div style="margin-top:6px">${cities}</div><div style="margin-top:8px">Halt files: <code>touch halt/KORD</code> <code>touch halt/KMIA</code> <code>touch halt/ALL</code></div></div></details>`;
}

function renderLive() {
  const root = document.getElementById("live-root");
  if (!LIVE) { root.innerHTML = `<div class="loading">Loading live data…</div>`; return; }
  const d = LIVE;
  // Preserve interaction state across the 2s poll rebuild: table scroll positions,
  // the params disclosure open/closed, and keyboard focus. Without this the
  // innerHTML swap resets scroll, snaps the params panel shut, and ejects a
  // keyboard user's focus every poll.
  const scrollState = {};
  root.querySelectorAll(".tbl-scroll[data-scroll-key]").forEach(el => { scrollState[el.dataset.scrollKey] = el.scrollTop; });
  const _pd = root.querySelector("details.params");
  const paramsOpen = _pd ? _pd.open : false;
  const _active = document.activeElement;
  const focusKey = (_active && root.contains(_active)) ? _active.getAttribute("data-focus-key") : null;
  root.innerHTML =
    killBanner(d) + liveHero(d) + statusStrip(d) +
    `<div class="section-label">Per-city · realized + unrealized + risk</div>` +
    // breakpoint-free auto-fit row: any count of cards (N cities + optional Other
    // Cities + the aggregate-risk card) wraps, instead of a .g-N that only exists
    // for 2-5 and collapsed 6+ (4 cities + Other + agg) to a single column.
    `<div class="city-grid">${d.cities.map(cityCard).join("")}${d.otherCities ? otherCitiesCard(d.otherCities) : ""}${aggRisk(d)}</div>` +
    `<div class="grid" style="grid-template-columns:1.45fr 1fr">` +
      `<div class="panel"><div class="panel-h"><h3>Cumulative P&amp;L</h3><span class="meta">realized · rolling since first live trade</span></div><div style="padding:10px 12px 4px"><div class="chart-wrap">${pnlChartSVG(d.series)}</div></div><div class="panel-b" style="padding-top:0"><div class="chart-legend"><span><span class="sw" style="background:${d.cumulative.total >= 0 ? "var(--up)" : "var(--down)"}"></span>cumulative realized P&amp;L · right axis</span></div></div></div>` +
      positionsTable(d.positions) +
    `</div>` +
    signalsTable(d.signals) +
    `<div class="grid g-2">${ordersTable(d.orders)}<div class="grid" style="grid-template-rows:auto auto;gap:14px">${openOrders(d.openOrdersTbl)}${recentFills(d.fills)}</div></div>` +
    cronAlerts(d) + paramsExpander(d);
  // restore preserved interaction state onto the freshly-built DOM
  root.querySelectorAll(".tbl-scroll[data-scroll-key]").forEach(el => { const v = scrollState[el.dataset.scrollKey]; if (v) el.scrollTop = v; });
  if (paramsOpen) { const pd2 = root.querySelector("details.params"); if (pd2) pd2.open = true; }
  if (focusKey) { const fel = root.querySelector('[data-focus-key="' + focusKey + '"]'); if (fel) fel.focus(); }
  wireCharts(root);
  animateLiveDeltas(d);
}

// ====================================================================
// DIFF-DRIVEN LIVE MOTION — called at the END of renderLive (one call).
// FIRST paint: one rampClock drives every hero number 0→target AND the P&L
// chart draw-on, so they land on the same frame (the entrance "moment").
// EVERY poll after: only values that actually moved tween prev→new (TICK_MS)
// and get a bg-tint flash; unchanged numbers never animate (no twitch).
// prevLive holds the previous snapshot(); RM/hidden → instant, values still set.
// ====================================================================
const HERO_FIELDS = [
  { id: "hero-today",        key: "todayTotal",      fmt: money },
  { id: "hero-today-real",   key: "todayRealized",   fmt: money },
  { id: "hero-today-unreal", key: "todayUnrealized", fmt: money },
  { id: "hero-cum",          key: "cumTotal",        fmt: money },
  { id: "hero-cum-ret",      key: "cumReturn",       fmt: pct },              // server % — never /3050
  { id: "hero-winrate",      key: "winRate",         fmt: v => (v * 100).toFixed(0) + "%" },
  { id: "hero-balance",      key: "balance",         fmt: moneyPlain },
];

// WAAPI background flash; tints mirror --flash-tint-pos/neg (rgba @0.22) inlined,
// since var() doesn't resolve inside element.animate() keyframes. Skipped under RM.
function flashValue(el, up) {
  if (!el || RM.matches) return;
  const rgb = up ? "47,208,138" : "244,71,107";
  el.animate(
    [{ backgroundColor: `rgba(${rgb},0.22)` }, { backgroundColor: `rgba(${rgb},0)` }],
    { duration: 600, easing: "cubic-bezier(.22,1,.36,1)" }
  );
}

function animateLiveDeltas(d) {
  const root = document.getElementById("live-root");
  if (!root) return;
  const snap = snapshot(d);

  // ---- FIRST PAINT: synchronized entrance moment ----
  if (!liveIntroDone) {
    root.classList.add("intro");                                   // E1 staggered rise reveal
    const tgs = HERO_FIELDS
      .map(h => ({ el: document.getElementById(h.id), to: snap[h.key], fmt: h.fmt }))
      .filter(x => x.el && x.to != null);
    tgs.forEach(x => { x.el.textContent = x.fmt(0); });            // seed 0 → no flash of final value
    const svg  = root.querySelector('svg[data-chart="pnl"]');
    const line = svg && svg.querySelector(".chart-line");
    const fill = svg && svg.querySelector(".chart-fill-reveal");
    let len = 0;
    if (line) { len = line.getTotalLength(); line.style.strokeDasharray = len; }
    rampClock(LOAD_MS, easeOutExpo,
      e => {
        tgs.forEach(x => { x.el.textContent = x.fmt(x.to * e); });
        if (line) line.style.strokeDashoffset = len * (1 - e);
        if (fill) fill.style.transform = "scaleX(" + e + ")";
      },
      () => {
        tgs.forEach(x => { x.el.textContent = x.fmt(x.to); });     // pin exact targets
        if (line) line.style.strokeDashoffset = 0;
        if (fill) fill.style.transform = "scaleX(1)";
      });
    liveIntroDone = true;
    prevLive = snap;
    return;
  }

  // ---- SUBSEQUENT POLLS ----
  root.classList.remove("intro");                                  // before paint → reveal never re-fires
  if (RM.matches || document.hidden) { prevLive = snap; return; }

  // hero numbers: tween + flash ONLY the ones that moved (|Δ| ≥ 0.01)
  HERO_FIELDS.forEach(h => {
    const el = document.getElementById(h.id);
    const nv = snap[h.key], ov = prevLive ? prevLive[h.key] : null;
    if (!el || nv == null || ov == null || Math.abs(nv - ov) < 0.01) return;
    countUp(el, ov, nv, h.fmt, "update");
    flashValue(el, nv >= ov);
  });

  // positions: flash the mark CELL on a WS mark move; row-enter for new tickers
  const pMarks = (prevLive && prevLive.marks) ? prevLive.marks : null;
  (d.positions || []).forEach(p => {
    const nv = snap.marks[p.ticker];
    const ov = pMarks ? pMarks[p.ticker] : undefined;
    if (ov === undefined) {                                        // ticker new this poll
      if (pMarks) {
        const tr = root.querySelector('tr[data-pos-ticker="' + p.ticker + '"]');
        if (tr) tr.animate(
          [{ opacity: 0, transform: "translateY(-6px)" }, { opacity: 1, transform: "none" }],
          { duration: 360, easing: "cubic-bezier(.22,1,.36,1)" });
      }
      return;
    }
    if (nv == null || nv === ov) return;
    const td = root.querySelector('td[data-mark-ticker="' + p.ticker + '"]');
    if (td) flashValue(td, nv >= ov);
  });

  prevLive = snap;
}

// ====================================================================
// CITY BEST-SHARPE — the one useful signal carried over from the retired US
// map: a city "warms up" on the thermal ramp as its best backtest finds edge.
// Drives the inline best-Sharpe stat next to the city selector.
// undefined (not computed yet) / null (too few trades) → muted steel.
// ====================================================================
function btSharpeColor(best) {
  if (!best) return "var(--text-lo)";
  const s = best.sharpe;
  // Quality scale (green=good … red=negative), NOT the thermal ramp — temperature
  // color stays reserved for °F so a strong Sharpe never reads as loss-red.
  return s >= 2.5 ? "var(--up)"        // clears the deploy bar
       : s >= 1.5 ? "var(--temperate)" // strong
       : s >= 0.8 ? "var(--warn)"      // marginal
       : s >= 0   ? "var(--text-mid)"  // weak
       :            "var(--down)";     // negative
}
// Inline best-Sharpe stat shown beside the city selector (replaces the map's
// per-city Sharpe coloring). bestByCity[code] is seeded by recordBest() on load.
function bestSharpeStat(code) {
  const best = bestByCity[code];
  if (best === undefined) return `<span class="bt-best"><span class="bt-best-k">best Sharpe</span><span class="bt-best-v muted">·</span></span>`;
  if (best === null) return `<span class="bt-best"><span class="bt-best-k">best Sharpe</span><span class="bt-best-v muted" title="too few trades to score">n/a</span></span>`;
  const col = btSharpeColor(best);
  const tip = `best Sharpe ${best.sharpe.toFixed(2)} · ${best.strategy} ≥ ${(best.edge * 100).toFixed(0)}% · n=${best.n} (trailing 365d, as of today)`;
  return `<span class="bt-best" title="${esc(tip)}"><span class="bt-best-k">best Sharpe</span><span class="bt-best-dot" style="background:${col};box-shadow:0 0 8px ${col}"></span><span class="bt-best-v mono" style="color:${col}">${best.sharpe.toFixed(2)}</span><span class="bt-best-s">${esc(best.strategy)} ≥${(best.edge * 100).toFixed(0)}%</span></span>`;
}

// ====================================================================
// BACKTEST TAB render functions
// ====================================================================
// COMPACT RUN BAR — the "what am I looking at" context: city (+ its best-Sharpe
// stat, carried over from the retired map), target date, the SIGNAL strategy
// (drives the bracket ladder + trade table), and the ladder edge threshold.
function controlsBar(d) {
  const blendAvailable = !!d.blend;
  const cityOpts = BT_CITIES.map(c => `<option value="${esc(c.code)}" ${c.code === bt.cityCode ? "selected" : ""}>${esc(c.label)} · ${esc(c.code)}</option>`).join("");
  const edgeOpts = [0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70].map(v => `<option value="${v}" ${Math.abs(v - bt.bracketEdge) < 1e-9 ? "selected" : ""}>≥ ${(v * 100).toFixed(0)}%</option>`).join("");
  const strat = (id, label) => {
    const dis = id !== "raw" && !blendAvailable;
    return `<button class="${bt.strategy === id ? "on" : ""}" ${dis ? `disabled title="no blend model for this city"` : `onclick="btSetStrategy('${id}')"`}>${label}</button>`;
  };
  return `<div class="panel"><div class="controls bt-runbar">
    <div class="ctrl"><span class="cl">City</span><div class="city-row"><select onchange="btSelectCity(this.value)">${cityOpts}</select>${bestSharpeStat(bt.cityCode)}</div></div>
    <div class="ctrl"><span class="cl">Target date</span><input type="date" value="${esc(bt.date || "")}" onchange="btSelectDate(this.value)"></div>
    <div class="ctrl"><span class="cl" title="Raw model P, Benter blend, or their union — drives the bracket ladder + trade table below">Signal strategy</span><div class="seg">${strat("raw", "Raw")}${strat("blend", "Blend")}${strat("union", "Union")}</div></div>
    <div class="ctrl"><span class="cl" title="A bracket fires when |model − market| clears this">Ladder edge</span><select onchange="btSetBracketEdge(this.value)">${edgeOpts}</select></div>
  </div></div>`;
}

// SIM RUN PARAMETERS — the daily-touched controls stay inline; the rare filters
// (min entry, max signals/day, edge cap, depth cap) tuck behind an Advanced
// disclosure that auto-opens if any of them is set off its default.
function simControls() {
  const sizeBtns = ["unit", "amount", "kelly", "scaling"].map(s => `<button class="${bt.sizing === s ? "on" : ""}" onclick="btSetSizing('${s}')">${s}</button>`).join("");
  const simEdgeOpts = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70].map(v => `<option value="${v}" ${Math.abs(v - bt.simEdge) < 1e-9 ? "selected" : ""}>≥ ${(v * 100).toFixed(0)}%</option>`).join("");
  const minEntryOpts = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80].map(v => `<option value="${v}" ${v === bt.minEntry ? "selected" : ""}>${v === 0 ? "any" : "≥ " + v + "¢"}</option>`).join("");
  const maxSigOpts = [[0, "no cap"], [1, "1 (KMIA live)"], [2, "2 (KORD live)"], [3, "3"], [4, "4"]].map(([v, l]) => `<option value="${v}" ${v === bt.maxSignals ? "selected" : ""}>${l}</option>`).join("");
  const edgeCapOpts = [[0, "no cap"], [0.30, "≥ 30%"], [0.40, "≥ 40% (live)"], [0.50, "≥ 50%"], [0.60, "≥ 60%"]].map(([v, l]) => `<option value="${v}" ${Math.abs(v - bt.edgeCap) < 1e-9 ? "selected" : ""}>${l}</option>`).join("");
  const execOpts = [["market", "market — cross spread, 100% fill"], ["post_inside_spread", "post_inside_spread — 1¢ inside, ~75% fill"], ["market_plus_1", "market_plus_1 — ask + 1¢"], ["market_plus_2", "market_plus_2 — ask + 2¢"]].map(([v, l]) => `<option value="${v}" ${v === bt.exec ? "selected" : ""}>${l}</option>`).join("");
  const amtLabel = bt.sizing === "unit" ? "Contracts" : bt.sizing === "amount" ? "$ / trade" : "% bankroll";
  const amtStep = bt.sizing === "unit" ? "50" : bt.sizing === "amount" ? "5" : "1";
  const advSet = bt.minEntry || bt.maxSignals || bt.edgeCap || Number(bt.depth) !== 500;
  return `<div class="controls sim-controls">
    <div class="ctrl"><span class="cl">Sizing</span><div class="seg">${sizeBtns}</div></div>
    <div class="ctrl"><span class="cl">${amtLabel}</span><input type="number" value="${bt.amount}" step="${amtStep}" onchange="btSetAmount(this.value)"></div>
    <div class="ctrl"><span class="cl">Bankroll</span><input type="number" value="${bt.bankroll}" step="100" min="100" onchange="btSetBankroll(this.value)"></div>
    <div class="ctrl"><span class="cl" title="Only simulate trades whose |edge| clears this">Sim edge</span><select onchange="btSetSimEdge(this.value)">${simEdgeOpts}</select></div>
    <div class="ctrl"><span class="cl" title="Maker fill model — how the entry price is set and whether the order fills">Execution</span><select onchange="btSetExec(this.value)">${execOpts}</select></div>
    <details class="adv" ${advSet ? "open" : ""}>
      <summary><span class="adv-cap">Advanced</span>${advSet ? `<span class="adv-on">active</span>` : ""}</summary>
      <div class="adv-row">
        <div class="ctrl"><span class="cl" title="Skip trades cheaper than this entry">Min entry</span><select onchange="btSetMinEntry(this.value)">${minEntryOpts}</select></div>
        <div class="ctrl"><span class="cl" title="Anti-stacking: per day, keep only the top N signals by |edge|">Max signals/day</span><select onchange="btSetMaxSignals(this.value)">${maxSigOpts}</select></div>
        <div class="ctrl"><span class="cl" title="Cap the edge used for position sizing (sizing only)">Edge cap (size)</span><select onchange="btSetEdgeCap(this.value)">${edgeCapOpts}</select></div>
        <div class="ctrl"><span class="cl" title="Max contracts available at the quoted price">Depth cap</span><input type="number" value="${bt.depth}" step="50" onchange="btSetDepth(this.value)"></div>
      </div>
    </details>
  </div>`;
}

// Independent SIM-strategy control, docked in the P&L panel header. Governs ONLY
// the equity curve + the sim chips (a separate jsComputeSim call). null simStrategy
// means "follow the signal strategy"; once the user picks here it stays locked,
// with a one-click reset back to following.
function simStrategyControl(d) {
  const blendAvailable = !!d.blend;
  const eff = bt.simStrategy || bt.strategy;
  const following = bt.simStrategy === null;
  const btn = (id, label) => {
    const dis = id !== "raw" && !blendAvailable;
    return `<button class="${eff === id ? "on" : ""}" ${dis ? `disabled title="no blend model for this city"` : `onclick="btSetSimStrategy('${id}')"`}>${label}</button>`;
  };
  const reset = following ? "" : `<button class="sim-strat-reset" title="follow the signal strategy again" onclick="btFollowSimStrategy()">↺ follow</button>`;
  return `<div class="sim-strat" title="Strategy used for the simulation curve + chips only — independent of the ladder's signal strategy"><span class="sim-strat-k">Sim strategy${following ? `<span class="sim-strat-follow">follows signals</span>` : ""}</span><div class="seg">${btn("raw", "Raw")}${btn("blend", "Blend")}${btn("union", "Union")}</div>${reset}</div>`;
}

// ★ THE BRACKET LADDER — a vertical thermal probability ladder. Rows are
// ordered hottest→coldest top-to-bottom and tinted on the thermal ramp by their
// temperature; the track fill width = the strategy-selected model/blend P and
// the white tick = the market price, so the fill→tick gap reads as the edge.
// Signal-selection logic (raw / blend / union) is preserved verbatim from the
// old table so the displayed signals stay in lockstep with jsComputeSim.
function edgeByBracketTable(d) {
  const brackets = d.brackets || [];
  const union = bt.strategy === "union";
  const blend = bt.strategy === "blend";
  const meta = union
    ? `union · raw ≥ ${(bt.bracketEdge * 100).toFixed(0)}% OR blend ≥ ${(bt.bracketEdge * 40).toFixed(0)}% · fill = model/blend P, tick = market`
    : `${blend ? "blend" : "raw"} · fires when |edge| ≥ ${(bt.bracketEdge * 100).toFixed(0)}% · fill = ${blend ? "blend" : "model"} P, tick = market`;
  if (brackets.length === 0) {
    return `<div class="panel"><div class="panel-h"><h3>Bracket ladder</h3><span class="meta">${esc(meta)}</span></div><div class="ladder-empty muted">No brackets for ${esc(bt.date || "")}.</div></div>`;
  }
  const ramp = ["var(--cold)", "var(--cool)", "var(--temperate)", "var(--warm)", "var(--hot)", "var(--extreme)"];
  // representative temperature per bracket — ignore the open-ended sentinel side
  // (≤X has lo≈−99, ≥X has hi≈99) so the thermal ramp spreads over the real range.
  // Mirrors ensembleChartSVG's |v|<90 boundary filter.
  const mids = brackets.map(b => {
    const loFin = b.lo != null && b.lo > -90, hiFin = b.hi != null && b.hi < 90;
    if (loFin && hiFin) return (b.lo + b.hi) / 2;
    if (hiFin) return b.hi;          // ≤hi (open below)
    if (loFin) return b.lo;          // ≥lo (open above)
    return 0;
  });
  const minMid = Math.min(...mids), midSpan = (Math.max(...mids) - minMid) || 1;
  const order = brackets.map((_, i) => i).sort((a, c) => mids[c] - mids[a]);   // hottest first
  const rows = order.map((i, k) => {
    const b = brackets[i];
    const tc = ramp[Math.round(((mids[i] - minMid) / midSpan) * (ramp.length - 1))];
    let probSel, e, fires, tag = "";
    if (union) {
      const rawEdge = b.modelP - b.mktP;
      const blendEdge = (b.blendP != null) ? (b.blendP - b.mktP) : null;
      const rawFires = Math.abs(rawEdge) >= bt.bracketEdge;
      const blendFires = blendEdge != null && Math.abs(blendEdge) >= (bt.bracketEdge * 0.4);
      fires = rawFires || blendFires;
      e = rawFires ? rawEdge : (blendFires ? blendEdge : rawEdge);
      probSel = rawFires ? b.modelP : (blendFires ? b.blendP : b.modelP);
      tag = rawFires && blendFires ? "both" : rawFires ? "raw" : blendFires ? "blend" : "";
    } else {
      probSel = (blend && b.blendP != null) ? b.blendP : b.modelP;
      e = probSel - b.mktP;
      fires = Math.abs(e) >= bt.bracketEdge;
    }
    const side = (e || 0) > 0 ? "YES" : "NO";
    const fillPct = Math.max(0, Math.min(100, (probSel || 0) * 100));
    const mktPct = Math.max(0, Math.min(100, (b.mktP || 0) * 100));
    const sig = fires
      ? `<span class="side ${side === "YES" ? "yes" : "no"}">BUY ${side}${tag ? ` <small style="opacity:.6">${tag}</small>` : ""}</span>`
      : `<span class="muted">—</span>`;
    return `<div class="rung${fires ? " fires" : ""}" style="--tc:${tc};--ri:${k}">
      <div class="rung-label"><span class="rung-dot"></span>${esc(b.label)}</div>
      <div class="rung-track" title="model/blend ${fillPct.toFixed(0)}% · market ${mktPct.toFixed(0)}%"><div class="rung-fill" style="width:${fillPct.toFixed(1)}%"></div><div class="rung-mkt" style="left:${mktPct.toFixed(1)}%"></div></div>
      <div class="rung-prob">${fillPct.toFixed(0)}%</div>
      <div class="rung-edge">${edgeCell(e || 0)}</div>
      <div class="rung-sig">${sig}</div>
      <div class="rung-res"><span class="outcome ${b.resolved === "YES" ? "yes" : "no"}">${esc(b.resolved)}</span></div>
    </div>`;
  }).join("");
  return `<div class="panel"><div class="panel-h"><h3>Bracket ladder</h3><span class="meta">${esc(meta)}</span></div>
    <div class="ladder">
      <div class="rung rung-head"><div class="rung-label">Bracket °F</div><div class="rung-track-h">${blend ? "blend" : "model"} P  ·  ▮ market</div><div class="rung-prob">P</div><div class="rung-edge">Edge</div><div class="rung-sig">Signal</div><div class="rung-res">Res</div></div>
      ${rows}
    </div></div>`;
}

function tradeDetailTable(sim) {
  const recs = sim.tradeRecords || [];
  let body;
  if (recs.length === 0) body = `<tr><td class="l muted" colspan="11" style="padding:16px 12px">No trade history.</td></tr>`;
  else body = [...recs].reverse().map(t => {
    const skipped = t.fill === "filtered" || t.fill === "below-min" || t.fill === "skipped";
    const isFilled = t.fill === "filled";
    const showP = t.stratP != null ? t.stratP : t.modelP;
    const showEdge = t.stratEdge != null ? t.stratEdge : t.edge;
    const showSide = t.stratSide ? (t.stratSide === "BUY_YES" ? "YES" : "NO") : t.side;
    const wonShown = t.stratWon != null ? t.stratWon : t.won;
    return `<tr><td class="l">${esc(t.date)}</td><td class="l hi">${esc(t.bracket)}</td><td><span class="side ${showSide === "YES" ? "yes" : "no"}">${showSide}</span></td><td>${(showP * 100).toFixed(0)}%</td><td>${(t.mktP * 100).toFixed(0)}%</td><td>${edgeCell(showEdge)}</td><td>${t.entry}¢</td><td class="${isFilled ? "hi" : "muted"}">${isFilled ? t.computedQty : "—"}</td><td><span class="pill-status ${esc(t.fill)}">${esc(t.fill)}</span></td><td>${(t.won === null || skipped) ? `<span class="muted">—</span>` : `<span class="outcome ${wonShown ? "yes" : "no"}">${wonShown ? "WIN" : "LOSS"}</span>`}</td><td class="${!isFilled ? "muted" : cls(t.computedPnl)}">${!isFilled ? "—" : money(t.computedPnl)}</td></tr>`;
  }).join("");
  return `<div class="panel"><div class="panel-h"><h3>Trade-by-trade detail</h3><span class="meta">every paper trade · ${bt.strategy === "union" ? "UNION" : bt.strategy === "blend" ? "BLEND" : "RAW"} signal · qty/P&L reflect (${esc(bt.sizing)}, $${Number(bt.amount).toLocaleString()}/trade, cap ${bt.depth})</span></div><div class="tbl-scroll" style="max-height:280px"><table class="dt"><thead><tr><th class="l">Date</th><th class="l">Bracket</th><th>Side</th><th>${bt.strategy === "blend" ? "Blend P" : "Model P"}</th><th>Market P</th><th>Edge</th><th>Entry</th><th>Qty</th><th>Fill</th><th>Result</th><th>P&amp;L</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
}

// Honest per-strategy Brier on the YES outcome over this strategy's filled,
// resolved trades — replaces the server's hardcoded 0.20 placeholder. stratP is
// the YES probability the strategy assigned; the realized YES outcome is derived
// from the side taken and whether it won. null when nothing filled.
function stratBrier(sim) {
  const fr = (sim.tradeRecords || []).filter(t => t.fill === "filled" && t.stratWon != null && t.stratP != null);
  if (!fr.length) return null;
  const sse = fr.reduce((s, t) => {
    const yesOutcome = (t.stratWon === (t.stratSide === "BUY_YES")) ? 1 : 0;
    return s + (t.stratP - yesOutcome) ** 2;
  }, 0);
  return sse / fr.length;
}

function strategyComparison(strat) {
  let body;
  if (!strat || strat.length === 0) body = `<tr><td class="l muted" colspan="8" style="padding:16px 12px">No strategy comparison data.</td></tr>`;
  else body = strat.map(s => {
    if (s.available === false) {
      return `<tr><td class="l hi">${esc(s.name)}</td><td class="muted" colspan="7" style="text-align:center">no blend model for this city</td></tr>`;
    }
    return `<tr class="${s.chosen ? "chosen" : ""}"><td class="l hi">${esc(s.name)}${s.chosen ? `<span class="chosen-tag">active</span>` : ""}</td><td class="hi">${moneyPlain(s.final)}</td><td class="${cls(s.ret)}">${pct(s.ret)}</td><td class="${s.sharpe >= 1 ? "pos" : ""}">${s.sharpe.toFixed(2)}</td><td class="neg">${pct(s.maxDD)}</td><td>${(s.win * 100).toFixed(0)}%</td><td>${s.brier != null ? s.brier.toFixed(3) : "—"}</td><td>${s.n}</td></tr>`;
  }).join("");
  return `<div class="panel"><div class="panel-h"><h3>Strategy comparison</h3><span class="meta">${esc(BT.city)} · raw vs blend vs union · ${esc(bt.sizing)} · |edge| ≥ ${(bt.simEdge * 100).toFixed(0)}% · matches sim controls</span></div><table class="dt"><thead><tr><th class="l">Model variant</th><th>Final balance</th><th>Return</th><th>Sharpe</th><th>Max DD</th><th>Win rate</th><th>Brier</th><th>Trades</th></tr></thead><tbody>${body}</tbody></table></div>`;
}

// FREE WIN — Benter blend breakdown (data already in the payload: blend{}).
// Shows the market-vs-model share of the blended probability + the logit
// coefficients. β_model can be NEGATIVE (model anti-informative) → flagged red.
function blendPanel(d) {
  const bl = d.blend;
  if (!bl) return "";
  const fmtB = v => (v == null ? "—" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2));
  const hasShare = typeof bl.marketShare === "number" && isFinite(bl.marketShare);
  const mkt = hasShare ? Math.max(0, Math.min(1, bl.marketShare)) : 0;
  const mdl = 1 - mkt;
  const split = hasShare
    ? `<div class="blend-split" title="share of the blended probability driven by each source"><div class="blend-seg market" style="width:${(mkt * 100).toFixed(1)}%">market ${(mkt * 100).toFixed(0)}%</div><div class="blend-seg model" style="width:${(mdl * 100).toFixed(1)}%">model ${(mdl * 100).toFixed(0)}%</div></div>`
    : "";
  const betaModelNeg = bl.betaModel != null && bl.betaModel < 0;
  return `<div class="panel blend-panel"><div class="panel-h"><h3>Benter blend</h3><span class="meta">logit weights · n=${bl.nTrain != null ? bl.nTrain : "—"}</span></div>
    <div class="panel-b blend-body">${split}<div class="blend-coefs mono"><span>α ${fmtB(bl.alpha)}</span><span>β<sub>market</sub> ${fmtB(bl.betaMarket)}</span><span class="${betaModelNeg ? "neg" : ""}">β<sub>model</sub> ${fmtB(bl.betaModel)}${betaModelNeg ? " <small>anti-informative</small>" : ""}</span></div></div>
  </div>`;
}

// MODEL CALIBRATION — reliability of the raw model probability over this city's
// resolved trade history (data already in d.trades). Bins trades by modelP and
// compares the predicted YES probability to the realized YES frequency, so a
// fill that falls short of its market tick reads as miscalibration. Compact —
// shares the diagnostics row with the Benter-blend panel.
function calibrationPanel(d) {
  const rs = (d.trades || []).filter(t => t.won !== null && t.modelP != null);
  if (rs.length < 12) return "";                 // too little resolved history to be honest
  const bands = [[0, 0.2], [0.2, 0.4], [0.4, 0.6], [0.6, 0.8], [0.8, 1.0001]];
  const agg = bands.map(([lo, hi]) => ({ lo, hi, n: 0, pred: 0, yes: 0 }));
  rs.forEach(t => {
    const p = t.modelP;
    let bi = bands.findIndex(([lo, hi]) => p >= lo && p < hi);
    if (bi < 0) bi = p >= 1 ? bands.length - 1 : 0;
    const bracketYes = (t.side === "YES") ? !!t.won : !t.won;   // modelP pairs with the raw model side
    agg[bi].n++; agg[bi].pred += p; agg[bi].yes += bracketYes ? 1 : 0;
  });
  const rows = agg.filter(g => g.n > 0).map(g => {
    const pred = g.pred / g.n, act = g.yes / g.n, gap = act - pred;
    const gapTone = Math.abs(gap) <= 0.08 ? "pos" : Math.abs(gap) <= 0.18 ? "warn" : "neg";
    return `<div class="calib-row">
      <span class="calib-band mono">${(g.lo * 100).toFixed(0)}–${(Math.min(g.hi, 1) * 100).toFixed(0)}%</span>
      <span class="calib-track" title="predicted ${(pred * 100).toFixed(0)}% · realized ${(act * 100).toFixed(0)}%"><span class="calib-fill" style="width:${(act * 100).toFixed(1)}%"></span><span class="calib-pred" style="left:${(pred * 100).toFixed(1)}%"></span></span>
      <span class="calib-act mono">${(act * 100).toFixed(0)}%</span>
      <span class="calib-gap mono ${gapTone}">${gap >= 0 ? "+" : "−"}${Math.abs(gap * 100).toFixed(0)}</span>
      <span class="calib-n mono muted">${g.n}</span>
    </div>`;
  }).join("");
  return `<div class="panel calib-panel"><div class="panel-h"><h3>Model calibration</h3><span class="meta">raw model P vs realized · n=${rs.length}</span></div>
    <div class="calib">
      <div class="calib-row calib-head"><span class="calib-band">model P</span><span class="calib-track">realized ▮ predicted</span><span class="calib-act">real</span><span class="calib-gap">gap</span><span class="calib-n">n</span></div>
      ${rows}
    </div></div>`;
}

// ---- entrance animations (city·date change only) ----------------------------
// changed=true (new city/date while the Backtest tab is visible) → panels
// scroll-reveal, the balance chart draws on, and the metrics count up. Param /
// slider tweaks pass changed=false → everything snaps to FINAL state, so a slider
// drag never thrashes. RM (reduced-motion) collapses to final state too.
let _btLastKey = null;
const _btPrevVals = {};

// Tween one metric cell to its already-rendered final value, preserving the
// cell's exact final innerHTML (countUp() writes textContent, which would strip
// the fc-stats °F <small> markup — so we drive rampClock ourselves here).
function btCountEl(el, from, to, fmt, big) {
  if (!el) return;
  const finalHTML = el.innerHTML;
  if (from == null || from === to || RM.matches || typeof to !== "number" || !isFinite(to)) { el.innerHTML = finalHTML; return; }
  el.innerHTML = fmt(from);                                  // pre-paint at previous value (no flash)
  rampClock(big ? LOAD_MS : TICK_MS, big ? easeOutExpo : easeOutCubic,   // big = first-open "moment" (0→value, slow); else a quick prev→new tick
    e => { el.innerHTML = fmt(from + (to - from) * e); },
    () => { el.innerHTML = finalHTML; });                    // restore exact final
}

// Draw-on for the balance curve via the shared rampClock + E1's chart hooks
// (.chart-line stroke-dashoffset → 0, .chart-fill-reveal scaleX 0 → 1).
function btDrawBalance(svg) {
  if (!svg || RM.matches) return;
  const line = svg.querySelector(".chart-line");
  const fill = svg.querySelector(".chart-fill-reveal");
  if (!line) return;
  let len; try { len = line.getTotalLength(); } catch (e) { return; }
  line.style.strokeDasharray = len; line.style.strokeDashoffset = len;
  if (fill) fill.style.transform = "scaleX(0)";
  rampClock(720, easeOutCubic,                               // 720ms == --dur-draw
    e => { line.style.strokeDashoffset = len * (1 - e); if (fill) fill.style.transform = "scaleX(" + e + ")"; },
    () => { line.style.strokeDashoffset = 0; if (fill) fill.style.transform = "scaleX(1)"; });
}

function btEnterAnimations(root, changed, d, sim) {
  // metric count-up specs — refresh the prev-value cache on EVERY render so a
  // later city change tweens from the last shown value; animate only on change.
  // `sim` here is the PnL-sim (bt.simStrategy) that drives the headline chips.
  const bm = [...root.querySelectorAll(".bt-metrics .mv")];
  const fc = [...root.querySelectorAll(".fc-stats .mv")];
  const deg = v => (Math.round(v * 10) / 10) + "<small>°F</small>";
  const degI = v => Math.round(v) + "<small>°F</small>";
  const pctI = v => Math.round(v) + "%";
  const net = (sim.final || 0) - (Number(bt.bankroll) || 0);
  const fm = (sim.filled || 0) + (sim.missed || 0);
  const fillPct = fm > 0 ? (sim.filled / fm) * 100 : null;
  const specs = [                                  // order MUST match the .bt-metrics cells in renderBacktest
    [bm[0], "net", net, money],
    [bm[1], "exp", sim.avg || 0, money],
    [bm[2], "hit", (sim.win || 0) * 100, pctI],
    [bm[3], "sharpe", sim.sharpe || 0, v => v.toFixed(2)],
    [bm[4], "maxdd", sim.maxDDDollars || 0, money],
    [bm[5], "fill", fillPct, pctI],
    [fc[0], "members", d.nMembers, v => String(Math.round(v))],
    [fc[1], "ensMean", d.ensMean, deg],
    [fc[2], "ensSpread", d.ensSpread, deg],
    [fc[3], "observed", d.observed, degI],
  ];
  const onBacktest = activeTab === "backtest";
  const doAnim = changed && onBacktest && !RM.matches;
  const firstReveal = doAnim && !btIntroDone;       // first VISIBLE animated paint → count from 0 (the "moment")
  if (onBacktest) btIntroDone = true;               // mark tab as shown (gates switchTab's one-time reveal force)
  for (const [el, k, to, fmt] of specs) {
    const from = firstReveal ? 0 : _btPrevVals[k];
    _btPrevVals[k] = to;
    if (doAnim) btCountEl(el, from, to, fmt, firstReveal);
  }
  if (!doAnim) return;
  btDrawBalance(root.querySelector('svg[data-chart="bal"]'));
  // scroll-reveal each direct child of .wrap as it enters the viewport
  const wrap = root.querySelector(".wrap");
  if (!wrap) return;
  const panels = [...wrap.children];
  panels.forEach((el, i) => { el.classList.add("reveal"); el.style.setProperty("--rd", (i * 45) + "ms"); });
  const reveal = el => el.classList.add("in");
  if (!("IntersectionObserver" in window)) { panels.forEach(reveal); return; }
  const io = new IntersectionObserver((entries, obs) => {
    entries.forEach(ent => { if (ent.isIntersecting) { reveal(ent.target); obs.unobserve(ent.target); } });
  }, { threshold: 0.06 });
  panels.forEach(el => io.observe(el));
  setTimeout(() => panels.forEach(reveal), 1500);              // safety net: never leave a panel hidden
}

function renderBacktest() {
  const root = document.getElementById("backtest-root");
  if (!BT) { root.innerHTML = `<div class="wrap"><div class="loading">Loading backtest…</div></div>`; return; }
  const d = BT;
  // FIX 1: observed is truthful now — null EXACTLY when unresolved — so it IS the
  // resolution signal (and unlike a brackets-only check it still reports a real
  // high on resolved dates that lack bracket rows). Gates every display of
  // d.observed so a still-PEND day never shows a fabricated "resolved high".
  const resolved = d.observed != null;
  // TWO independent sims off the FROZEN jsComputeSim (called here, never edited):
  //   simSig (signal strategy) → the trade-by-trade table, kept in lockstep with the ladder.
  //   simPnl (sim strategy)    → the equity curve + the headline chips, independently strategizable.
  // bt.simStrategy === null means the sim mirrors the signal strategy.
  const simStrat = bt.simStrategy || bt.strategy;
  const baseParams = {
    sizing: bt.sizing, edgeFilter: bt.simEdge, minEntry: bt.minEntry, amountDollars: Number(bt.amount) || 0,
    depthCap: Number(bt.depth) || 0, execution: bt.exec, startingBankroll: bt.bankroll,
    maxSignals: Number(bt.maxSignals) || 0, edgeCap: Number(bt.edgeCap) || 0,
  };
  const simSig = jsComputeSim(d.trades || [], { ...baseParams, strategy: bt.strategy });
  const simPnl = (simStrat === bt.strategy) ? simSig : jsComputeSim(d.trades || [], { ...baseParams, strategy: simStrat });

  // Strategy comparison — recomputed CLIENT-SIDE under the SAME controls as the
  // Simulation panel (bankroll/sizing/edge/exec) so it's honestly apples-to-apples
  // and live-updates with the controls, instead of a stale server snapshot whose
  // numbers (fetch-time $1000 / 10% edge) contradicted the panel they sat beside.
  // The `chosen` row is the active sim strategy → its numbers match the chips above.
  const STRAT_LABELS = { raw: "Raw model", blend: "Benter blend", union: "Union (raw ∪ blend)" };
  const stratRows = ["raw", "blend", "union"].map(strat => {
    const avail = strat === "raw" || !!d.blend;
    const r = avail ? jsComputeSim(d.trades || [], { ...baseParams, strategy: strat }) : null;
    return {
      name: STRAT_LABELS[strat], available: avail,
      final: r ? r.final : null, ret: r ? r.ret : null, sharpe: r ? r.sharpe : null,
      maxDD: r ? r.maxDD : null, win: r ? r.win : null, brier: r ? stratBrier(r) : null,
      n: r ? r.filled : 0, chosen: strat === simStrat,
    };
  });

  const btKey = (d.code || "") + "|" + (bt.date || "");
  const changed = btKey !== _btLastKey;          // new city/date vs. a param/slider tweak
  _btLastKey = btKey;
  const noData = (!d.trades || d.trades.length === 0);
  const backfilling = noData ? `<div class="bt-backfilling">⏳ ${esc(d.city)}: backtest data is still backfilling (forecast history for this city's traded dates hasn't finished downloading). Best-results will load automatically once it's ready — no action needed.</div>` : "";

  // headline economics (from simPnl) — lead with net edge / expectancy, not win-rate
  const net = (simPnl.final || 0) - (Number(bt.bankroll) || 0);
  const fm = (simPnl.filled || 0) + (simPnl.missed || 0);
  const fillPct = fm > 0 ? (simPnl.filled / fm) * 100 : null;
  const filledRecs = (simPnl.tradeRecords || []).filter(t => t.fill === "filled");
  const avgEdge = filledRecs.length ? filledRecs.reduce((s, t) => s + Math.abs(t.stratEdge != null ? t.stratEdge : t.edge), 0) / filledRecs.length : null;
  const avgEntry = filledRecs.length ? filledRecs.reduce((s, t) => s + (t.entry || 0), 0) / filledRecs.length : null;
  const simMeta = `${esc(d.city)} · ${esc(simStrat)} · ${esc(bt.sizing)} · |edge| ≥ ${(bt.simEdge * 100).toFixed(0)}%`;
  // "filtered" = evaluated trades that didn't trade (below edge/min-entry, capped,
  // no-blend, skipped). Surfacing it makes the breakdown reconcile:
  // evaluated = filled + filtered + missed + pending.
  const noTrade = Math.max(0, (simPnl.total || 0) - (simPnl.filled || 0) - (simPnl.missed || 0) - (simPnl.pending || 0));
  const ledger = `<div class="bt-ledger mono"><span><b>${simPnl.total || 0}</b> evaluated</span><span class="pos"><b>${simPnl.filled || 0}</b> filled</span><span class="muted"><b>${noTrade}</b> filtered</span><span class="${(simPnl.missed || 0) > 0 ? "warn" : "muted"}"><b>${simPnl.missed || 0}</b> missed</span><span class="muted"><b>${simPnl.pending || 0}</b> pending</span><span>avg edge <b>${avgEdge != null ? (avgEdge * 100).toFixed(0) + "%" : "—"}</b></span><span>avg entry <b>${avgEntry != null ? Math.round(avgEntry) + "¢" : "—"}</b></span></div>`;

  const diag = [blendPanel(d), calibrationPanel(d)].filter(Boolean);
  const diagRow = diag.length === 2 ? `<div class="grid g-2">${diag.join("")}</div>` : diag.join("");

  root.innerHTML = `<div class="wrap">` +
    controlsBar(d) +
    `<div class="section-label">Forecast · ${esc(d.city)} · ${esc(bt.date || "")} <span class="sl-sub">combined GEFS + ECMWF ensemble</span></div>` +
    `<div class="grid" style="grid-template-columns:1.5fr 1fr">` +
      `<div class="panel"><div class="panel-h"><h3>Ensemble distribution</h3><span class="meta">${d.nMembers} members · EMOS Gaussian overlay</span></div><div style="padding:8px 8px 0"><div class="chart-wrap">${ensembleChartSVG(d)}</div></div><div class="ens-note"><span><span class="sw" style="background:linear-gradient(90deg,var(--cold),var(--cool),var(--temperate),var(--warm),var(--hot),var(--extreme))"></span>member highs (thermal)</span><span><span class="sw" style="background:linear-gradient(90deg,var(--cold),var(--temperate),var(--hot),var(--extreme));height:4px"></span>EMOS μ=${d.emosMu}° σ=${d.emosSigma}°</span><span><span class="sw" style="background:var(--text-lo)"></span>ensemble mean ${d.ensMean}°</span><span><span class="sw" style="background:var(--up)"></span>resolved high ${resolved ? `${d.observed}°` : "—"}</span></div></div>` +
      `<div class="panel" style="display:flex;flex-direction:column"><div class="panel-h"><h3>Forecast summary</h3></div><div class="fc-stats" style="border-bottom:1px solid var(--border)">${BTMetric("Members", d.nMembers)}${BTMetric("Ens. mean", `${d.ensMean}<small>°F</small>`)}${BTMetric("Ens. spread", `${d.ensSpread}<small>°F</small>`)}${BTMetric("Resolved", resolved ? `${d.observed}<small>°F</small>` : `<span class="muted">pending</span>`)}</div><div style="padding:16px;display:flex;flex-direction:column;gap:14px;flex:1"><div style="display:flex;justify-content:space-between;align-items:baseline"><span style="font:600 11px/1 var(--ui);letter-spacing:.12em;text-transform:uppercase;color:var(--text-lo)">EMOS post-processed</span><span class="mono" style="font-size:18px;color:var(--text-hi)">μ ${d.emosMu}° · σ ${d.emosSigma}°</span></div><div class="mono" style="font-size:11.5px;line-height:1.7;color:var(--text-lo)">Rolling 45-day fit corrects ensemble under-dispersion. Bracket probabilities below integrate this Gaussian; edge = model − market mid.</div></div></div>` +
    `</div>` +
    edgeByBracketTable(d) +
    diagRow +
    `<div class="section-label">P&amp;L simulation <span class="sl-sub">curve &amp; chips follow the sim strategy · trade table follows the signal strategy</span></div>` +
    `<div class="panel"><div class="panel-h"><h3>Simulation</h3>${simStrategyControl(d)}<span class="meta">${simMeta}</span></div>` +
      backfilling + simControls() +
      `<div class="bt-metrics" style="border-bottom:1px solid var(--border)">` +
        BTMetric("Net P&L", money(net), pct(simPnl.ret || 0), net >= 0 ? "pos" : "neg") +
        BTMetric("Expectancy", money(simPnl.avg || 0), "per filled trade", (simPnl.avg || 0) >= 0 ? "pos" : "neg") +
        BTMetric("Hit rate", `${((simPnl.win || 0) * 100).toFixed(0)}%`, `${Math.round((simPnl.n || 0) * (simPnl.win || 0))}/${simPnl.n || 0} resolved`) +
        BTMetric("Sharpe", (simPnl.sharpe || 0).toFixed(2), "annualized", (simPnl.sharpe || 0) >= 1 ? "pos" : "") +
        BTMetric("Max drawdown", money(simPnl.maxDDDollars || 0), `${pct(simPnl.maxDD || 0)} peak→trough`, "neg") +
        BTMetric("Fill rate", fillPct != null ? `${fillPct.toFixed(0)}%` : "—", `${simPnl.filled || 0} filled · ${simPnl.missed || 0} missed`, (fillPct != null && fillPct < 100) ? "warn" : "") +
      `</div>` +
      ledger +
      `<div style="padding:12px 12px 4px"><div class="chart-wrap">${balanceChartSVG(simPnl.curve || [bt.bankroll, bt.bankroll], filledRecs)}</div></div>` +
      `<div class="panel-b" style="padding-top:4px"><div class="chart-legend"><span><span class="sw" style="background:${net >= 0 ? "var(--up)" : "var(--down)"}"></span>equity · $${(simPnl.curve || [bt.bankroll])[0].toLocaleString()} → $${(simPnl.final || 0).toLocaleString()}</span><span><span class="sw" style="background:var(--down);opacity:.4;height:8px"></span>drawdown (underwater)</span></div></div>` +
    `</div>` +
    tradeDetailTable(simSig) +
    strategyComparison(stratRows) +
  `</div>`;
  wireCharts(root);
  btEnterAnimations(root, changed, d, simPnl);
}

// ====================================================================
// BACKTEST control handlers
// ====================================================================
function btSelectCity(code) { bt.cityCode = code; bt.date = null; loadBacktest(); }
function btSelectDate(v) { bt.date = v; loadBacktest(); }
function btSetStrategy(v) { bt.strategy = v; renderBacktest(); }      // signal strategy → ladder + trade table (sim follows if unlocked)
function btSetSimStrategy(v) { bt.simStrategy = v; renderBacktest(); } // PnL-sim strategy → curve + chips only (locks independence)
function btFollowSimStrategy() { bt.simStrategy = null; renderBacktest(); }
function btSetBracketEdge(v) { bt.bracketEdge = +v; renderBacktest(); }
function btSetSimEdge(v) { bt.simEdge = +v; renderBacktest(); }
function btSetMinEntry(v) { bt.minEntry = +v; renderBacktest(); }
function btSetSizing(v) { bt.sizing = v; renderBacktest(); }
function btSetAmount(v) { bt.amount = Number(v) || 0; renderBacktest(); }
function btSetDepth(v) { bt.depth = Number(v) || 0; renderBacktest(); }
function btSetExec(v) { bt.exec = v; renderBacktest(); }
function btSetBankroll(v) { bt.bankroll = Math.max(100, Number(v) || 1000); renderBacktest(); }
function btSetMaxSignals(v) { bt.maxSignals = +v; renderBacktest(); }
function btSetEdgeCap(v) { bt.edgeCap = +v; renderBacktest(); }

// AUTO-LOAD best params the FIRST time each city's data appears. Sets strategy +
// edge to that city's best (by Sharpe, min 15 trades) and forces the realistic
// unit-500 / market defaults. Tracked via a Set so it runs once per city per
// session and never fights manual tweaks (port of the React useEffect).
function autoLoadBest() {
  if (!BT || !BT.trades || !BT.trades.length) return;
  if (autoedCities.has(BT.code)) return;
  const best = (BT.code in bestByCity) ? bestByCity[BT.code] : findBestParams(BT.trades);
  autoedCities.add(BT.code);
  if (best) { bt.strategy = best.strategy; bt.simEdge = best.edge; bt.bracketEdge = best.edge; }
  else { bt.strategy = BT.blend ? "blend" : "raw"; }
  // Reproduce findBestParams' swept config exactly so the rendered Sharpe matches
  // the map dot label (it sweeps unit-500 / market / no caps).
  bt.sizing = "unit"; bt.amount = 500; bt.exec = "market";
  bt.maxSignals = 0; bt.edgeCap = 0;
}

// Cache a city's best (strategy, edge, Sharpe) for the map labels + auto-load.
// Only seed from the TODAY-anchored window so every dot's label is computed over
// the same trailing-365d-as-of-today window (the sweep also forces date=""). A
// load made under an explicit older date is left for the sweep to populate
// canonically, so labels never silently reflect a different date than each other.
function recordBest(p) {
  if (!p || !p.code || p.code in bestByCity) return;
  const today = new Date().toISOString().slice(0, 10);
  if (p.date && p.date !== today) return;
  bestByCity[p.code] = (p.trades && p.trades.length) ? findBestParams(p.trades) : null;
}

// ====================================================================
// DATA FETCH + POLLING
// ====================================================================
async function loadCities() {
  try {
    const r = await fetch("/api/backtest/cities");
    BT_CITIES = await r.json();
    if (!bt.cityCode && BT_CITIES.length) {
      bt.cityCode = BT_CITIES.some(c => c.code === "KORD") ? "KORD" : BT_CITIES[0].code;
    }
  } catch (e) { BT_CITIES = []; }
}

async function loadLive() {
  try {
    const r = await fetch("/api/live");
    LIVE = await r.json();
    LIVE._loadedAt = Date.now();
    const eb = document.getElementById("env-badge");
    if (eb) { eb.textContent = LIVE.env || "LIVE"; eb.className = "env-badge" + (String(LIVE.env).toUpperCase() === "LIVE" ? " live" : ""); }
    renderLive();
    updateLiveIndicator();
  } catch (e) {
    const root = document.getElementById("live-root");
    if (root && !LIVE) root.innerHTML = `<div class="loading">Failed to load live data: ${esc(String(e))}</div>`;
  }
}

async function loadBacktest() {
  if (!bt.cityCode) return;
  try {
    const q = new URLSearchParams({
      city: bt.cityCode, date: bt.date || "",
      sizing: bt.sizing, amount: bt.amount, depth: bt.depth, edge: bt.simEdge,
    });
    const r = await fetch("/api/backtest?" + q.toString());
    BT = await r.json();
    if (!bt.date) bt.date = BT.date;
    recordBest(BT);
    autoLoadBest();
    renderBacktest();
  } catch (e) {
    const root = document.getElementById("backtest-root");
    root.innerHTML = `<div class="wrap"><div class="loading">Failed to load backtest: ${esc(String(e))}</div></div>`;
  }
}

function tickClocks() {
  const el = document.getElementById("cron-countdown");
  if (el && LIVE) el.textContent = formatCountdown(LIVE);
  const c = document.getElementById("clock");
  if (c) {
    const n = new Date(); const p = x => String(x).padStart(2, "0");
    c.innerHTML = `<span class="utc">${p(n.getUTCHours())}:${p(n.getUTCMinutes())}:${p(n.getUTCSeconds())} UTC</span>`;
  }
}

function startLivePolling() { if (!liveTimer) liveTimer = setInterval(loadLive, 2000); }

// Reflect the WS live-mark service status in the topbar pill.
function updateLiveIndicator() {
  const lab = document.getElementById("refresh-label");
  const dot = document.querySelector(".refresh-pill .dot");
  const lv = (LIVE && LIVE.live) || { connected: false, marks: 0, ageMs: null };
  const fs = liveFeedState(lv);
  if (lab) {
    lab.textContent = lv.connected
      ? `ws · ${lv.marks} live · ${fs.ageS != null ? fs.ageS + "s" : "—"}${fs.tag ? " · " + fs.tag : ""}`
      : "rest · 2s";
  }
  // dot state drives BOTH colour and pulse via CSS (.dot.live/.stale/.dead) —
  // green only when marks are genuinely fresh.
  if (dot) dot.className = "dot " + fs.dot;
}
function stopLivePolling() { if (liveTimer) { clearInterval(liveTimer); liveTimer = null; } }

// ====================================================================
// ACCOUNTING TAB — tax reserve + withdrawals + safe-to-withdraw.
// Figures come from /api/accounting (live Kalshi: deposits/withdrawals/
// settlements/balance/orders). The federal RATE is applied client-side so the
// control recomputes reserve + safe-to-withdraw with no refetch; every other
// dollar is server-computed and traces to a live source.
// ====================================================================
let ACCT = null;
let acctFedRate = null;      // seeded from tax.fedRateDefault on first payload
let acctIntroDone = false;

async function loadAccounting() {
  const root = document.getElementById("accounting-root");
  if (!ACCT) root.innerHTML = `<div class="wrap"><div class="loading">Loading accounting…</div></div>`;
  try {
    const r = await fetch("/api/accounting");
    if (!r.ok) throw new Error("HTTP " + r.status);
    ACCT = await r.json();
    if (acctFedRate === null) acctFedRate = ACCT.tax.fedRateDefault;
    renderAccounting();
  } catch (e) {
    root.innerHTML = `<div class="wrap"><div class="loading">Failed to load accounting: ${esc(String(e))}</div></div>`;
  }
}

function acctSetFedRate(rate) {
  const v = Number(rate);
  if (!isFinite(v)) return;
  acctFedRate = Math.min(0.6, Math.max(0, v));   // clamp 0–60%
  renderAccounting();
}

function acctMetric(label, value, sub, tone) {
  return `<div class="m"><div class="ml">${esc(label)}</div><div class="mv ${tone || ""}">${value}</div>${sub != null ? `<div class="ms">${esc(sub)}</div>` : ""}</div>`;
}

function transferTable(title, rows, dir) {
  const cls = dir === "in" ? "amt-in" : "amt-out", sign = dir === "in" ? "+" : "−";
  const body = rows.length === 0
    ? `<tr><td class="l muted" colspan="3" style="padding:16px 12px">None recorded.</td></tr>`
    : rows.map(r => `<tr><td class="l">${esc(r.date)}</td><td class="l">${esc(r.type || "—")}</td><td class="${cls}">${sign}${moneyPlain(r.amount)}</td></tr>`).join("");
  return `<div class="panel"><div class="panel-h"><h3>${esc(title)}</h3><span class="meta">${rows.length} · live Kalshi</span></div><div class="tbl-scroll" style="max-height:220px"><table class="dt"><thead><tr><th class="l">Date</th><th class="l">Type</th><th>Amount</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
}

function renderAccounting() {
  const root = document.getElementById("accounting-root");
  root.classList.remove("intro");                 // clear so a re-render never re-animates
  if (!ACCT) { root.innerHTML = `<div class="wrap"><div class="loading">Loading accounting…</div></div>`; return; }
  const d = ACCT, t = d.tax, rate = acctFedRate;
  const base = Math.max(0, t.realizedNetTaxable);
  const fedReserve = Math.round(base * rate * 100) / 100;
  const reserve = Math.round((fedReserve + t.stateTax) * 100) / 100;    // FL state = 0
  const safe = Math.round((d.cash - reserve - d.openOrderMargin) * 100) / 100;
  const reserveWithdrawn = Math.round(d.withdrawals.total * rate * 100) / 100;   // illustrative: tax only on withdrawn cash
  const presets = t.fedRatePresets.map(p =>
    `<button class="${Math.abs(p.rate - rate) < 1e-9 ? "on" : ""}" onclick="acctSetFedRate(${p.rate})">${esc(p.label)}</button>`).join("");
  const asOf = (d.asOf || "").replace("T", " ").replace("+00:00", " UTC");

  root.innerHTML = `<div class="wrap">
    <div class="disclaimer"><span class="i">⚠</span><span><b>Estimate only — not tax advice.</b> Federal treatment of prediction-market income is unsettled (ordinary income vs. §1256 60/40); Kalshi 1099 reporting has varied. Figures are live from Kalshi. Consult a tax professional before filing or withdrawing against this.</span></div>

    <div class="section-label">Withdrawal readiness <span class="sl-sub">live · Kalshi · as of ${esc(asOf)}</span></div>

    <div class="panel">
      <div class="panel-h"><h3>Safe to withdraw now</h3><span class="meta">cash − tax reserve − open-order margin</span></div>
      <div class="safe-body">
        <div class="safe-figure ${safe >= 0 ? "pos" : "neg"}">${moneyPlain(safe)}</div>
        <div class="safe-eq">
          <span class="eq-term"><b>${moneyPlain(d.cash)}</b><span class="k">cash</span></span>
          <span class="eq-op">−</span>
          <span class="eq-term"><b>${moneyPlain(reserve)}</b><span class="k">tax reserve</span></span>
          <span class="eq-op">−</span>
          <span class="eq-term"><b>${moneyPlain(d.openOrderMargin)}</b><span class="k">open-order margin</span></span>
        </div>
      </div>
    </div>

    <div class="panel"><div class="acct-metrics">
      ${acctMetric("Cash", moneyPlain(d.cash), "settled, withdrawable")}
      ${acctMetric("Portfolio value", moneyPlain(d.portfolioValue), "open positions, marked")}
      ${acctMetric("Account value", moneyPlain(d.accountValue), "cash + portfolio")}
      ${acctMetric("Cumulative net P&L", money(d.cumulativePnl), "realized + unrealized", cls(d.cumulativePnl))}
    </div></div>

    <div class="grid acct-grid" style="grid-template-columns:1fr 1fr">
      <div class="panel">
        <div class="panel-h"><h3>Capital flow</h3><span class="meta">live · Kalshi transfers</span></div>
        <div class="ledger">
          <div class="lrow"><span class="lbl">Deposits <small>· ${d.deposits.rows.length} transfers</small></span><span class="val amt-in">+${moneyPlain(d.deposits.total)}</span></div>
          <div class="lrow"><span class="lbl">Referral credit <small>· audited, non-API</small></span><span class="val amt-in">+${moneyPlain(d.referralCredit)}</span></div>
          <div class="lrow"><span class="lbl">Withdrawals <small>· ${d.withdrawals.rows.length}</small></span><span class="val amt-out">−${moneyPlain(d.withdrawals.total)}</span></div>
          <div class="lrow total"><span class="lbl">Net external capital</span><span class="val">${moneyPlain(d.netExternalCapital)}</span></div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-h"><h3>Estimated tax reserve · ${t.year}</h3><span class="meta">realized · net of fees</span></div>
        <div class="ledger" style="padding-bottom:6px">
          <div class="lrow"><span class="lbl">Settled realized <small>· gross · ${t.nSettled} markets</small></span><span class="val amt-in">+${moneyPlain(t.settledGross)}</span></div>
          <div class="lrow"><span class="lbl">Kalshi fees</span><span class="val amt-out">−${moneyPlain(t.settledFees)}</span></div>
          <div class="lrow"><span class="lbl">Settled realized <small>· net</small></span><span class="val ${cls(t.settledNet)}">${money(t.settledNet)}</span></div>
          <div class="lrow"><span class="lbl">Intraday round-trips <small class="hint" title="Net realized P&amp;L of contracts bought and sold before expiry. Derived from the account identity — Kalshi's per-fill feed is capped and mis-signed, so it can't be itemized. All account activity is in ${t.year}, so this realized cash is current-year.">round-trip realized ⓘ</small></span><span class="val ${cls(t.intradayRealized)}">${money(t.intradayRealized)}</span></div>
          <div class="lrow total"><span class="lbl">${t.year} realized net (taxable base)</span><span class="val ${cls(t.realizedNetTaxable)}">${money(t.realizedNetTaxable)}</span></div>
        </div>
        <div class="rate-ctrl">
          <span class="cl">Federal rate</span>
          <span class="seg">${presets}</span>
          <input class="rate-input" type="number" min="0" max="60" step="0.1" value="${(rate * 100).toFixed(1)}" onchange="acctSetFedRate(this.value/100)" aria-label="Custom federal rate percent" />
          <span class="rate-suffix">%</span>
        </div>
        <div class="ledger">
          <div class="lrow"><span class="lbl">Florida state tax <small>· no state income tax</small></span><span class="val state-zero">$0.00</span></div>
          <div class="lrow"><span class="lbl">Federal reserve <small>· ${(rate * 100).toFixed(1)}% × ${moneyPlain(base)}${t.realizedNetTaxable < 0 ? " · no liability on a net loss" : ""}</small></span><span class="val">${moneyPlain(fedReserve)}</span></div>
          <div class="lrow total"><span class="lbl">Estimated reserve to set aside</span><span class="val warn">${moneyPlain(reserve)}</span></div>
        </div>
        <div class="scen">
          <div class="scen-head">Tax-basis comparison · × ${(rate * 100).toFixed(1)}%</div>
          <div class="lrow"><span class="lbl">On realized gains <small>· standard for a taxable account</small></span><span class="val">${moneyPlain(reserve)}</span></div>
          <div class="lrow"><span class="lbl">On withdrawn cash only <small>· ${moneyPlain(d.withdrawals.total)} withdrawn to date</small></span><span class="val">${moneyPlain(reserveWithdrawn)}</span></div>
          <div class="scen-note">Withdrawing from a taxable account isn't itself a taxable event — realized gains are taxed in the year they're realized (the "tax on withdrawal" rule is for tax-deferred retirement accounts, not Kalshi). Shown for comparison only; the reserve and safe-to-withdraw above use the realized-gains basis.</div>
        </div>
      </div>
    </div>

    <div class="grid acct-grid" style="grid-template-columns:1fr 1fr">
      ${transferTable("Withdrawal history", d.withdrawals.rows, "out")}
      ${transferTable("Deposit history", d.deposits.rows, "in")}
    </div>

    <div class="disclaimer fine"><span class="i">ⓘ</span><span>Taxable base = all realized net gains for ${t.year} (settled + intraday round-trips), net of Kalshi fees; open positions and withdrawals are not taxable events and are excluded. The federal rate is an adjustable assumption, not a determination. This tool does not file, remit, or advise.</span></div>
  </div>`;

  if (!acctIntroDone) { root.classList.add("intro"); acctIntroDone = true; }   // one-shot entrance
}

// ====================================================================
// DIGEST TAB — read-only ops-copilot output. Analytics only, never places or
// adjusts trades: the digest is generated by a daily cron (scripts/ops_digest.py),
// this tab only fetches + displays whatever it last wrote. No LLM call happens
// from the browser or from this server route.
// ====================================================================
let DIGEST = null;

async function loadDigest() {
  const root = document.getElementById("digest-root");
  if (!DIGEST) root.innerHTML = `<div class="wrap"><div class="loading">Loading digest…</div></div>`;
  try {
    const r = await fetch("/api/digest");
    if (!r.ok) throw new Error("HTTP " + r.status);
    DIGEST = await r.json();
    renderDigest();
  } catch (e) {
    root.innerHTML = `<div class="wrap"><div class="loading">Failed to load digest: ${esc(String(e))}</div></div>`;
  }
}

function renderDigest() {
  const root = document.getElementById("digest-root");
  if (!DIGEST) { root.innerHTML = `<div class="wrap"><div class="loading">Loading digest…</div></div>`; return; }
  if (!DIGEST.exists) {
    root.innerHTML = `<div class="wrap"><div class="disclaimer"><span class="i">ⓘ</span><span>No digest yet — run <code>uv run python scripts/ops_digest.py --out docs/digests/$(date -u +%F)-ops-digest.md</code> or install the cron line in docs/crontab.txt.</span></div></div>`;
    return;
  }
  const gen = (DIGEST.generatedAt || "").replace("T", " ").replace("+00:00", " UTC");
  root.innerHTML = `<div class="wrap">
    <div class="disclaimer"><span class="i">ⓘ</span><span><b>Analytics only, not financial advice.</b> Every item below is a suggestion for the operator — this system has no ability to place or adjust a trade. Generated ${esc(gen)} from <code>${esc(DIGEST.file)}</code>.</span></div>
    <div class="panel"><div class="panel-h" style="padding:24px 28px 0"></div><div class="digest-md" style="padding:8px 28px 28px">${DIGEST.html}</div></div>
  </div>`;
}

function switchTab(name) {
  activeTab = name;
  const applyTab = () => {
    ["live", "backtest", "polymarket", "forecastex", "accounting", "digest"].forEach(n => {
      const sec = document.getElementById("section-" + n);
      if (sec) sec.hidden = n !== name;
      const btn = document.getElementById("tab-" + n);
      if (btn) { btn.classList.toggle("on", n === name); btn.setAttribute("aria-selected", String(n === name)); }
    });
  };
  // Cross-fade the tab swap via the View-Transitions API (the ::view-transition
  // rules already ship in shell.css); instant fallback when unsupported or the
  // user prefers reduced motion.
  if (document.startViewTransition && !RM.matches) document.startViewTransition(applyTab);
  else applyTab();
  const rl = document.getElementById("refresh-label");
  if (name === "live") {
    startLivePolling();
    if (rl) rl.textContent = "live";
    return;
  }
  stopLivePolling();
  if (rl) rl.textContent = name;
  if (name === "backtest") {
    // First-reveal hook: the backtest payload is prefetched in init() while the
    // Live tab is showing, so its first render happens hidden (no animation). On
    // the FIRST switch, force a re-render so the entrance ramp fires now visible.
    if (!BT) loadBacktest();
    else if (!btIntroDone) { _btLastKey = null; renderBacktest(); }
  } else if (name === "polymarket") {
    loadPolymarket();   // lazy-load fresh each open (60s server cache bounds cost)
  } else if (name === "forecastex") {
    loadForecastEx();   // lazy-load fresh each open (60s server cache bounds cost)
  } else if (name === "accounting") {
    loadAccounting();   // lazy-load fresh each open (60s server cache bounds cost)
  } else if (name === "digest") {
    loadDigest();       // lazy-load; server just reads a file (5min cache), no LLM call
  }
}

// ---------------------------------------------------------------------------
// POLYMARKET TAB — live-probe status + 5-city paper tracking (/api/polymarket).
// Read-only display; rails values come from the trading script via the API.
let PM_DATA = null;

async function loadPolymarket() {
  const root = document.getElementById("polymarket-root");
  if (!PM_DATA) root.innerHTML = `<div class="wrap"><div class="loading">Loading Polymarket…</div></div>`;
  try {
    const r = await fetch("/api/polymarket");
    PM_DATA = await r.json();
    renderPolymarket();
  } catch (e) {
    root.innerHTML = `<div class="wrap"><div class="loading">Failed to load Polymarket: ${esc(String(e))}</div></div>`;
  }
}

function pmUsd(cents) {
  if (cents == null) return "–";
  const v = cents / 100;
  const cls = v > 0 ? "pos" : v < 0 ? "neg" : "";
  return `<span class="${cls}">${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}</span>`;
}

function renderPolymarket() {
  const root = document.getElementById("polymarket-root");
  if (!PM_DATA) { root.innerHTML = `<div class="wrap"><div class="loading">Loading Polymarket…</div></div>`; return; }
  const p = PM_DATA.probe, rails = p.rails;

  const statusPill = p.halted
    ? `<span class="pill-status halt">HALTED</span>`
    : `<span class="pill-status ok">LIVE</span>`;
  const killPct = Math.min(100, Math.max(0, (p.cumulative_realized_cents / (rails.cumulative_kill_usd * 100)) * 100));
  const probeHead =
    `<div class="panel"><div class="panel-h"><h3>Live probe — Miami (raw@${(rails.edge_threshold * 100).toFixed(0)}%)</h3>` +
    `<span class="meta">${statusPill} · ${rails.contracts_per_signal}x/signal · max ${rails.max_signals_per_day}/day · ` +
    `$${rails.daily_spend_cap_usd}/day cap · kill −$${Math.abs(rails.cumulative_kill_usd).toFixed(0)} · IOC-limit only, +2¢ bound</span></div>` +
    `<div style="padding:14px 28px 6px;font-family:var(--mono);font-size:13px">` +
    `Cumulative realized: ${pmUsd(p.cumulative_realized_cents)}` +
    // Realized is the trading result; out-of-pocket is what the operator's own
    // cash is down. The promo credit absorbs losses first, so the two differ
    // until it is exhausted. Only shown while the credit is actually doing
    // something -- on a winning book they are the same number.
    (p.funding && p.funding.credit_used_cents > 0
      ? `<span style="color:var(--text-lo)"> · ${pmUsd(p.funding.credit_used_cents)} of ` +
        `${pmUsd(p.funding.promo_credit_cents)} promo credit absorbed → ` +
        `out of pocket <span style="color:${p.funding.out_of_pocket_cents < 0 ? "var(--neg)" : "var(--pos)"}">` +
        `${pmUsd(p.funding.out_of_pocket_cents)}</span></span>`
      : "") +
    (p.halted ? `<div style="color:var(--neg);margin-top:6px">${esc(p.halt_text || "halt file present")}</div>` : "") +
    `<div style="color:var(--text-lo);margin-top:4px;font-size:11.5px">${killPct <= 0 ? "" : `${killPct.toFixed(0)}% of the way to the kill switch`}</div></div>`;

  const tradeRows = (p.trades || []).map(t => {
    const res = t.settlement == null ? `<span style="color:var(--text-lo)">open</span>`
      : t.settlement === "no_fill" ? `<span style="color:var(--text-lo)">no fill</span>`
      : t.settlement === "win" ? `<span class="pos">WIN</span>` : `<span class="neg">LOSS</span>`;
    return `<tr><td class="l">${esc(t.target_date)}</td><td class="l">${esc(t.ticker.replace("tc-temp-", ""))}</td>` +
      `<td><span class="side ${t.side === "YES" ? "yes" : "no"}">${t.side}</span></td>` +
      `<td>${t.count}</td><td>${t.limit_cents}¢</td><td>${t.fill_count}${t.fill_avg_cents ? ` @ ${t.fill_avg_cents.toFixed(1)}¢` : ""}</td>` +
      `<td>${res}</td><td>${pmUsd(t.realized_cents)}</td></tr>`;
  }).join("");
  const probeTable = (p.trades || []).length
    ? `<div class="tbl-scroll" style="max-height:260px"><table class="dt"><thead><tr>` +
      `<th class="l">Date</th><th class="l">Market</th><th>Side</th><th>Qty</th><th>Limit</th><th>Fill</th><th>Result</th><th>P&amp;L</th>` +
      `</tr></thead><tbody>${tradeRows}</tbody></table></div>`
    : `<div style="padding:10px 28px 22px;color:var(--text-lo);font-size:12.5px">No orders yet — first cron fire 14:47 UTC daily.</div>`;

  const paperRows = (PM_DATA.paper || []).map(c =>
    `<tr><td class="l">${esc(c.city)}</td><td>${c.signals_14d}</td><td class="l">${esc(c.last_signal || "–")}</td>` +
    `<td>${c.settled}</td><td>${c.settled ? Math.round(100 * c.wins / c.settled) + "%" : "–"}</td>` +
    `<td>${pmUsd(c.net_cents)}</td></tr>`).join("");
  const paperPanel =
    `<div class="panel"><div class="panel-h"><h3>Paper tracking — 5 PM cities</h3>` +
    `<span class="meta">forward validation · logged daily 14:46 UTC · threshold 10% · 1 contract/signal</span></div>` +
    `<div class="tbl-scroll"><table class="dt"><thead><tr><th class="l">City</th><th>Signals 14d</th>` +
    `<th class="l">Last signal</th><th>Settled</th><th>Win%</th><th>Net</th></tr></thead><tbody>${paperRows}</tbody></table></div></div>`;

  const replayRows = (PM_DATA.replay || []).map(r =>
    `<tr><td class="l">${esc(r.city)}</td><td>${r.n}</td><td>${r.win}%</td><td>${r.cents_per_trade.toFixed(1)}¢</td></tr>`).join("");
  const replayPanel =
    `<div class="panel"><div class="panel-h"><h3>Replay reference</h3>` +
    `<span class="meta">day-matched backtest 06-30→08-11 · PM-native brackets @25% · judge forward numbers against these</span></div>` +
    `<div class="tbl-scroll"><table class="dt"><thead><tr><th class="l">City</th><th>n</th><th>Win%</th><th>¢/trade</th></tr></thead>` +
    `<tbody>${replayRows}</tbody></table></div></div>`;

  root.innerHTML = `<div class="wrap"><div class="grid" style="gap:14px">` +
    `${probeHead}${probeTable}</div>` +   // closes the probe .panel opened in probeHead
    `<div class="grid g-2">${paperPanel}${replayPanel}</div></div></div>`;
}

let FX_DATA = null;

let FX_CITY = "KMIA";       // deep-dive selection; Miami is the live Kalshi city

function fxSelectCity(code) {
  FX_CITY = code;
  renderForecastEx();
}

async function loadForecastEx() {
  const root = document.getElementById("forecastex-root");
  if (!FX_DATA) root.innerHTML = `<div class="wrap"><div class="loading">Loading Robinhood…</div></div>`;
  try {
    const r = await fetch("/api/forecastex");
    FX_DATA = await r.json();
    renderForecastEx();
  } catch (e) {
    root.innerHTML = `<div class="wrap"><div class="loading">Failed to load Robinhood: ${esc(String(e))}</div></div>`;
  }
}

function fxUsd(v) {
  if (v == null) return "–";
  const cls = v > 0 ? "pos" : v < 0 ? "neg" : "";
  return `<span class="${cls}">${v >= 0 ? "+" : "−"}$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>`;
}

function fxDeepDive(bt) {
  const cities = (bt.cities || []).filter(c => c.detail);
  if (!cities.length) return "";
  const c = cities.find(x => x.station === FX_CITY) || cities[0];
  const d = c.detail;

  const tabs = `<div class="seg">` + cities.map(x =>
    `<button class="${x.station === c.station ? "on" : ""}" ` +
    `onclick="fxSelectCity('${esc(x.station)}')">${esc(x.name)}</button>`).join("") + `</div>`;

  // A t below ~2 is not distinguishable from luck; 9 cities were screened, so
  // the honest family-wise bar is nearer 2.9 than 2.0.
  const tCell = (t) => t == null ? `<td>–</td>`
    : `<td class="${t >= 2.9 ? "pos" : t >= 2 ? "" : "neg"}">${t.toFixed(2)}</td>`;
  const halfRows = [{ ...d.overall, label: "OOS overall", from: c.oos_from, to: c.window_end }]
    .concat(d.halves).map(h =>
      `<tr><td class="l">${esc(h.label)}</td>` +
      `<td style="color:var(--text-lo);font-size:11px">${esc(h.from)} → ${esc(h.to)}</td>` +
      `<td>${h.days}</td><td>${fxUsd(h.net_usd)}</td>` +
      `<td>${h.sharpe == null ? "–" : h.sharpe.toFixed(2)}</td>${tCell(h.tstat)}</tr>`).join("");

  const con = d.concentration;
  const bar = (pct) =>
    `<div style="background:var(--line);height:6px;border-radius:3px;overflow:hidden">` +
    `<div style="width:${Math.min(100, pct || 0)}%;height:100%;background:${(pct || 0) >= 75 ? "var(--neg)" : "var(--accent,#6ea8fe)"}"></div></div>`;
  const conRows = [["top 1 day", con.top1], ["top 3 days", con.top3],
                   ["top 5 days", con.top5], ["top 10 days", con.top10]].map(([k, v]) =>
    `<tr><td class="l">${k}</td><td>${v == null ? "–" : v.toFixed(1) + "%"}</td>` +
    `<td style="width:45%">${bar(v)}</td></tr>`).join("");

  const bkRows = (d.buckets || []).map(b =>
    `<tr><td class="l">${esc(b.band)}</td><td>${b.n}</td><td>${b.win_pct.toFixed(1)}%</td>` +
    `<td>${b.avg_cents.toFixed(1)}¢</td><td>${fxUsd(b.net_usd)}</td>` +
    `<td class="${b.share_pct >= 50 ? "pos" : ""}">${b.share_pct == null ? "–" : b.share_pct.toFixed(1) + "%"}</td></tr>`).join("");

  const mech = d.debias === "adds"
    ? `The CLI→WU correction <b>is</b> the edge here — the naive run is materially worse. That is the mechanism we expect and can validate.`
    : d.debias === "irrelevant"
      ? `<span class="neg">Mechanism unknown.</span> The naive run scores the same as rolling45, so this edge does <b>not</b> come from the settlement-basis correction. Less fragile, but unexplained.`
      : `<span class="neg">The fixed debias hurts</span> — this city's basis drifts, so only the rolling offset is safe.`;

  const volNote = d.moneyDayVol == null ? "" :
    `Money days are ${d.moneyDayVol >= (d.otherDayVol || 0) * 0.8 ? "<b>as liquid</b> as" : "<span class=\"neg\">thinner</span> than"} ` +
    `the rest — median <b>${d.moneyDayVol.toLocaleString()}</b> on the traded strike vs ` +
    `${(d.otherDayVol || 0).toLocaleString()} on quiet days.`;

  return `<div class="panel"><div class="panel-h"><h3>Robustness — ${esc(c.name)}</h3>` +
    `<span class="meta">rolling45, the config we would actually trade · held-out window only</span></div>` +
    `<div style="padding:12px 28px 4px;display:flex;gap:6px;flex-wrap:wrap">${tabs}</div>` +
    `<div class="grid g-2" style="padding:10px 28px 6px;gap:18px">` +
      `<div><div style="font:600 11px/1 var(--mono);color:var(--text-lo);text-transform:uppercase;letter-spacing:.06em;padding:6px 0 8px">Does it hold in both halves?</div>` +
      `<table class="dt"><thead><tr><th class="l">Window</th><th></th><th>Days</th><th>Net</th><th>Sharpe</th><th>t</th></tr></thead>` +
      `<tbody>${halfRows}</tbody></table></div>` +
      `<div><div style="font:600 11px/1 var(--mono);color:var(--text-lo);text-transform:uppercase;letter-spacing:.06em;padding:6px 0 8px">How concentrated is the P&L?</div>` +
      `<table class="dt"><thead><tr><th class="l">Share of net from</th><th>%</th><th></th></tr></thead>` +
      `<tbody>${conRows}</tbody></table>` +
      `<div style="padding:6px 0;color:var(--text-lo);font-size:11.5px">` +
      `${con.positiveDays}/${con.days} days positive (${(100 * con.positiveDays / con.days).toFixed(0)}%)</div></div>` +
    `</div>` +
    `<div style="padding:4px 28px 6px"><div style="font:600 11px/1 var(--mono);color:var(--text-lo);text-transform:uppercase;letter-spacing:.06em;padding:6px 0 8px">Which entry prices carry it?</div>` +
    `<table class="dt"><thead><tr><th class="l">Paid</th><th>Trades</th><th>Win%</th><th>Avg/ct</th><th>Net</th><th>Share of P&L</th></tr></thead>` +
    `<tbody>${bkRows}</tbody></table></div>` +
    `<div style="padding:8px 28px 18px;color:var(--text-lo);font-size:11.5px;line-height:1.7">` +
    `${mech}<br>${volNote}<br>` +
    `<b>t</b> = Sharpe × √(days/252) — annualized Sharpe flatters a short window. ` +
    `Nine cities were screened, so a family-wise 5% bar is ≈2.9, not 2.0.</div></div>`;
}

// ====================================================================
// ROBINHOOD TAB — the manual-entry surface.
// Robinhood Derivatives routes weather event contracts to ForecastEX, so every
// number here comes from our own ForecastEx collector (verified tick-for-tick
// on 2026-08-31). Robinhood's web pages are VIEW-ONLY — the order itself is
// typed into the phone app, which is why the ticket below is sized to be read
// across a desk.
// ====================================================================
const RH_RAMP = ["var(--cold)", "var(--cool)", "var(--temperate)", "var(--warm)", "var(--hot)", "var(--extreme)"];

// Decision time is a wall-clock UTC instant on the event date; the strategy was
// validated at that instant, so the tab says plainly whether it has passed.
function rhWhen(dateStr, hhmm) {
  if (!dateStr || !hhmm) return { text: "–", cls: "muted" };
  const [h, m] = hhmm.split(":").map(Number);
  const at = new Date(`${dateStr}T00:00:00Z`);
  at.setUTCHours(h, m, 0, 0);
  const mins = Math.round((at - new Date()) / 60000);
  const local = at.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const span = (v) => v >= 60 ? `${Math.floor(v / 60)}h ${v % 60}m` : `${v}m`;
  if (mins > 0) return { text: `${local} local · in ${span(mins)}`, cls: "pos" };
  return { text: `${local} local · ${span(-mins)} ago`, cls: "muted" };
}

function rhPick(p, city) {
  const side = p.side === "yes" ? "YES" : "NO";
  // The Robinhood app quotes each rung from the YES side, so a NO limit of 28c
  // is entered against a YES book showing 72c. Print both to kill that mistake.
  const otherSide = 100 - p.limit;
  const drift = p.drift == null ? "" :
    ` · <span class="${p.drift >= 0 ? "pos" : "neg"}">${p.drift >= 0 ? "+" : "−"}${Math.abs(p.drift)}¢</span> since`;
  // The market has repriced materially since the decision snapshot; the edge
  // the size was computed from is not the edge on offer now.
  const moved = p.drift != null && Math.abs(p.drift) >= 10;
  return `<div class="rh-card${moved ? " moved" : ""}">
    <div class="rh-head">
      <span class="rh-strike">&gt; ${p.strike}°F</span>
      <span class="rh-side ${p.side}">BUY ${side}</span>
      <span class="tag-pill">${esc(p.ticker)}</span>
    </div>
    <div class="rh-order"><b>${p.contracts.toLocaleString()}</b> contracts &nbsp;·&nbsp; limit <b>${p.limit}¢</b>
      <span style="color:var(--text-lo);font-size:12px">(${side} side; the YES quote reads ${side === "NO" ? otherSide : p.limit}¢)</span></div>
    <div class="rh-meta">
      cost <b style="color:var(--text-mid)">$${p.costUsd.toFixed(2)}</b> · max loss $${p.maxLossUsd.toFixed(2)} · max win $${p.maxWinUsd.toFixed(2)} · fee $${p.feeUsd.toFixed(2)}<br>
      model ${(p.pModel * 100).toFixed(0)}% · market implies ${p.lastPx}% &nbsp;${edgeCell(p.edge)}<br>
      decision mark ${p.entry}¢ · now ${p.currentEntry == null ? "–" : p.currentEntry + "¢"}${drift}
      <span style="color:var(--text-faint)">${p.currentAt ? esc(p.currentAt.slice(11, 16)) + "Z" : ""}</span>
    </div>
    ${city.rhUrl ? `<a class="rh-btn" href="${esc(city.rhUrl)}" target="_blank" rel="noopener noreferrer">Open ${esc(city.name)} on Robinhood ↗</a>` : ""}
  </div>`;
}

// Same six-column .rung grid as the Kalshi bracket ladder, so no new CSS: the
// last column carries the CURRENT price instead of a resolution.
function rhLadder(city) {
  const rows = (city.ladder || []);
  if (!rows.length) return "";
  const lo = rows[0].strike, span = (rows[rows.length - 1].strike - lo) || 1;
  const body = [...rows].reverse().map((r, k) => {
    const tc = RH_RAMP[Math.round(((r.strike - lo) / span) * (RH_RAMP.length - 1))];
    const fires = Math.abs(r.edge) >= city.edgeThreshold;
    const fill = Math.max(0, Math.min(100, r.pModel * 100));
    const mkt = Math.max(0, Math.min(100, r.decisionPx));
    const sig = r.pick
      ? `<span class="side ${r.pick}">BUY ${r.pick.toUpperCase()}</span>`
      : fires ? `<span class="muted" title="clears the edge threshold but was filtered: price outside 5–95¢, entry under the city minimum, or ranked below the day's max picks">filtered</span>` : `<span class="muted">—</span>`;
    const moved = r.currentPx != null && r.currentPx !== r.decisionPx;
    return `<div class="rung${r.pick ? " fires" : ""}" style="--tc:${tc};--ri:${k}">
      <div class="rung-label"><span class="rung-dot"></span>&gt; ${r.strike}°F</div>
      <div class="rung-track" title="model ${fill.toFixed(0)}% · market ${mkt}%"><div class="rung-fill" style="width:${fill.toFixed(1)}%"></div><div class="rung-mkt" style="left:${mkt}%"></div></div>
      <div class="rung-prob">${fill.toFixed(0)}%</div>
      <div class="rung-edge">${edgeCell(r.edge)}</div>
      <div class="rung-sig">${sig}</div>
      <div class="rung-res" style="font:600 12px/1 var(--mono);color:${moved ? "var(--text-hi)" : "var(--text-lo)"}">${r.currentPx == null ? "–" : r.currentPx + "¢"}</div>
    </div>`;
  }).join("");
  return `<div class="ladder">
    <div class="rung rung-head"><div class="rung-label">Threshold</div><div class="rung-track-h">model P · ▮ market at decision</div><div class="rung-prob">P</div><div class="rung-edge">Edge</div><div class="rung-sig">Signal</div><div class="rung-res">Now</div></div>
    ${body}</div>`;
}

function rhToday(tr) {
  if (!tr || !tr.available) {
    return `<div class="panel"><div class="panel-h"><h3>Today's trades</h3><span class="meta">unavailable</span></div>` +
      `<div style="padding:14px 28px 22px;color:var(--text-lo);font-size:12.5px;font-family:var(--mono)">${esc((tr && tr.error) || "no payload")}</div></div>`;
  }
  const cards = (tr.cities || []).map(c => {
    const when = rhWhen(tr.date, c.decisionUtc);
    const head = `<div class="panel-h"><h3>${esc(c.name)} — daily high</h3>` +
      `<span class="meta">${esc(c.product)} · decision ${esc(c.decisionUtc)}Z · <span class="rh-when ${when.cls}">${esc(when.text)}</span>` +
      `${c.mu != null ? ` · model ${c.mu.toFixed(1)}°F ±${c.sigma.toFixed(2)} (basis ${c.offset >= 0 ? "+" : "−"}${Math.abs(c.offset).toFixed(2)})` : ""}</span></div>`;
    const warn = c.warning
      ? `<div style="padding:10px 28px 0"><span class="pill-status halt">HEADS UP</span> <span style="color:var(--text-lo);font-size:12px">${esc(c.warning)}</span></div>` : "";
    const body = c.picks.length
      ? `<div style="padding:14px 28px 4px;display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(330px,1fr))">${c.picks.map(p => rhPick(p, c)).join("")}</div>`
      : `<div style="padding:16px 28px 6px;color:var(--text-lo);font-size:12.5px;font-family:var(--mono)">` +
        `No trade — nothing cleared the ${(c.edgeThreshold * 100).toFixed(0)}% edge threshold. ${esc(c.note || "")}` +
        `${c.rhUrl ? `<br><a class="rh-btn" style="margin-top:12px" href="${esc(c.rhUrl)}" target="_blank" rel="noopener noreferrer">View ${esc(c.name)} on Robinhood ↗</a>` : ""}</div>`;
    const foot = `<div style="padding:10px 28px 16px;color:var(--text-faint);font-size:11.5px;line-height:1.6">` +
      `Size = ${tr.maxContracts} contracts/day split evenly, then capped at this city's measured capacity ` +
      `(${c.capacity == null ? "unknown" : c.capacity.toLocaleString()}). Limit sits half the measured spread ` +
      `(${c.spreadCents == null ? "–" : c.spreadCents.toFixed(2) + "¢"}) inside the last print — it is a POST, so it may not fill.</div>`;
    return `<div class="panel">${head}${warn}${body}${foot}${rhLadder(c)}</div>`;
  }).join("");

  const hoursPanel =
    `<div class="panel"><div class="panel-h"><h3>Placing the order</h3>` +
    `<span class="meta">web is view-only · trade in the Robinhood app</span></div>` +
    `<div style="padding:14px 28px 20px;font-size:12.5px;color:var(--text-lo);line-height:1.75">` +
    `<b style="color:var(--text-mid)">Trading hours:</b> ${esc(tr.tradingHours)}.<br>` +
    `<b style="color:var(--text-mid)">Settlement:</b> Weather Underground's station high — the same source ForecastEx uses, ` +
    `and <i>not</i> the NWS CLI report Kalshi settles on.<br>` +
    `<b style="color:var(--text-mid)">Fee assumption:</b> ${tr.feeCents.toFixed(0)}¢/contract/side, taken from ForecastEx's schedule. ` +
    `Robinhood may add its own — check a settled statement and correct FEE_CENTS_PER_CONTRACT if it differs.<br>` +
    `<b style="color:var(--text-mid)">Order type:</b> resting limit. The backtest's edge assumes posting, not crossing; ` +
    `paying the spread costs roughly a third of the measured t-stat.</div></div>`;

  const b = FX_DATA.broker || {};
  const brokerPanel =
    `<div class="panel"><div class="panel-h"><h3>Account</h3>` +
    `<span class="pill-status halt">NOT LINKED</span></div>` +
    `<div style="padding:14px 28px 8px;font-family:var(--mono);font-size:13px;line-height:1.9">` +
    `Bankroll (entered by hand): <b>$${tr.bankroll.toLocaleString(undefined, { minimumFractionDigits: 2 })}</b><br>` +
    `Day's budget: <b>${tr.maxContracts}</b> contracts</div>` +
    `<div style="padding:4px 28px 20px;font-size:12.5px;color:var(--text-lo);line-height:1.65">` +
    `<b style="color:var(--text-mid)">${esc(b.headline || "")}</b> ${esc(b.detail || "")}</div></div>`;

  return cards + `<div class="grid g-2">${hoursPanel}${brokerPanel}</div>`;
}

function renderForecastEx() {
  const root = document.getElementById("forecastex-root");
  if (!FX_DATA) { root.innerHTML = `<div class="wrap"><div class="loading">Loading Robinhood…</div></div>`; return; }
  const col = FX_DATA.collector, bt = FX_DATA.backtest, basis = FX_DATA.basis;

  // --- collector health -----------------------------------------------------
  const stale = col.staleMinutes;
  const pill = stale == null ? `<span class="pill-status halt">NO DATA</span>`
    : stale <= 30 ? `<span class="pill-status ok">COLLECTING</span>`
    : `<span class="pill-status halt">STALE ${stale}m</span>`;
  const collectorPanel =
    `<div class="panel"><div class="panel-h"><h3>Public data collector</h3>` +
    `<span class="meta">${pill} · no auth / no IBKR needed · every 10 min · ${col.cities} mapped cities</span></div>` +
    `<div style="padding:14px 28px 20px;font-family:var(--mono);font-size:13px;line-height:1.9">` +
    `Ticks last 24h: <b>${col.ticks24h.toLocaleString()}</b><br>` +
    `Contracts tracked: <b>${col.contracts.toLocaleString()}</b><br>` +
    `Coverage: <b>${esc(col.firstDay || "–")}</b> → <b>${esc(col.lastDay || "–")}</b><br>` +
    `<span style="color:var(--text-lo);font-size:11.5px">Last tick ${esc(col.lastTickAt || "–")}</span></div></div>`;

  // --- the basis warning (gates every number below) -------------------------
  const offRows = (basis.offsets || []).map(o =>
    `<tr><td class="l">${esc(o.code)}</td><td>${o.offset > 0 ? "+" : "−"}${Math.abs(o.offset).toFixed(2)}°F</td></tr>`).join("");
  const basisPanel =
    `<div class="panel"><div class="panel-h"><h3>⚠ Settlement basis</h3>` +
    `<span class="meta">${esc(basis.headline)}</span></div>` +
    `<div style="padding:12px 28px 4px;font-size:12.5px;color:var(--text-lo);line-height:1.65">${esc(basis.detail)}</div>` +
    `<div style="padding:8px 28px 4px;font-size:12.5px;color:var(--text-lo);line-height:1.65">${esc(basis.correlation)}</div>` +
    `<div class="tbl-scroll" style="max-height:220px"><table class="dt"><thead><tr>` +
    `<th class="l">City</th><th>CLI→WU offset</th></tr></thead><tbody>${offRows}</tbody></table></div></div>`;

  // --- backtest -------------------------------------------------------------
  let btPanel;
  if (!bt.available) {
    btPanel = `<div class="panel"><div class="panel-h"><h3>Backtest</h3><span class="meta">not generated yet</span></div>` +
      `<div style="padding:14px 28px 22px;color:var(--text-lo);font-size:12.5px;font-family:var(--mono)">${esc(bt.note || "")}</div></div>`;
  } else {
    const v = (c, k) => (c.variants || {})[k] || {};
    const cell = (x) => x.n == null ? `<td>–</td><td>–</td>` :
      `<td>${fxUsd(x.net_usd)}</td><td>${x.sharpe == null ? "–" : x.sharpe.toFixed(2)}</td>`;
    const rows = (bt.cities || []).map(c => {
      const roll = v(c, "rolling45");
      const thin = c.settled_events < 40 || (roll.no_print_days || 0) > 5;
      return `<tr><td class="l">${esc(c.name)}${thin ? ` <span style="color:var(--text-lo)">·thin</span>` : ""}</td>` +
        `<td>${c.settled_events}</td><td>${roll.n ?? "–"}</td>` +
        `<td>${roll.win_pct == null ? "–" : roll.win_pct.toFixed(1) + "%"}</td>` +
        cell(v(c, "naive")) + cell(v(c, "debiased")) + cell(roll) +
        `<td>${c.offset_f > 0 ? "+" : "−"}${Math.abs(c.offset_f).toFixed(2)}</td></tr>`;
    }).join("");
    const age = bt.ageHours == null ? "" : ` · generated ${bt.ageHours < 1 ? "just now" : bt.ageHours.toFixed(0) + "h ago"}`;
    btPanel =
      `<div class="panel"><div class="panel-h"><h3>Backtest — 500 contracts, edge≥10%, 1¢/contract fee</h3>` +
      `<span class="meta">out-of-sample 2nd half · priced on last tick at the decision time · settled vs ForecastEx's OWN (WU) value${esc(age)}</span></div>` +
      `<div class="tbl-scroll"><table class="dt"><thead><tr>` +
      `<th class="l">City</th><th>Events</th><th>n</th><th>Win%</th>` +
      `<th>naive $</th><th>Sh</th><th>fixed $</th><th>Sh</th><th>roll45 $</th><th>Sh</th><th>offset</th>` +
      `</tr></thead><tbody>${rows}</tbody></table></div>` +
      `<div style="padding:8px 28px 18px;color:var(--text-lo);font-size:11.5px;line-height:1.6">` +
      `<b>rolling45</b> is the config to read — a fixed offset over-corrects cities whose basis drifts (LA, Austin). ` +
      `<b>No fill model:</b> ForecastEx publishes no public order book, so spread and slippage are unmodeled and these are optimistic.</div></div>`;
  }

  // --- capacity (PER STRIKE, not per city) ---------------------------------
  const capRows = (FX_DATA.capacity || []).map(l => {
    const verdict = l.suggested === 0
      ? `<span class="neg">untradeable</span>`
      : l.oversizedBy && l.oversizedBy >= 2
        ? `<span class="neg">${l.oversizedBy}× oversized</span>`
        : `<span class="pos">headroom</span>`;
    return `<tr><td class="l">${esc(l.name)}</td><td class="l">${esc(l.product)}</td><td>${esc(l.decisionUtc)}</td>` +
      `<td>${l.medianVol.toLocaleString()}</td><td>${l.p25Vol.toLocaleString()}</td><td>${l.p10Vol.toLocaleString()}</td>` +
      `<td>${l.zeroVolPicks}</td><td><b>${l.suggested.toLocaleString()}</b></td><td>${verdict}</td></tr>`;
  }).join("");
  const liqPanel =
    `<div class="panel"><div class="panel-h"><h3>Capacity — volume on the strike we actually trade</h3>` +
    `<span class="meta">2h before the decision · PER STRIKE, not city-wide · suggested = half the thin-day (p25) volume</span></div>` +
    `<div class="tbl-scroll"><table class="dt"><thead><tr><th class="l">City</th><th class="l">Product</th><th>Decision</th>` +
    `<th>Median</th><th>p25</th><th>p10</th><th>0-vol picks</th><th>Suggested size</th><th>vs backtest 500</th></tr></thead>` +
    `<tbody>${capRows}</tbody></table></div>` +
    `<div style="padding:8px 28px 18px;color:var(--text-lo);font-size:11.5px;line-height:1.6">` +
    `City-wide volume is <b>misleading</b> — it aggregates ~30 strikes, but a signal is one strike. ` +
    `Miami's city median is ~2,100/2h yet its traded-strike median is ~240, so the backtest's 500-lot is ~10× too big there. ` +
    `LA is the only city with genuine depth. No order book is published, so these are realized-volume lower bounds — ` +
    `only live orders settle true depth.</div></div>`;

  const deepPanel = bt.available ? fxDeepDive(bt) : "";

  root.innerHTML = `<div class="wrap"><div class="grid" style="gap:14px">` +
    rhToday(FX_DATA.trading) +
    `<div class="grid g-2">${collectorPanel}${basisPanel}</div>` +
    `${btPanel}${deepPanel}${liqPanel}</div></div>`;
}

async function init() {
  await loadCities();
  loadLive();
  startLivePolling();
  setInterval(tickClocks, 1000);
  tickClocks();
  loadBacktest();   // prefetch default city so the backtest tab is instant
}
document.addEventListener("DOMContentLoaded", init);
