"use strict";
/* =====================================================================
   weather · kalshi trading desk — vanilla frontend (zero build)
   Talks to the FastAPI JSON API (dashboard/app.py). Render functions build
   HTML strings → innerHTML; state lives in module globals; the backtest sim
   runs entirely client-side (jsComputeSim, ported verbatim from the former
   React app.jsx so tests/test_sim_parity.py stays green).
   ===================================================================== */

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
  const c = color || (last >= 0 ? "var(--pos)" : "var(--neg)");
  const gid = "sg" + (++_uid);
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c}" stop-opacity="0.22"/><stop offset="1" stop-color="${c}" stop-opacity="0"/></linearGradient></defs><path d="${area}" fill="url(#${gid})"/><path d="${line}" fill="none" stroke="${c}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}

function pnlChartSVG(data) {
  if (!data || data.length < 2) return `<div class="loading">No P&amp;L series.</div>`;
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
  const c = last >= 0 ? "var(--pos)" : "var(--neg)";
  const line = data.map((d, i) => `${i === 0 ? "M" : "L"}${X(i).toFixed(1)},${Y(d.v).toFixed(1)}`).join(" ");
  const area = `${line} L${X(data.length - 1)},${zeroY} L${X(0)},${zeroY} Z`;
  const dayLabels = ["6d", "5d", "4d", "3d", "2d", "1d", "yest", "today"];
  const grid = tickVals.map(tv =>
    `<line x1="${padL}" x2="${padL + iw}" y1="${Y(tv)}" y2="${Y(tv)}" stroke="var(--border)" stroke-width="1" stroke-dasharray="${Math.abs(tv) < 1e-6 ? "0" : "2 4"}"/><text x="${padL + iw + 8}" y="${Y(tv) + 3.5}" fill="var(--text-faint)" style="font:500 10px var(--mono)">${(tv >= 0 ? "" : "−") + "$" + Math.abs(Math.round(tv))}</text>`).join("");
  const xlab = data.map((d, i) => `<text x="${X(i)}" y="${height - 8}" text-anchor="middle" fill="var(--text-faint)" style="font:500 9.5px var(--mono)">${dayLabels[i] || i}</text>`).join("");
  return `<svg width="${w}" height="${height}" viewBox="0 0 ${w} ${height}"><defs><linearGradient id="pnlfill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c}" stop-opacity="0.20"/><stop offset="1" stop-color="${c}" stop-opacity="0.01"/></linearGradient></defs>${grid}<line x1="${padL}" x2="${padL + iw}" y1="${zeroY}" y2="${zeroY}" stroke="var(--border-strong)" stroke-width="1"/><path d="${area}" fill="url(#pnlfill)"/><path d="${line}" fill="none" stroke="${c}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>${xlab}</svg>`;
}

function ensembleChartSVG(d) {
  const w = 760, height = 248;
  if (!d.members || d.members.length === 0)
    return `<div style="padding:24px;color:var(--text-lo);text-align:center">No ensemble data for ${esc(d.date)}.</div>`;
  const padL = 16, padR = 16, padT = 16, padB = 30;
  const iw = w - padL - padR, ih = height - padT - padB;
  const lo = Math.floor(Math.min(...d.members, d.observed || d.ensMean) - 1.5);
  const hi = Math.ceil(Math.max(...d.members, d.observed || d.ensMean) + 1.5);
  const X = t => padL + ((t - lo) / (hi - lo)) * iw;
  const bins = {};
  for (let t = lo; t <= hi; t++) bins[t] = 0;
  d.members.forEach(m => { const b = Math.round(m); if (bins[b] !== undefined) bins[b]++; });
  const maxCount = Math.max(...Object.values(bins), 1);
  const barW = iw / (hi - lo) * 0.82;
  const pdfPeak = (d.emosSigma > 0) ? normPdf(d.emosMu, d.emosMu, d.emosSigma) : 1;
  let curve = "";
  if (d.emosSigma > 0) {
    const pts = [];
    for (let i = 0; i <= 80; i++) {
      const t = lo + (hi - lo) * (i / 80);
      const yv = (normPdf(t, d.emosMu, d.emosSigma) / pdfPeak) * (maxCount * 0.92);
      pts.push(`${i === 0 ? "M" : "L"}${X(t).toFixed(1)},${(padT + ih - (yv / maxCount) * ih).toFixed(1)}`);
    }
    curve = `<path d="${pts.join(" ")}" fill="none" stroke="var(--warn)" stroke-width="2"/>`;
  }
  const boundaries = [...new Set((d.brackets || []).flatMap(b => [b.lo, b.hi]).filter(v => v > lo && v < hi && Math.abs(v) < 90))];
  const bnd = boundaries.map(bv => `<line x1="${X(bv + 0.5)}" x2="${X(bv + 0.5)}" y1="${padT}" y2="${padT + ih}" stroke="var(--border)" stroke-width="1" stroke-dasharray="2 4"/>`).join("");
  const bars = Object.entries(bins).map(([t, c]) => c > 0 ? `<rect x="${X(+t) - barW / 2}" y="${padT + ih - (c / maxCount) * ih}" width="${barW}" height="${(c / maxCount) * ih}" rx="1.5" fill="var(--bg-3)"/>` : "").join("");
  const mean = d.ensMean > 0 ? `<line x1="${X(d.ensMean)}" x2="${X(d.ensMean)}" y1="${padT}" y2="${padT + ih}" stroke="var(--text-lo)" stroke-width="1" stroke-dasharray="3 3"/>` : "";
  let obs = "";
  if (d.observed > 0) {
    obs = `<line x1="${X(d.observed)}" x2="${X(d.observed)}" y1="${padT - 2}" y2="${padT + ih}" stroke="var(--pos)" stroke-width="2"/><g transform="translate(${Math.min(X(d.observed) + 6, padL + iw - 70)},${padT + 4})"><rect width="64" height="18" rx="4" fill="var(--pos-dim)" stroke="var(--pos-line)"/><text x="7" y="13" fill="var(--pos)" style="font:600 10px var(--mono)">obs ${d.observed}°</text></g>`;
  }
  const xlab = Array.from({ length: hi - lo + 1 }, (_, i) => lo + i).filter(t => t % 2 === 0).map(t => `<text x="${X(t)}" y="${height - 9}" text-anchor="middle" class="chart-axis-x">${t}°</text>`).join("");
  return `<svg width="${w}" height="${height}" viewBox="0 0 ${w} ${height}">${bnd}${bars}${curve}${mean}${obs}${xlab}</svg>`;
}

function balanceChartSVG(curve, filledTrades) {
  const w = 720, height = 300;
  if (!curve || curve.length < 2) return `<div style="padding:24px;color:var(--text-lo);text-align:center">No simulation curve.</div>`;
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
  const c = last >= start ? "var(--pos)" : "var(--neg)";
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
  return `<svg width="${w}" height="${height}" viewBox="0 0 ${w} ${height}"><defs><linearGradient id="balfill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c}" stop-opacity="0.16"/><stop offset="1" stop-color="${c}" stop-opacity="0.01"/></linearGradient></defs>${grid}<line x1="${padL}" x2="${padL + iw}" y1="${Y(start)}" y2="${Y(start)}" stroke="var(--border-strong)" stroke-width="1.5"/><text x="${padL + iw + 8}" y="${Y(start) - 4}" fill="var(--text-lo)" style="font:600 9.5px var(--mono)">start</text><path d="${line} L${X(curve.length - 1)},${Y(min)} L${X(0)},${Y(min)} Z" fill="url(#balfill)"/><path d="${line}" fill="none" stroke="${c}" stroke-width="2" stroke-linejoin="round"/>${xlab}</svg>`;
}

function edgeCell(edge) {
  const positive = edge >= 0;
  const w = Math.min(100, Math.abs(edge) / 0.4 * 100);
  return `<span class="edge-cell"><span class="${positive ? "pos" : "neg"}">${(edge >= 0 ? "+" : "−") + (Math.abs(edge) * 100).toFixed(0) + "%"}</span><span class="edge-bar"><span style="width:${w / 2}%;${positive ? "left" : "right"}:50%;background:${positive ? "var(--pos)" : "var(--neg)"}"></span></span></span>`;
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
function kalshiFeeCents(entry) {
  if (entry <= 0 || entry >= 100) return 0;
  const p = entry / 100;
  return Math.max(1, Math.ceil(0.07 * p * (1 - p) * 100));
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
    const feePer = kalshiFeeCents(entry) / 100;
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
let BT = null;            // current city's backtest payload
let BT_CITIES = [];       // [{code,label}]
let activeTab = "live";
let liveTimer = null;
const autoedCities = new Set();
const bt = {              // backtest control state
  platform: "Kalshi", cityCode: null, date: null,
  strategy: "raw", bracketEdge: 0.10, simEdge: 0.10, minEntry: 0,
  sizing: "unit", amount: 500, depth: 500, exec: "market",
  bankroll: 3000, maxSignals: 0, edgeCap: 0,
};

// ====================================================================
// LIVE TAB render functions
// ====================================================================
function liveHero(d) {
  const t = d.today, c = d.cumulative;
  return `<div class="hero">
    <div>
      <div class="k">Today's P&amp;L</div>
      <div class="v ${cls(t.total)}">${money(t.total)}</div>
      <div class="sub"><span>realized <b class="${cls(t.realized)}">${money(t.realized)}</b></span><span>unrealized <b class="${cls(t.unrealized)}">${money(t.unrealized)}</b></span><span><b>${t.trades}</b> trades · <b>${t.open}</b> open</span></div>
    </div>
    <div>
      <div class="k">Cumulative P&amp;L <span class="tag-pill">since first live trade</span></div>
      <div class="v ${cls(c.total)}">${money(c.total)}</div>
      <div class="sub"><span>return <b class="${cls(c.returnPct)}">${pct(c.returnPct)}</b></span><span>win rate <b>${(c.winRate * 100).toFixed(0)}%</b></span><span><b>${c.nSettled}</b> settled</span></div>
      <div class="spark">${sparkSVG(d.series)}</div>
    </div>
    <div>
      <div class="k">Account balance</div>
      <div class="v sm" style="color:var(--text-hi)">${moneyPlain(d.balance)}</div>
      <div class="sub"><span>cash <b>${moneyPlain(d.cashBalance)}</b></span><span>portfolio <b>${moneyPlain(d.portfolioValue)}</b></span></div>
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

function statusStrip(d) {
  const killOk = d.killArmed;
  const liveCities = d.cities.filter(c => c.status === "active").length;
  return `<div class="status-strip">
    <div class="chip"><span class="ico ${killOk ? "ok" : "err"}"></span><span class="txt"><span class="l">Kill switch</span><span class="d" style="color:${killOk ? "var(--pos)" : "var(--neg)"}">${killOk ? "ARMED" : "TRIGGERED"}</span></span></div>
    <div class="chip"><span class="ico ${d.nextCron.inMin === null ? "err" : "ok"}"></span><span class="txt"><span class="l">Next cron · ${esc(d.nextCron.label)}</span><span class="d">${esc(d.nextCron.at)} ${d.nextCron.inMin !== null ? `<small>· in <span id="cron-countdown">${formatCountdown(d)}</span></small>` : ""}</span></span></div>
    <div class="chip"><span class="ico ${d.openOrders.count > 0 ? "ok" : ""}"></span><span class="txt"><span class="l">Open orders</span><span class="d">${d.openOrders.count} resting <small>· ${d.openOrders.contracts.toLocaleString()} contracts</small></span></span></div>
    <div class="chip"><span class="ico ${d.hrrr.status === "ok" ? "ok" : "warn"}"></span><span class="txt"><span class="l">HRRR data</span><span class="d" style="color:${d.hrrr.status === "ok" ? "var(--text-hi)" : "var(--warn)"}">${d.hrrr.status === "ok" ? "fresh" : "stale"} <small>· ${esc(d.hrrr.age)} ago</small></span></span></div>
    <div class="chip"><span class="ico ok"></span><span class="txt"><span class="l">Positions</span><span class="d">${d.positions.length} open <small>· ${liveCities}/${d.cities.length} cities live</small></span></span></div>
  </div>`;
}

function killBanner(d) {
  if (d.killArmed) return "";
  return `<div class="alert"><span class="bang">⛔</span><div class="body"><div class="t">Kill switch triggered — all trading halted</div><div class="d">${esc(d.killReason || "Cumulative drawdown breached the aggregate kill threshold.")}</div></div><span class="ts">${esc(d.asOf || "")}</span></div>`;
}

function riskBar(name, used, limit) {
  const r = Math.min(1, limit ? used / limit : 0);
  const lvl = r >= 0.8 ? "err" : r >= 0.5 ? "warn" : "ok";
  return `<div class="riskrow"><div class="rl"><span class="name">${esc(name)}</span><span class="val">$${used.toFixed(0)} <span style="color:var(--text-faint)">/ $${limit.toFixed(0)}</span></span></div><div class="bar"><span class="${lvl}" style="width:${(r * 100).toFixed(0)}%"></span></div></div>`;
}

function dialHTML(used, limit) {
  const r = Math.min(1, limit ? used / limit : 0);
  const pctv = Math.round(r * 100);
  const col = r >= 0.8 ? "var(--neg)" : r >= 0.5 ? "var(--warn)" : "var(--dial)";
  return `<span class="dial" title="${pctv}% of cumulative kill used" style="background:conic-gradient(${col} ${pctv}%, var(--bg-3) 0)"><span class="inner">${pctv}%</span></span>`;
}

function cityCard(c) {
  return `<div class="panel city">
    <div class="ch"><span class="nm">${esc(c.name)}</span><span class="code">${esc(c.code)}</span><span class="badge ${c.status === "active" ? "active" : "halted"}">${esc(c.status)}</span>${dialHTML(c.risk.cumUsed, c.risk.cumKill)}<span class="model">${esc(c.model)}</span></div>
    <div class="cbody">
      <div class="m"><div class="ml">Realized</div><div class="mv ${cls(c.realized)}">${money(c.realized)}</div><div class="ms">settled</div></div>
      <div class="m"><div class="ml">Unrealized</div><div class="mv ${cls(c.unrealized)}">${money(c.unrealized)}</div><div class="ms">open mark</div></div>
      <div class="m"><div class="ml">Today</div><div class="mv ${cls(c.today)}">${money(c.today)}</div><div class="ms">${c.orders} orders</div></div>
    </div>
    <div class="cfoot">${c.haltNote ? `<div class="halt-note">${esc(c.haltNote)}</div>` : `<div class="activity"><span>budget <b>$${c.budget}</b></span><span><b>${c.contracts.toLocaleString()}</b> contracts</span><span>edge ≥ <b>${esc(c.edgeThresh)}</b></span><span>size <b>${esc(c.stake)}</b></span></div>`}${riskBar("Cumulative", c.risk.cumUsed, c.risk.cumKill)}${riskBar("Today", c.risk.todayUsed, c.risk.todayKill)}</div>
  </div>`;
}

function aggRisk(d) {
  const a = d.agg;
  const cumUsed = a.cumPnl < 0 ? Math.abs(a.cumPnl) : 0;
  const todayUsed = a.todayPnl < 0 ? Math.abs(a.todayPnl) : 0;
  const lvl = (u, k) => (k && u / k >= 0.8) ? "err" : (k && u / k >= 0.5) ? "warn" : "ok";
  return `<div class="panel" style="display:flex;flex-direction:column"><div class="panel-h"><h3>Aggregate risk envelope</h3><span class="meta">cross-city</span></div>
    <div class="panel-b aggm" style="flex:1">
      <div class="a"><div class="top"><span class="lbl">Cumulative drawdown</span><span class="num ${cls(a.cumPnl)}">${money(a.cumPnl)}</span></div><div class="bar"><span class="${lvl(cumUsed, a.cumKill)}" style="width:${Math.min(100, a.cumKill ? cumUsed / a.cumKill * 100 : 0)}%"></span></div><span class="cap">kill at −$${a.cumKill} · ${(a.cumKill ? cumUsed / a.cumKill * 100 : 0).toFixed(0)}% used</span></div>
      <div class="a"><div class="top"><span class="lbl">Daily loss</span><span class="num ${cls(a.todayPnl)}">${money(a.todayPnl)}</span></div><div class="bar"><span class="${lvl(todayUsed, a.dailyKill)}" style="width:${Math.min(100, a.dailyKill ? todayUsed / a.dailyKill * 100 : 0)}%"></span></div><span class="cap">halt at −$${a.dailyKill} · ${(a.dailyKill ? todayUsed / a.dailyKill * 100 : 0).toFixed(0)}% used</span></div>
      <div class="a"><div class="top"><span class="lbl">Open contracts</span><span class="num">${a.openContracts.toLocaleString()}</span></div><div class="bar"><span class="ok" style="width:${Math.min(100, a.contractCap ? a.openContracts / a.contractCap * 100 : 0)}%"></span></div><span class="cap">cap ${a.contractCap.toLocaleString()} (sum of city caps)</span></div>
    </div>
  </div>`;
}

function positionsTable(rows) {
  const body = rows.length === 0
    ? `<tr><td class="l muted" colspan="8" style="padding:20px 12px">No open positions — all flat.</td></tr>`
    : rows.map(r => `<tr><td class="l hi">${esc(r.ticker)}</td><td class="l">${esc(r.bracket)}</td><td><span class="side ${r.side === "YES" ? "yes" : "no"}">${esc(r.side)}</span></td><td>${r.qty}</td><td>${r.avg}¢</td><td class="hi">${r.mark}¢</td><td class="${cls(r.unreal)}">${money(r.unreal)}</td><td class="${cls(r.unreal)}">${pct(r.unrealPct)}</td></tr>`).join("");
  return `<div class="panel"><div class="panel-h"><h3>Current positions</h3><span class="meta">mark = side-adjusted bid · ${rows.length} open</span></div><div class="tbl-scroll"><table class="dt"><thead><tr><th class="l">Ticker</th><th class="l">Bracket</th><th>Side</th><th>Qty</th><th>Avg</th><th>Mark</th><th>Unreal</th><th>%</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
}

function signalsTable(rows) {
  const body = rows.length === 0
    ? `<tr><td class="l muted" colspan="9" style="padding:18px 12px">No signals logged today.</td></tr>`
    : rows.map(r => `<tr><td class="l hi">${esc(r.ticker)}</td><td class="l">${esc(r.bracket)}</td><td>${(r.modelP * 100).toFixed(0)}%</td><td>${(r.mktP * 100).toFixed(0)}%</td><td>${edgeCell(r.edge)}</td><td><span class="side ${r.side === "YES" ? "yes" : "no"}">BUY ${esc(r.side)}</span></td><td><span class="pill-status ${r.placed === "placed" ? "placed" : "skipped"}">${esc(r.placed)}</span></td><td><span class="pill-status ${esc(r.fill)}">${esc(r.fill)}</span></td><td class="${r.pnl === null ? "muted" : cls(r.pnl)}">${r.pnl === null ? "—" : money(r.pnl)}</td></tr>`).join("");
  return `<div class="panel"><div class="panel-h"><h3>Today's signals → fills</h3><span class="meta">every logged signal · placed? · fill status</span></div><div class="tbl-scroll"><table class="dt"><thead><tr><th class="l">Ticker</th><th class="l">Bracket</th><th>Model P</th><th>Market P</th><th>Edge</th><th>Signal</th><th>Order</th><th>Fill</th><th>P&amp;L</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
}

function ordersTable(rows) {
  const body = rows.length === 0
    ? `<tr><td class="l muted" colspan="7" style="padding:18px 12px">No orders placed today.</td></tr>`
    : rows.map(r => `<tr><td class="l">${esc(r.time)}</td><td class="l hi">${esc(r.ticker)}</td><td><span class="side ${r.side === "YES" ? "yes" : "no"}">${esc(r.side)}</span></td><td>${r.qty}</td><td>${r.limit}¢</td><td class="hi">${r.fillPx === null ? "—" : r.fillPx + "¢"}</td><td><span class="pill-status ${esc(r.status)}">${esc(r.status)}</span></td></tr>`).join("");
  return `<div class="panel"><div class="panel-h"><h3>Today's live orders</h3><span class="meta">live_trades view</span></div><div class="tbl-scroll" style="max-height:240px"><table class="dt"><thead><tr><th class="l">Time</th><th class="l">Ticker</th><th>Side</th><th>Qty</th><th>Limit</th><th>Fill</th><th>Status</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
}

function openOrders(rows) {
  const body = rows.length === 0
    ? `<tr><td class="l muted" colspan="5" style="padding:16px 12px">No resting orders.</td></tr>`
    : rows.map(r => `<tr><td class="l hi">${esc(r.ticker)}</td><td><span class="side ${r.side === "YES" ? "yes" : "no"}">${esc(r.side)}</span></td><td>${r.qty}</td><td>${r.limit}¢</td><td class="muted">${esc(r.age)}</td></tr>`).join("");
  return `<div class="panel"><div class="panel-h"><h3>Open orders on Kalshi</h3><span class="meta">${rows.length} resting</span></div><div class="tbl-scroll" style="max-height:200px"><table class="dt"><thead><tr><th class="l">Ticker</th><th>Side</th><th>Qty</th><th>Limit</th><th>Age</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
}

function recentFills(rows) {
  const body = rows.length === 0
    ? `<tr><td class="l muted" colspan="6" style="padding:16px 12px">No fills in the last 7 days.</td></tr>`
    : rows.map(r => `<tr><td class="l">${esc(r.date)}</td><td class="l hi">${esc(r.ticker)}</td><td><span class="side ${r.side === "YES" ? "yes" : "no"}">${esc(r.side)}</span></td><td>${r.qty}</td><td>${r.px}¢</td><td class="${r.pnl === null ? "muted" : cls(r.pnl)}">${r.pnl === null ? "open" : money(r.pnl)}</td></tr>`).join("");
  return `<div class="panel"><div class="panel-h"><h3>Recent fills (7 days)</h3><span class="meta">${rows.length} fills</span></div><div class="tbl-scroll" style="max-height:200px"><table class="dt"><thead><tr><th class="l">Date</th><th class="l">Ticker</th><th>Side</th><th>Qty</th><th>Px</th><th>Settled P&amp;L</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
}

function cronAlerts(d) {
  const dot = s => s === "ok" ? "var(--pos)" : s === "error" ? "var(--neg)" : "var(--warn)";
  const crons = d.crons.map(c => `<div style="display:flex;align-items:center;gap:10px"><span style="width:8px;height:8px;border-radius:50%;background:${dot(c.status)};flex:none"></span><span class="mono" style="font-size:12px;color:var(--text-hi);min-width:104px">${esc(c.name)}</span><span class="mono" style="font-size:11px;color:var(--text-lo)">${esc(c.last)}</span><span class="mono" style="font-size:11px;color:var(--text-faint);margin-left:auto">${esc(c.desc)}</span></div>`).join("");
  const alerts = d.alerts.map(a => `<div class="logline ${esc(a.lvl)}" style="display:flex;gap:9px"><span class="tt">${esc(a.ts)}</span><span style="color:${a.lvl === "err" ? "var(--neg)" : a.lvl === "warn" ? "var(--warn)" : "var(--text-mid)"}">${esc(a.msg)}</span></div>`).join("");
  return `<div class="panel"><div class="panel-h"><h3>Cron health &amp; alerts</h3><span class="meta">${d.crons.length} daily jobs</span></div><div class="panel-b" style="display:grid;grid-template-columns:1fr 1fr;gap:18px"><div style="display:flex;flex-direction:column;gap:9px">${crons}</div><div style="border-left:1px solid var(--border);padding-left:18px;display:flex;flex-direction:column;gap:8px">${alerts}</div></div></div>`;
}

function paramsExpander(d) {
  const cities = d.cities.map(c => `<div>— <b style="color:var(--text-hi)">${esc(c.name)}</b> (${esc(c.code)}) — edge ≥ ${esc(c.edgeThresh)}, size ${esc(c.stake)}, daily $${c.risk.todayKill}, cumulative $${c.risk.cumKill}</div>`).join("");
  return `<details class="params"><summary>Strategy parameters in effect (live from live_trade.py)</summary><div class="pbody"><div><b style="color:var(--text-hi)">Filter:</b> |edge| ≥ per-city threshold, no entry-price floor · <b style="color:var(--text-hi)">Execution:</b> <code>post_inside_spread</code></div><div><b style="color:var(--text-hi)">Aggregate kills:</b> daily loss −$${d.agg.dailyKill}, cumulative drawdown −$${d.agg.cumKill}, 4wk avg spread &gt; 5¢</div><div style="margin-top:6px">${cities}</div><div style="margin-top:8px">Halt files: <code>touch halt/KORD</code> <code>touch halt/KMIA</code> <code>touch halt/ALL</code></div></div></details>`;
}

function renderLive() {
  const root = document.getElementById("live-root");
  if (!LIVE) { root.innerHTML = `<div class="loading">Loading live data…</div>`; return; }
  const d = LIVE;
  root.innerHTML =
    killBanner(d) + liveHero(d) + statusStrip(d) +
    `<div class="section-label">Per-city · realized + unrealized + risk</div>` +
    `<div class="grid g-3">${d.cities.map(cityCard).join("")}${aggRisk(d)}</div>` +
    `<div class="grid" style="grid-template-columns:1.45fr 1fr">` +
      `<div class="panel"><div class="panel-h"><h3>Cumulative P&amp;L</h3><span class="meta">last 7 days · since first live trade</span></div><div style="padding:10px 12px 4px"><div class="chart-wrap">${pnlChartSVG(d.series)}</div></div><div class="panel-b" style="padding-top:0"><div class="chart-legend"><span><span class="sw" style="background:${d.cumulative.total >= 0 ? "var(--pos)" : "var(--neg)"}"></span>cumulative realized P&amp;L · right axis</span></div></div></div>` +
      positionsTable(d.positions) +
    `</div>` +
    signalsTable(d.signals) +
    `<div class="grid g-2">${ordersTable(d.orders)}<div class="grid" style="grid-template-rows:auto auto;gap:14px">${openOrders(d.openOrdersTbl)}${recentFills(d.fills)}</div></div>` +
    cronAlerts(d) + paramsExpander(d);
}

// ====================================================================
// BACKTEST TAB render functions
// ====================================================================
function controlsBar(d) {
  const blendAvailable = !!d.blend;
  const cityOpts = BT_CITIES.map(c => `<option value="${esc(c.code)}" ${c.code === bt.cityCode ? "selected" : ""}>${esc(c.label)} · ${esc(c.code)}</option>`).join("");
  const platBtns = ["Kalshi", "Polymarket"].map(p => `<button class="${bt.platform === p ? "on" : ""}" onclick="btSetPlatform('${p}')">${p}</button>`).join("");
  const edgeOpts = [0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70].map(v => `<option value="${v}" ${Math.abs(v - bt.bracketEdge) < 1e-9 ? "selected" : ""}>≥ ${(v * 100).toFixed(0)}%</option>`).join("");
  return `<div class="panel"><div class="controls">
    <div class="ctrl"><span class="cl">Platform</span><div class="seg">${platBtns}</div></div>
    <div class="ctrl"><span class="cl">City</span><select onchange="btSelectCity(this.value)">${cityOpts}</select></div>
    <div class="ctrl"><span class="cl">Target date</span><input type="date" value="${esc(bt.date || "")}" onchange="btSelectDate(this.value)"></div>
    <div class="ctrl"><span class="cl">Strategy</span><div class="seg">
      <button class="${bt.strategy === "raw" ? "on" : ""}" onclick="btSetStrategy('raw')">Raw Model</button>
      <button class="${bt.strategy === "blend" ? "on" : ""}" ${blendAvailable ? "" : "disabled"} onclick="${blendAvailable ? "btSetStrategy('blend')" : ""}">Blend (Benter)</button>
      <button class="${bt.strategy === "union" ? "on" : ""}" ${blendAvailable ? "" : "disabled"} onclick="${blendAvailable ? "btSetStrategy('union')" : ""}">Union (R + B)</button>
    </div></div>
    <div class="ctrl"><span class="cl">Edge filter</span><select onchange="btSetBracketEdge(this.value)">${edgeOpts}</select></div>
  </div></div>`;
}

function simControls() {
  const sizeBtns = ["unit", "amount", "kelly", "scaling"].map(s => `<button class="${bt.sizing === s ? "on" : ""}" onclick="btSetSizing('${s}')">${s}</button>`).join("");
  const simEdgeOpts = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70].map(v => `<option value="${v}" ${Math.abs(v - bt.simEdge) < 1e-9 ? "selected" : ""}>≥ ${(v * 100).toFixed(0)}%</option>`).join("");
  const minEntryOpts = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80].map(v => `<option value="${v}" ${v === bt.minEntry ? "selected" : ""}>${v === 0 ? "any" : "≥ " + v + "¢"}</option>`).join("");
  const maxSigOpts = [[0, "no cap"], [1, "1 (KMIA live)"], [2, "2 (KORD live)"], [3, "3"], [4, "4"]].map(([v, l]) => `<option value="${v}" ${v === bt.maxSignals ? "selected" : ""}>${l}</option>`).join("");
  const edgeCapOpts = [[0, "no cap"], [0.30, "≥ 30%"], [0.40, "≥ 40% (live)"], [0.50, "≥ 50%"], [0.60, "≥ 60%"]].map(([v, l]) => `<option value="${v}" ${Math.abs(v - bt.edgeCap) < 1e-9 ? "selected" : ""}>${l}</option>`).join("");
  const execOpts = [["market", "market — cross spread, 100% fill"], ["post_inside_spread", "post_inside_spread — 1¢ inside, ~75% fill"], ["market_plus_1", "market_plus_1 — ask + 1¢"], ["market_plus_2", "market_plus_2 — ask + 2¢"]].map(([v, l]) => `<option value="${v}" ${v === bt.exec ? "selected" : ""}>${l}</option>`).join("");
  const amtLabel = bt.sizing === "unit" ? "Contracts" : bt.sizing === "amount" ? "$ / trade" : "% bankroll";
  const amtStep = bt.sizing === "unit" ? "50" : bt.sizing === "amount" ? "5" : "1";
  return `<div class="controls sim-controls">
    <div class="ctrl"><span class="cl">Bankroll</span><input type="number" value="${bt.bankroll}" step="100" min="100" onchange="btSetBankroll(this.value)"></div>
    <div class="ctrl"><span class="cl">Edge filter</span><select onchange="btSetSimEdge(this.value)">${simEdgeOpts}</select></div>
    <div class="ctrl"><span class="cl">Min entry</span><select onchange="btSetMinEntry(this.value)">${minEntryOpts}</select></div>
    <div class="ctrl"><span class="cl">Sizing</span><div class="seg">${sizeBtns}</div></div>
    <div class="ctrl"><span class="cl">${amtLabel}</span><input type="number" value="${bt.amount}" step="${amtStep}" onchange="btSetAmount(this.value)"></div>
    <div class="ctrl" title="Anti-stacking: per-day, keep only top N signals by |edge|."><span class="cl">Max signals/day</span><select onchange="btSetMaxSignals(this.value)">${maxSigOpts}</select></div>
    <div class="ctrl" title="Edge cap for sizing only."><span class="cl">Edge cap (size)</span><select onchange="btSetEdgeCap(this.value)">${edgeCapOpts}</select></div>
    <div class="ctrl"><span class="cl">Execution</span><select onchange="btSetExec(this.value)">${execOpts}</select></div>
    <div class="ctrl"><span class="cl">Depth cap</span><input type="number" value="${bt.depth}" step="50" onchange="btSetDepth(this.value)"></div>
  </div>`;
}

function edgeByBracketTable(d) {
  const brackets = d.brackets || [];
  const union = bt.strategy === "union";
  const meta = union
    ? `UNION signal: raw ≥ ${(bt.bracketEdge * 100).toFixed(0)}% OR blend ≥ ${(bt.bracketEdge * 40).toFixed(0)}% · set in top bar`
    : `${bt.strategy === "blend" ? "BLEND" : "RAW"} signal fires when |edge| ≥ ${(bt.bracketEdge * 100).toFixed(0)}% · set in top bar (independent of P&L sim)`;
  const head = union
    ? `<th class="l">Bracket</th><th>Model P</th><th>Blend P</th><th>Market P</th><th>Edge</th><th>Signal</th><th>Resolved</th>`
    : `<th class="l">Bracket</th><th>${bt.strategy === "blend" ? "Blend P" : "Model P"}</th><th>Market P</th><th>Edge</th><th>Signal</th><th>Resolved</th>`;
  let body;
  if (brackets.length === 0) {
    body = `<tr><td class="l muted" colspan="${union ? 7 : 6}" style="padding:16px 12px">No brackets for ${esc(bt.date || "")}.</td></tr>`;
  } else {
    body = brackets.map(b => {
      if (union) {
        const rawEdge = b.modelP - b.mktP;
        const blendEdge = (b.blendP != null) ? (b.blendP - b.mktP) : null;
        const rawFires = Math.abs(rawEdge) >= bt.bracketEdge;
        const blendFires = blendEdge != null && Math.abs(blendEdge) >= (bt.bracketEdge * 0.4);
        const fires = rawFires || blendFires;
        const e = rawFires ? rawEdge : blendEdge;
        const side = (e || 0) > 0 ? "YES" : "NO";
        const tag = rawFires && blendFires ? "both" : rawFires ? "raw" : blendFires ? "blend" : "";
        return `<tr><td class="l hi">${esc(b.label)}</td><td>${(b.modelP * 100).toFixed(0)}%</td><td>${b.blendP != null ? (b.blendP * 100).toFixed(0) + "%" : "—"}</td><td>${(b.mktP * 100).toFixed(0)}%</td><td>${edgeCell(e || 0)}</td><td>${fires ? `<span class="side ${side === "YES" ? "yes" : "no"}">BUY ${side} <small style="opacity:.6;margin-left:4px">${tag}</small></span>` : `<span class="muted">—</span>`}</td><td><span class="outcome ${b.resolved === "YES" ? "yes" : "no"}">${esc(b.resolved)}</span></td></tr>`;
      }
      const probSel = (bt.strategy === "blend" && b.blendP != null) ? b.blendP : b.modelP;
      const e = probSel - b.mktP;
      const fires = Math.abs(e) >= bt.bracketEdge;
      const side = e > 0 ? "YES" : "NO";
      return `<tr><td class="l hi">${esc(b.label)}</td><td>${(probSel * 100).toFixed(0)}%</td><td>${(b.mktP * 100).toFixed(0)}%</td><td>${edgeCell(e)}</td><td>${fires ? `<span class="side ${side === "YES" ? "yes" : "no"}">BUY ${side}</span>` : `<span class="muted">—</span>`}</td><td><span class="outcome ${b.resolved === "YES" ? "yes" : "no"}">${esc(b.resolved)}</span></td></tr>`;
    }).join("");
  }
  return `<div class="panel"><div class="panel-h"><h3>Edge by bracket</h3><span class="meta">${esc(meta)}</span></div><table class="dt"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
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

function strategyComparison(strat) {
  let body;
  if (!strat || strat.length === 0) body = `<tr><td class="l muted" colspan="8" style="padding:16px 12px">No strategy comparison data.</td></tr>`;
  else body = strat.map(s => `<tr class="${s.chosen ? "chosen" : ""}"><td class="l hi">${esc(s.name)}${s.chosen ? `<span class="chosen-tag">live</span>` : ""}</td><td class="hi">${moneyPlain(s.final)}</td><td class="${cls(s.ret)}">${pct(s.ret)}</td><td class="${s.sharpe >= 1 ? "pos" : ""}">${s.sharpe.toFixed(2)}</td><td class="neg">${pct(s.maxDD)}</td><td>${(s.win * 100).toFixed(0)}%</td><td>${s.brier.toFixed(3)}</td><td>${s.n}</td></tr>`).join("");
  return `<div class="panel"><div class="panel-h"><h3>Strategy comparison</h3><span class="meta">${esc(BT.city)} · head-to-head model variants · |edge| ≥ ${(bt.simEdge * 100).toFixed(0)}%</span></div><table class="dt"><thead><tr><th class="l">Model variant</th><th>Final balance</th><th>Return</th><th>Sharpe</th><th>Max DD</th><th>Win rate</th><th>Brier</th><th>Trades</th></tr></thead><tbody>${body}</tbody></table></div>`;
}

function renderBacktest() {
  const root = document.getElementById("backtest-root");
  if (!BT) { root.innerHTML = `<div class="wrap"><div class="loading">Loading backtest…</div></div>`; return; }
  const d = BT;
  const sim = jsComputeSim(d.trades || [], {
    sizing: bt.sizing, edgeFilter: bt.simEdge, minEntry: bt.minEntry, amountDollars: Number(bt.amount) || 0,
    depthCap: Number(bt.depth) || 0, execution: bt.exec, startingBankroll: bt.bankroll,
    strategy: bt.strategy, maxSignals: Number(bt.maxSignals) || 0, edgeCap: Number(bt.edgeCap) || 0,
  });
  const noData = (!d.trades || d.trades.length === 0);
  const backfilling = noData ? `<div class="bt-backfilling">⏳ ${esc(d.city)}: backtest data is still backfilling (forecast history for this city's traded dates hasn't finished downloading). Best-results will load automatically once it's ready — no action needed.</div>` : "";
  const simMeta = `${esc(d.city)} · ${esc(bt.sizing)} · |edge| ≥ ${(bt.simEdge * 100).toFixed(0)}%${bt.minEntry ? " · entry ≥ " + bt.minEntry + "¢" : ""}`;
  root.innerHTML = `<div class="wrap">` +
    controlsBar(d) +
    `<div class="section-label">Forecast — combined GEFS + ECMWF ensemble · ${esc(d.city)} · ${esc(bt.date || "")}</div>` +
    `<div class="grid" style="grid-template-columns:1.5fr 1fr">` +
      `<div class="panel"><div class="panel-h"><h3>Ensemble distribution</h3><span class="meta">${d.nMembers} members · EMOS Gaussian overlay</span></div><div style="padding:8px 8px 0"><div class="chart-wrap">${ensembleChartSVG(d)}</div></div><div class="ens-note"><span><span class="sw" style="background:var(--bg-3)"></span>member daily highs</span><span><span class="sw" style="background:var(--warn)"></span>EMOS μ=${d.emosMu}° σ=${d.emosSigma}°</span><span><span class="sw" style="background:var(--text-lo)"></span>ensemble mean ${d.ensMean}°</span><span><span class="sw" style="background:var(--pos)"></span>resolved high ${d.observed}°</span></div></div>` +
      `<div class="panel" style="display:flex;flex-direction:column"><div class="panel-h"><h3>Forecast summary</h3></div><div class="fc-stats" style="border-bottom:1px solid var(--border)">${BTMetric("Members", d.nMembers)}${BTMetric("Ens. mean", `${d.ensMean}<small>°F</small>`)}${BTMetric("Ens. spread", `${d.ensSpread}<small>°F</small>`)}${BTMetric("Resolved", `${d.observed}<small>°F</small>`)}</div><div style="padding:16px;display:flex;flex-direction:column;gap:14px;flex:1"><div style="display:flex;justify-content:space-between;align-items:baseline"><span style="font:600 11px/1 var(--ui);letter-spacing:.12em;text-transform:uppercase;color:var(--text-lo)">EMOS post-processed</span><span class="mono" style="font-size:18px;color:var(--text-hi)">μ ${d.emosMu}° · σ ${d.emosSigma}°</span></div><div class="mono" style="font-size:11.5px;line-height:1.7;color:var(--text-lo)">Rolling 45-day fit corrects ensemble under-dispersion. Bracket probabilities below integrate this Gaussian; edge = model − market mid.</div></div></div>` +
    `</div>` +
    edgeByBracketTable(d) +
    `<div class="section-label">P&amp;L simulation — tweak the run parameters below</div>` +
    `<div class="panel"><div class="panel-h"><h3>Simulation results</h3><span class="meta">${simMeta}</span></div>` +
      backfilling + simControls() +
      `<div class="bt-metrics" style="border-bottom:1px solid var(--border)">` +
        BTMetric("Final balance", moneyPlain(sim.final || 0), pct(sim.ret || 0), (sim.ret || 0) >= 0 ? "pos" : "neg") +
        BTMetric("Resolved", `${Math.round((sim.n || 0) * (sim.win || 0))}/${sim.n || 0}`, `${((sim.win || 0) * 100).toFixed(0)}% win rate`) +
        BTMetric("Sharpe (ann.)", (sim.sharpe || 0).toFixed(2), "risk-adjusted", (sim.sharpe || 0) >= 1 ? "pos" : "") +
        BTMetric("Max drawdown", money(sim.maxDDDollars || 0), `${pct(sim.maxDD || 0)} peak-to-trough`, "neg") +
        BTMetric("Missed fills", sim.missed || 0, "maker didn't fill", (sim.missed || 0) > 0 ? "neg" : "") +
        BTMetric("Filtered / total", `${sim.n || 0} / ${sim.total || 0}`, "filled / passed filter") +
      `</div>` +
      `<div style="padding:12px 12px 4px"><div class="chart-wrap">${balanceChartSVG(sim.curve || [bt.bankroll, bt.bankroll], (sim.tradeRecords || []).filter(t => t.fill === "filled"))}</div></div>` +
      `<div class="panel-b" style="padding-top:4px"><div class="chart-legend"><span><span class="sw" style="background:${(sim.ret || 0) >= 0 ? "var(--pos)" : "var(--neg)"}"></span>balance curve · start $${(sim.curve || [1000])[0].toLocaleString()} → $${(sim.final || 0).toLocaleString()}</span></div></div>` +
    `</div>` +
    tradeDetailTable(sim) +
    strategyComparison(d.strat || []) +
  `</div>`;
}

// ====================================================================
// BACKTEST control handlers
// ====================================================================
function btSelectCity(code) { bt.cityCode = code; bt.date = null; loadBacktest(); }
function btSelectDate(v) { bt.date = v; loadBacktest(); }
function btSetPlatform(v) { bt.platform = v; renderBacktest(); }
function btSetStrategy(v) { bt.strategy = v; renderBacktest(); }
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
  const best = findBestParams(BT.trades);
  autoedCities.add(BT.code);
  if (best) { bt.strategy = best.strategy; bt.simEdge = best.edge; bt.bracketEdge = best.edge; }
  else { bt.strategy = BT.blend ? "blend" : "raw"; }
  bt.sizing = "unit"; bt.amount = 500; bt.exec = "market";
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

function startLivePolling() { if (!liveTimer) liveTimer = setInterval(loadLive, 15000); }
function stopLivePolling() { if (liveTimer) { clearInterval(liveTimer); liveTimer = null; } }

function switchTab(name) {
  activeTab = name;
  document.getElementById("section-live").hidden = name !== "live";
  document.getElementById("section-backtest").hidden = name !== "backtest";
  document.getElementById("tab-live").classList.toggle("on", name === "live");
  document.getElementById("tab-backtest").classList.toggle("on", name === "backtest");
  const rl = document.getElementById("refresh-label");
  if (name === "live") {
    startLivePolling();
    if (rl) rl.textContent = "live · 15s";
  } else {
    stopLivePolling();
    if (rl) rl.textContent = "backtest";
    if (!BT) loadBacktest();
  }
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
