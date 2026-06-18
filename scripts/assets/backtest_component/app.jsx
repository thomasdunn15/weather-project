// ====================================================================
// SHARED ATOMS (from components.jsx)
// ====================================================================
const { useState, useEffect, useRef } = React;

function money(v, { sign = true, dp = 2 } = {}) {
  if (v === null || v === undefined) return "—";
  const s = v < 0 ? "−" : (sign ? "+" : "");
  return s + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}
function moneyPlain(v) {
  if (v === null || v === undefined) return "—";
  return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function pct(v, dp = 1) {
  if (v === null || v === undefined) return "—";
  const s = v < 0 ? "−" : "+";
  return s + Math.abs(v).toFixed(dp) + "%";
}
function cls(v) { return v > 0 ? "pos" : v < 0 ? "neg" : "muted"; }

function Panel({ title, meta, children, style }) {
  return (
    <div className="panel" style={style}>
      <div className="panel-h"><h3>{title}</h3>{meta && <span className="meta">{meta}</span>}</div>
      <div className="panel-b">{children}</div>
    </div>
  );
}
function PanelBare({ title, meta, children, style }) {
  return (
    <div className="panel" style={style}>
      <div className="panel-h"><h3>{title}</h3>{meta && <span className="meta">{meta}</span>}</div>
      {children}
    </div>
  );
}

function EdgeCell({ edge }) {
  const positive = edge >= 0;
  const w = Math.min(100, Math.abs(edge) / 0.4 * 100);
  return (
    <span className="edge-cell">
      <span className={positive ? "pos" : "neg"}>{(edge >= 0 ? "+" : "−") + (Math.abs(edge) * 100).toFixed(0) + "%"}</span>
      <span className="edge-bar"><span style={{ width: w / 2 + "%", [positive ? "left" : "right"]: "50%", background: positive ? "var(--pos)" : "var(--neg)" }} /></span>
    </span>
  );
}

// ====================================================================
// CHARTS (Ensemble + Balance + erf helpers from backtest-tab.jsx)
// ====================================================================
function erf(x) {
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return x >= 0 ? y : -y;
}
const normPdf = (x, mu, s) => Math.exp(-0.5 * ((x - mu) / s) ** 2) / (s * Math.sqrt(2 * Math.PI));

function EnsembleChart({ d, height = 248 }) {
  const wrapRef = useRef(null);
  const [w, setW] = useState(760);
  useEffect(() => {
    const ro = new ResizeObserver(es => { for (const e of es) setW(e.contentRect.width); });
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  if (!d.members || d.members.length === 0) {
    return <div ref={wrapRef} style={{ padding: 24, color: "var(--text-lo)", textAlign: "center" }}>No ensemble data for {d.date}.</div>;
  }
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
  const curve = [];
  if (d.emosSigma > 0) {
    for (let i = 0; i <= 80; i++) {
      const t = lo + (hi - lo) * (i / 80);
      const yv = (normPdf(t, d.emosMu, d.emosSigma) / pdfPeak) * (maxCount * 0.92);
      curve.push(`${i === 0 ? "M" : "L"}${X(t).toFixed(1)},${(padT + ih - (yv / maxCount) * ih).toFixed(1)}`);
    }
  }
  const boundaries = [...new Set((d.brackets || []).flatMap(b => [b.lo, b.hi]).filter(v => v > lo && v < hi && Math.abs(v) < 90))];

  return (
    <div className="chart-wrap" ref={wrapRef}>
      <svg width={w} height={height} viewBox={`0 0 ${w} ${height}`}>
        {boundaries.map((bv, i) => (
          <line key={i} x1={X(bv + 0.5)} x2={X(bv + 0.5)} y1={padT} y2={padT + ih}
            stroke="var(--border)" strokeWidth="1" strokeDasharray="2 4" />
        ))}
        {Object.entries(bins).map(([t, c], i) => c > 0 && (
          <rect key={i} x={X(+t) - barW / 2} y={padT + ih - (c / maxCount) * ih}
            width={barW} height={(c / maxCount) * ih} rx="1.5" fill="var(--bg-3)" />
        ))}
        {curve.length > 0 && <path d={curve.join(" ")} fill="none" stroke="var(--warn)" strokeWidth="2" />}
        {d.ensMean > 0 && <line x1={X(d.ensMean)} x2={X(d.ensMean)} y1={padT} y2={padT + ih} stroke="var(--text-lo)" strokeWidth="1" strokeDasharray="3 3" />}
        {d.observed > 0 && <>
          <line x1={X(d.observed)} x2={X(d.observed)} y1={padT - 2} y2={padT + ih} stroke="var(--pos)" strokeWidth="2" />
          <g transform={`translate(${Math.min(X(d.observed) + 6, padL + iw - 70)},${padT + 4})`}>
            <rect width="64" height="18" rx="4" fill="var(--pos-dim)" stroke="var(--pos-line)" />
            <text x="7" y="13" fill="var(--pos)" style={{ font: "600 10px var(--mono)" }}>obs {d.observed}°</text>
          </g>
        </>}
        {Array.from({ length: hi - lo + 1 }, (_, i) => lo + i).filter(t => t % 2 === 0).map((t, i) => (
          <text key={i} x={X(t)} y={height - 9} textAnchor="middle" className="chart-axis-x">{t}°</text>
        ))}
      </svg>
    </div>
  );
}

function BalanceChart({ curve, filledTrades, height = 300 }) {
  const wrapRef = useRef(null);
  const [w, setW] = useState(720);
  const [hover, setHover] = useState(null);  // index into curve
  useEffect(() => {
    const ro = new ResizeObserver(es => { for (const e of es) setW(e.contentRect.width); });
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);
  if (!curve || curve.length < 2) {
    return <div ref={wrapRef} style={{ padding: 24, color: "var(--text-lo)", textAlign: "center" }}>No simulation curve.</div>;
  }
  const padL = 14, padR = 64, padT = 14, padB = 26;
  const iw = w - padL - padR, ih = height - padT - padB;
  const start = curve[0];

  // "Nice" axis: round min DOWN and max UP to a clean multiple so labels are
  // readable (e.g., $0, $10k, $20k, …) instead of arbitrary $-890 / $9,384 etc.
  const rawMin = Math.min(...curve, start);
  const rawMax = Math.max(...curve, start);
  function niceStep(range, targetTicks) {
    const rough = range / targetTicks;
    const exp = Math.pow(10, Math.floor(Math.log10(rough)));
    const norm = rough / exp;
    let step;
    if (norm < 1.5) step = 1;
    else if (norm < 3) step = 2;
    else if (norm < 7) step = 5;
    else step = 10;
    return step * exp;
  }
  const targetTicks = 4;
  const step = niceStep(rawMax - rawMin || 1, targetTicks);
  const min = Math.floor(rawMin / step) * step;
  const max = Math.ceil(rawMax / step) * step;
  const span = (max - min) || 1;

  const X = i => padL + (i / (curve.length - 1)) * iw;
  const Y = v => padT + (1 - (v - min) / span) * ih;
  const last = curve[curve.length - 1];
  const c = last >= start ? "var(--pos)" : "var(--neg)";
  const line = curve.map((v, i) => `${i === 0 ? "M" : "L"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  // Build round tick values from min to max in step increments
  const tickVals = [];
  for (let v = min; v <= max + step * 0.01; v += step) tickVals.push(v);

  // Hover state — find nearest index to mouse x
  const onMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = (e.clientX - r.left) * (w / r.width);
    let best = 0, bd = 1e9;
    for (let i = 0; i < curve.length; i++) {
      const dist = Math.abs(X(i) - px);
      if (dist < bd) { bd = dist; best = i; }
    }
    setHover(best);
  };

  // Trade at hover position. curve[0] = starting bankroll, curve[i] = balance
  // AFTER filledTrades[i-1]. So tooltip for index i shows the trade that
  // produced that balance (or "start" for i==0).
  const ft = filledTrades || [];
  const tradeAt = hover != null && hover > 0 ? ft[hover - 1] : null;
  const balanceAt = hover != null ? curve[hover] : last;
  const cumPnl = balanceAt - start;
  const tooltipW = 220, tooltipH = 88;
  let tooltipX = hover != null ? Math.min(X(hover) + 10, padL + iw - tooltipW - 2) : 0;
  if (tooltipX < padL + 2) tooltipX = padL + 2;
  const tooltipY = padT + 6;

  return (
    <div className="chart-wrap" ref={wrapRef}>
      <svg width={w} height={height} viewBox={`0 0 ${w} ${height}`}
           onMouseMove={onMove} onMouseLeave={() => setHover(null)}
           style={{ cursor: "crosshair" }}>
        <defs><linearGradient id="balfill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={c} stopOpacity="0.16" /><stop offset="1" stopColor={c} stopOpacity="0.01" />
        </linearGradient></defs>
        {tickVals.map((tv, i) => {
          const labelTxt = Math.abs(tv) >= 1000
            ? (tv < 0 ? "−$" : "$") + (Math.abs(tv) / 1000).toFixed(Math.abs(tv) >= 10000 ? 0 : 1) + "k"
            : (tv < 0 ? "−$" : "$") + Math.abs(Math.round(tv));
          return (
            <g key={i}>
              <line x1={padL} x2={padL + iw} y1={Y(tv)} y2={Y(tv)} stroke="var(--border)" strokeWidth="1" strokeDasharray="2 4" />
              <text x={padL + iw + 8} y={Y(tv) + 3.5} fill="var(--text-faint)" style={{ font: "500 10px var(--mono)" }}>{labelTxt}</text>
            </g>
          );
        })}
        {/* Starting bankroll line — solid emphasis so user sees the baseline */}
        <line x1={padL} x2={padL + iw} y1={Y(start)} y2={Y(start)} stroke="var(--border-strong)" strokeWidth="1.5" />
        <text x={padL + iw + 8} y={Y(start) - 4} fill="var(--text-lo)" style={{ font: "600 9.5px var(--mono)" }}>start</text>
        <path d={`${line} L${X(curve.length - 1)},${Y(min)} L${X(0)},${Y(min)} Z`} fill="url(#balfill)" />
        <path d={line} fill="none" stroke={c} strokeWidth="2" strokeLinejoin="round" />
        {/* X-axis date labels — pull from filledTrades so user can see real
            chronology (left = oldest, right = newest). */}
        {[0, Math.floor(curve.length * 0.25), Math.floor(curve.length * 0.5), Math.floor(curve.length * 0.75), curve.length - 1].map((i, k) => {
          let label;
          if (i === 0) label = "start";
          else if (ft[i - 1] && ft[i - 1].date) label = ft[i - 1].date;
          else label = `t${i}`;
          return (
            <text key={k} x={X(i)} y={height - 8} textAnchor="middle"
              fill="var(--text-faint)" style={{ font: "500 9.5px var(--mono)" }}>
              {label}
            </text>
          );
        })}
        {/* Hover overlay: crosshair + dot + tooltip */}
        {hover != null && (
          <g pointerEvents="none">
            <line x1={X(hover)} x2={X(hover)} y1={padT} y2={padT + ih}
                  stroke="var(--border-strong)" strokeWidth="1" />
            <circle cx={X(hover)} cy={Y(curve[hover])} r="4"
                    fill={c} stroke="var(--bg-1)" strokeWidth="2" />
            <g transform={`translate(${tooltipX},${tooltipY})`}>
              <rect width={tooltipW} height={tooltipH} rx="5"
                    fill="var(--bg-3)" stroke="var(--border-strong)" />
              <text x="10" y="16" fill="var(--text-hi)" style={{ font: "600 11px var(--mono)" }}>
                {tradeAt ? `${tradeAt.date} · ${tradeAt.bracket}` : "Starting bankroll"}
              </text>
              {tradeAt && (
                <text x="10" y="32" fill="var(--text-mid)" style={{ font: "500 10.5px var(--mono)" }}>
                  {tradeAt.side} @ {tradeAt.entry}¢ · qty {tradeAt.computedQty}
                </text>
              )}
              <text x="10" y={tradeAt ? 50 : 32} fill="var(--text-lo)" style={{ font: "500 10px var(--mono)" }}>
                BALANCE
              </text>
              <text x="78" y={tradeAt ? 50 : 32} fill="var(--text-hi)" style={{ font: "600 11px var(--mono)" }}>
                ${curve[hover].toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </text>
              {tradeAt && (
                <>
                  <text x="10" y="66" fill="var(--text-lo)" style={{ font: "500 10px var(--mono)" }}>TRADE P&amp;L</text>
                  <text x="78" y="66" fill={tradeAt.computedPnl >= 0 ? "var(--pos)" : "var(--neg)"} style={{ font: "600 11px var(--mono)" }}>
                    {tradeAt.computedPnl >= 0 ? "+" : "−"}${Math.abs(tradeAt.computedPnl).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </text>
                  <text x="10" y="80" fill="var(--text-lo)" style={{ font: "500 10px var(--mono)" }}>CUMULATIVE</text>
                  <text x="78" y="80" fill={cumPnl >= 0 ? "var(--pos)" : "var(--neg)"} style={{ font: "600 11px var(--mono)" }}>
                    {cumPnl >= 0 ? "+" : "−"}${Math.abs(cumPnl).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </text>
                </>
              )}
            </g>
          </g>
        )}
      </svg>
    </div>
  );
}

// ====================================================================
// CONTROLS BAR + SIM CONTROLS
// ====================================================================
function ControlsBar({ platform, setPlatform, cityCode, setCityCode, date, setDate, edge, setEdge, strategy, setStrategy, blendInfo }) {
  const availableCities = (window.BTDATA && window.BTDATA.cities) || [cityCode];
  const blendAvailable = !!blendInfo;
  return (
    <div className="panel">
      <div className="controls">
        <div className="ctrl">
          <span className="cl">Platform</span>
          <div className="seg">
            {["Kalshi", "Polymarket"].map(p => <button key={p} className={platform === p ? "on" : ""} onClick={() => setPlatform(p)}>{p}</button>)}
          </div>
        </div>
        <div className="ctrl">
          <span className="cl">City</span>
          <select value={cityCode} onChange={e => setCityCode(e.target.value)}>
            {availableCities.map(code => {
              const cdata = window.BTDATA[code] || {};
              const label = (cdata.city || code) + " · " + code;
              return <option key={code} value={code}>{label}</option>;
            })}
          </select>
        </div>
        <div className="ctrl">
          <span className="cl">Target date</span>
          <input type="date" value={date} onChange={e => setDate(e.target.value)} />
        </div>
        <div className="ctrl">
          <span className="cl">Strategy</span>
          <div className="seg">
            <button className={strategy === "raw" ? "on" : ""} onClick={() => setStrategy("raw")}>Raw Model</button>
            <button className={strategy === "blend" ? "on" : ""}
                    disabled={!blendAvailable}
                    onClick={() => blendAvailable && setStrategy("blend")}
                    title={blendAvailable
                      ? `Blend: ${blendInfo.marketShare * 100}% market, ${(100 - blendInfo.marketShare * 100).toFixed(0)}% model (n_train=${blendInfo.nTrain})`
                      : "Need ≥100 settled paper_trades to fit blend"}>
              Blend (Benter)
            </button>
            <button className={strategy === "union" ? "on" : ""}
                    disabled={!blendAvailable}
                    onClick={() => blendAvailable && setStrategy("union")}
                    title="Fire if RAW edge ≥ filter OR BLEND edge ≥ (filter × 0.4). Both signals captured; live KORD config.">
              Union (R + B)
            </button>
          </div>
        </div>
        <div className="ctrl">
          <span className="cl">Edge filter</span>
          <select value={edge} onChange={e => setEdge(+e.target.value)}>
            {[0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70].map(v => <option key={v} value={v}>≥ {(v * 100).toFixed(0)}%</option>)}
          </select>
        </div>
      </div>
    </div>
  );
}

function SimControls({ edge, setEdge, minEntry, setMinEntry, sizing, setSizing, exec, setExec, depth, setDepth, amount, setAmount, bankroll, setBankroll, maxSignals, setMaxSignals, edgeCap, setEdgeCap }) {
  return (
    <div className="controls sim-controls">
      <div className="ctrl"><span className="cl">Bankroll</span>
        <input type="number" value={bankroll} onChange={e => setBankroll(e.target.value)} step="100" min="100" />
      </div>
      <div className="ctrl"><span className="cl">Edge filter</span>
        <select value={edge} onChange={e => setEdge(+e.target.value)}>
          {[0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70].map(v => <option key={v} value={v}>≥ {(v * 100).toFixed(0)}%</option>)}
        </select>
      </div>
      <div className="ctrl"><span className="cl">Min entry</span>
        <select value={minEntry} onChange={e => setMinEntry(+e.target.value)}>
          {[0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80].map(v => <option key={v} value={v}>{v === 0 ? "any" : "≥ " + v + "¢"}</option>)}
        </select>
      </div>
      <div className="ctrl"><span className="cl">Sizing</span>
        <div className="seg">
          {["unit", "amount", "kelly", "scaling"].map(s => <button key={s} className={sizing === s ? "on" : ""} onClick={() => setSizing(s)}>{s}</button>)}
        </div>
      </div>
      <div className="ctrl"><span className="cl">{sizing === "unit" ? "Contracts" : sizing === "amount" ? "$ / trade" : "% bankroll"}</span>
        <input type="number" value={amount} onChange={e => setAmount(e.target.value)} step={sizing === "unit" ? "50" : sizing === "amount" ? "5" : "1"} />
      </div>
      <div className="ctrl" title="Anti-stacking: per-day, keep only top N signals by |edge|. Live KORD=2, KMIA=1, 0=off.">
        <span className="cl">Max signals/day</span>
        <select value={maxSignals} onChange={e => setMaxSignals(+e.target.value)}>
          <option value={0}>no cap</option>
          <option value={1}>1 (KMIA live)</option>
          <option value={2}>2 (KORD live)</option>
          <option value={3}>3</option>
          <option value={4}>4</option>
        </select>
      </div>
      <div className="ctrl" title="Edge cap for sizing only: treat edges above this as if they were this. Doesn't change which trades fire — only sizing. Live: 40% in both cities.">
        <span className="cl">Edge cap (size)</span>
        <select value={edgeCap} onChange={e => setEdgeCap(+e.target.value)}>
          <option value={0}>no cap</option>
          <option value={0.30}>≥ 30%</option>
          <option value={0.40}>≥ 40% (live)</option>
          <option value={0.50}>≥ 50%</option>
          <option value={0.60}>≥ 60%</option>
        </select>
      </div>
      <div className="ctrl"><span className="cl">Execution</span>
        <select value={exec} onChange={e => setExec(e.target.value)}>
          <option value="market">market — cross the spread, 100% fill (realistic default)</option>
          <option value="post_inside_spread">post_inside_spread — 1¢ inside, only ~75% fill (saves $ when it fills)</option>
          <option value="market_plus_1">market_plus_1 — pay ask + 1¢ (aggressive, ensures fill)</option>
          <option value="market_plus_2">market_plus_2 — pay ask + 2¢ (very aggressive)</option>
        </select>
      </div>
      <div className="ctrl"><span className="cl">Depth cap</span>
        <input type="number" value={depth} onChange={e => setDepth(e.target.value)} step="50" />
      </div>
    </div>
  );
}

// JS port of scripts/dashboard.py simulate_pnl — runs entirely client-side so
// changing sizing/edge/amount/depth/bankroll updates the panel instantly with
// no Python round-trip. Fields needed from each trade: entry, edge, won (bool|null),
// pos ("BUY_YES"|"BUY_NO"), modelP, marketYesBid, marketYesAsk, date.
// Fraction of post_inside_spread (maker) orders that actually fill. A maker
// order posted inside the spread only fills when the market trades through it;
// live KORD/KMIA data shows ~75%. Missed fills produce no position. Taker
// modes (market / market_plus_*) cross the spread and fill 100%.
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

function BTMetric({ label, value, sub, tone }) {
  return <div className="m"><div className="ml">{label}</div><div className={"mv " + (tone || "")}>{value}</div><div className="ms">{sub}</div></div>;
}

// ====================================================================
// MAIN BACKTEST TAB
// ====================================================================
function BacktestTab({ initialState }) {
  const init = initialState || {};
  const defaultCity = init.cityCode || (window.BTDATA && window.BTDATA.cities && window.BTDATA.cities[0]) || "KORD";
  const [platform, setPlatform_] = useState(init.platform || "Kalshi");
  const [cityCode, setCityCode_] = useState(defaultCity);
  const [sizing, setSizing] = useState(init.sizing || "unit");             // LOCAL only — default unit
  // Migrate any legacy 'cross_at_ask' / 'cross_with_premium' values from old
  // saved state to the new explicit names.
  const _execInit = (() => {
    // Default to "market" (cross, 100% fill) — the realistic baseline. The old
    // default (post_inside_spread) assumed a free cent AND a guaranteed fill,
    // which overstated returns; it's still selectable but now fill-modeled.
    const v = init.exec || "market";
    if (v === "cross_at_ask") return "market";
    if (v === "cross_with_premium") return "market_plus_1";
    return v;
  })();
  const [exec, setExec] = useState(_execInit);                              // LOCAL only
  const [depth, setDepth] = useState(init.depth ?? 500);                   // LOCAL only
  // Two separate edge filters:
  //   bracketEdge — controls the "Edge by bracket" Signal column at TOP
  //   simEdge     — controls trade selection in the P&L SIMULATION at BOTTOM
  // Decoupled per user request 2026-06-09 — previously a single shared `edge`.
  const [bracketEdge, setBracketEdge] = useState(init.edge ?? 0.10);
  const [simEdge, setSimEdge] = useState(init.edge ?? 0.10);
  const [minEntry, setMinEntry] = useState(init.minEntry ?? 0);            // LOCAL only
  const [amount, setAmount] = useState(init.amount ?? 500);               // LOCAL only — default 500 contracts (unit)
  const [bankroll, setBankroll_] = useState(3000);                         // LOCAL only — matches real Kalshi balance
  // RISK CONTROLS (added 2026-06-10, matching live_trade.py).
  // maxSignals — anti-stacking cap. When the model has high directional
  // conviction, multiple brackets express the SAME view; capping to top N
  // prevents losing on all stacked positions when the model is wrong.
  // 0 = no cap (legacy). Live config: KORD=2, KMIA=1.
  const [maxSignals, setMaxSignals] = useState(init.maxSignals ?? 0);
  // edgeCap — for SIZING ONLY. Edges above this get sized as-if they were
  // edgeCap. Doesn't change which trades fire — only sizing math. 0 = no cap.
  // Live: 0.40 in both cities.
  const [edgeCap, setEdgeCap] = useState(init.edgeCap ?? 0);
  const [dateStr, setDateStr_] = useState(init.date || (window.BTDATA[defaultCity] || {}).date);
  // Strategy: "raw" = use modelP; "blend" = use blendP (Benter-style logistic blend).
  // Auto-default to blend if available, else raw.
  const _cityData = window.BTDATA[defaultCity] || {};
  const [strategy, setStrategy] = useState(init.strategy || (_cityData.blend ? "blend" : "raw"));

  // ONLY city/date/platform round-trip Python (they need fresh data).
  // Sim params (sizing/edge/minEntry/amount/depth/exec/bankroll) recompute
  // in JS instantly using jsComputeSim — no Python rerun.
  const notify = (partial) => {
    if (typeof window.BT_ON_CHANGE === "function") {
      window.BT_ON_CHANGE({
        platform, cityCode, sizing, exec, depth,
        edge: simEdge,                  // backwards-compat: send simEdge under legacy key
        bracketEdge, simEdge,           // explicit for new code
        minEntry, amount, date: dateStr,
        ...partial,
      });
    }
  };
  const setPlatform = (v) => { setPlatform_(v); notify({ platform: v }); };
  const setCityCode = (v) => { setCityCode_(v); notify({ cityCode: v }); };
  const setDate     = (v) => { setDateStr_(v);  notify({ date: v }); };
  const setBankroll = (v) => { setBankroll_(Math.max(100, Number(v) || 1000)); };  // local only

  const d = window.BTDATA[cityCode] || window.BTDATA[defaultCity];

  // AUTO-LOAD best params the FIRST time each city's data appears (on click /
  // initial load). Sets strategy + edge to that city's best (by Sharpe, min 15
  // trades) and forces the realistic unit-500 / market defaults. Tracked via a
  // Set of cities already auto-loaded so it runs ONCE per city per session and
  // never fights the user's manual tweaks — neither on revisit nor when a
  // city's trade count changes mid-session (e.g. backfill data arriving).
  const autoedCities = useRef(new Set());
  useEffect(() => {
    if (!d || !d.trades || !d.trades.length) return;
    if (autoedCities.current.has(cityCode)) return;
    const best = findBestParams(d.trades);
    autoedCities.current.add(cityCode);
    if (best) {
      setStrategy(best.strategy);
      setSimEdge(best.edge);
      setBracketEdge(best.edge);
    }
    setSizing("unit");
    setAmount(500);
    setExec("market");
  }, [cityCode, d && d.trades && d.trades.length]);

  if (!d) {
    return <div style={{ padding: 24, color: "var(--text-lo)" }}>No data for {cityCode}.</div>;
  }
  // Recompute sim every render using current params + trade history. Cheap
  // (<5ms for ~1k trades) so it's fine to redo every render.
  // Sim uses simEdge (the bottom filter), NOT bracketEdge.
  const sim = jsComputeSim(d.trades || [], {
    sizing, edgeFilter: simEdge, minEntry, amountDollars: Number(amount) || 0,
    depthCap: Number(depth) || 0, execution: exec, startingBankroll: bankroll,
    strategy,                                       // "raw" / "blend" / "union"
    maxSignals: Number(maxSignals) || 0,            // 0 = no cap (legacy)
    edgeCap: Number(edgeCap) || 0,                  // 0 = no cap (legacy)
  });
  const brackets = d.brackets || [];
  // For the Edge by bracket display, pick which P to compare to market.
  const probField = strategy === "blend" ? "blendP" : "modelP";
  const trades = d.trades || [];
  const strat = d.strat || [];

  return (
    <div className="wrap">
      <ControlsBar {...{ platform, setPlatform, cityCode, setCityCode, date: dateStr, setDate,
                          edge: bracketEdge, setEdge: setBracketEdge,
                          strategy, setStrategy, blendInfo: d.blend }} />

      <div className="section-label">Forecast — combined GEFS + ECMWF ensemble · {d.city} · {dateStr}</div>
      <div className="grid" style={{ gridTemplateColumns: "1.5fr 1fr" }}>
        <div className="panel">
          <div className="panel-h"><h3>Ensemble distribution</h3><span className="meta">{d.nMembers} members · EMOS Gaussian overlay</span></div>
          <div style={{ padding: "8px 8px 0" }}><EnsembleChart d={d} /></div>
          <div className="ens-note">
            <span><span className="sw" style={{ background: "var(--bg-3)" }} />member daily highs</span>
            <span><span className="sw" style={{ background: "var(--warn)" }} />EMOS μ={d.emosMu}° σ={d.emosSigma}°</span>
            <span><span className="sw" style={{ background: "var(--text-lo)" }} />ensemble mean {d.ensMean}°</span>
            <span><span className="sw" style={{ background: "var(--pos)" }} />resolved high {d.observed}°</span>
          </div>
        </div>
        <div className="panel" style={{ display: "flex", flexDirection: "column" }}>
          <div className="panel-h"><h3>Forecast summary</h3></div>
          <div className="fc-stats" style={{ borderBottom: "1px solid var(--border)" }}>
            <BTMetric label="Members" value={d.nMembers} />
            <BTMetric label="Ens. mean" value={<span>{d.ensMean}<small>°F</small></span>} />
            <BTMetric label="Ens. spread" value={<span>{d.ensSpread}<small>°F</small></span>} />
            <BTMetric label="Resolved" value={<span>{d.observed}<small>°F</small></span>} />
          </div>
          <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 14, flex: 1 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <span style={{ font: "600 11px/1 var(--ui)", letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--text-lo)" }}>EMOS post-processed</span>
              <span className="mono" style={{ fontSize: 18, color: "var(--text-hi)" }}>μ {d.emosMu}° · σ {d.emosSigma}°</span>
            </div>
            <div className="mono" style={{ fontSize: 11.5, lineHeight: 1.7, color: "var(--text-lo)" }}>
              Rolling 45-day fit corrects ensemble under-dispersion. Bracket probabilities below integrate this Gaussian; edge = model − market mid.
            </div>
          </div>
        </div>
      </div>

      <PanelBare title="Edge by bracket" meta={
        strategy === "union"
          ? `UNION signal: raw ≥ ${(bracketEdge * 100).toFixed(0)}% OR blend ≥ ${(bracketEdge * 40).toFixed(0)}% · set in top bar`
          : `${strategy === "blend" ? "BLEND" : "RAW"} signal fires when |edge| ≥ ${(bracketEdge * 100).toFixed(0)}% · set in top bar (independent of P&L sim)`
      }>
        <table className="dt">
          <thead><tr>
            <th className="l">Bracket</th>
            {strategy === "union"
              ? <><th>Model P</th><th>Blend P</th></>
              : <th>{strategy === "blend" ? "Blend P" : "Model P"}</th>}
            <th>Market P</th>
            <th>Edge</th>
            <th>Signal</th>
            <th>Resolved</th>
          </tr></thead>
          <tbody>
            {brackets.length === 0 && (
              <tr><td className="l muted" colSpan={strategy === "union" ? 7 : 6} style={{ padding: "16px 12px" }}>
                No brackets for {dateStr}.
              </td></tr>
            )}
            {brackets.map((b, i) => {
              if (strategy === "union") {
                const rawEdge = b.modelP - b.mktP;
                const blendEdge = (b.blendP != null) ? (b.blendP - b.mktP) : null;
                const rawFires = Math.abs(rawEdge) >= bracketEdge;
                const blendFires = blendEdge != null && Math.abs(blendEdge) >= (bracketEdge * 0.4);
                const fires = rawFires || blendFires;
                // Side: take whichever fires; when both fire they agree
                const e = rawFires ? rawEdge : blendEdge;
                const side = e > 0 ? "YES" : "NO";
                const tag = rawFires && blendFires ? "both"
                          : rawFires ? "raw"
                          : blendFires ? "blend" : "";
                return (
                  <tr key={i}>
                    <td className="l hi">{b.label}</td>
                    <td>{(b.modelP * 100).toFixed(0)}%</td>
                    <td>{b.blendP != null ? `${(b.blendP * 100).toFixed(0)}%` : "—"}</td>
                    <td>{(b.mktP * 100).toFixed(0)}%</td>
                    <td><EdgeCell edge={e || 0} /></td>
                    <td>{fires
                      ? <span className={"side " + (side === "YES" ? "yes" : "no")}>
                          BUY {side} <small style={{opacity: 0.6, marginLeft: 4}}>{tag}</small>
                        </span>
                      : <span className="muted">—</span>}</td>
                    <td><span className={"outcome " + (b.resolved === "YES" ? "yes" : "no")}>{b.resolved}</span></td>
                  </tr>
                );
              }
              // Default raw/blend single-prob display
              const probSel = strategy === "blend" && b.blendP != null ? b.blendP : b.modelP;
              const e = probSel - b.mktP;
              const fires = Math.abs(e) >= bracketEdge;
              const side = e > 0 ? "YES" : "NO";
              return (
                <tr key={i}>
                  <td className="l hi">{b.label}</td>
                  <td>{(probSel * 100).toFixed(0)}%</td>
                  <td>{(b.mktP * 100).toFixed(0)}%</td>
                  <td><EdgeCell edge={e} /></td>
                  <td>{fires ? <span className={"side " + (side === "YES" ? "yes" : "no")}>BUY {side}</span> : <span className="muted">—</span>}</td>
                  <td><span className={"outcome " + (b.resolved === "YES" ? "yes" : "no")}>{b.resolved}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </PanelBare>

      <div className="section-label">P&amp;L simulation — tweak the run parameters below</div>
      <PanelBare title="Simulation results" meta={`${d.city} · ${sizing} · |edge| ≥ ${(simEdge * 100).toFixed(0)}%${minEntry ? " · entry ≥ " + minEntry + "¢" : ""}`}>
        {(!d.trades || d.trades.length === 0) && (
          <div style={{ padding: "16px 12px", margin: "8px 0", borderRadius: 6,
                        background: "rgba(255,153,0,0.08)", border: "1px solid rgba(255,153,0,0.3)",
                        color: "var(--warn)", fontFamily: "var(--mono)", fontSize: 12 }}>
            ⏳ {d.city}: backtest data is still backfilling (forecast history for this
            city's traded dates hasn't finished downloading). Best-results will load
            automatically once it's ready — no action needed.
          </div>
        )}
        <SimControls {...{ edge: simEdge, setEdge: setSimEdge, minEntry, setMinEntry,
                           sizing, setSizing, exec, setExec, depth, setDepth,
                           amount, setAmount, bankroll, setBankroll,
                           maxSignals, setMaxSignals, edgeCap, setEdgeCap }} />
        <div className="bt-metrics" style={{ borderBottom: "1px solid var(--border)" }}>
          <BTMetric label="Final balance" value={moneyPlain(sim.final || 0)} sub={pct(sim.ret || 0)} tone={(sim.ret || 0) >= 0 ? "pos" : "neg"} />
          <BTMetric label="Resolved" value={`${Math.round((sim.n || 0) * (sim.win || 0))}/${sim.n || 0}`} sub={`${((sim.win || 0) * 100).toFixed(0)}% win rate`} />
          <BTMetric label="Sharpe (ann.)" value={(sim.sharpe || 0).toFixed(2)} sub="risk-adjusted" tone={(sim.sharpe || 0) >= 1 ? "pos" : ""} />
          <BTMetric label="Max drawdown" value={money(sim.maxDDDollars || 0)} sub={`${pct(sim.maxDD || 0)} peak-to-trough`} tone="neg" />
          <BTMetric label="Missed fills" value={sim.missed || 0} sub="maker didn't fill" tone={(sim.missed || 0) > 0 ? "neg" : ""} />
          <BTMetric label="Filtered / total" value={`${sim.n || 0} / ${sim.total || 0}`} sub="filled / passed filter" />
        </div>
        <div style={{ padding: "12px 12px 4px" }}>
          <BalanceChart
            curve={sim.curve || [bankroll, bankroll]}
            filledTrades={(sim.tradeRecords || []).filter(t => t.fill === "filled")}
          />
        </div>
        <div className="panel-b" style={{ paddingTop: 4 }}>
          <div className="chart-legend"><span><span className="sw" style={{ background: (sim.ret || 0) >= 0 ? "var(--pos)" : "var(--neg)" }} />balance curve · start ${(sim.curve || [1000])[0].toLocaleString()} → ${(sim.final || 0).toLocaleString()}</span></div>
        </div>
      </PanelBare>

      <PanelBare title="Trade-by-trade detail" meta={`every paper trade · ${strategy === "union" ? "UNION" : strategy === "blend" ? "BLEND" : "RAW"} signal · qty/P&L reflect (${sizing}, $${Number(amount).toLocaleString()}/trade, cap ${depth})`}>
        <div className="tbl-scroll" style={{ maxHeight: 280 }}>
          <table className="dt">
            <thead><tr>
              <th className="l">Date</th><th className="l">Bracket</th><th>Side</th>
              <th>{strategy === "blend" ? "Blend P" : "Model P"}</th>
              <th>Market P</th><th>Edge</th><th>Entry</th><th>Qty</th><th>Fill</th><th>Result</th><th>P&amp;L</th>
            </tr></thead>
            <tbody>
              {(sim.tradeRecords || []).length === 0 && <tr><td className="l muted" colSpan="11" style={{ padding: "16px 12px" }}>No trade history.</td></tr>}
              {[...(sim.tradeRecords || [])].reverse().map((t, i) => {
                const skipped = t.fill === "filtered" || t.fill === "below-min" || t.fill === "skipped";
                const isFilled = t.fill === "filled";
                // Strategy-aware fields: side / edge / P depend on raw vs blend selection.
                const showP = t.stratP != null ? t.stratP : t.modelP;
                const showEdge = t.stratEdge != null ? t.stratEdge : t.edge;
                const showSide = t.stratSide ? (t.stratSide === "BUY_YES" ? "YES" : "NO") : t.side;
                const wonShown = t.stratWon != null ? t.stratWon : t.won;
                return (
                  <tr key={i}>
                    <td className="l">{t.date}</td>
                    <td className="l hi">{t.bracket}</td>
                    <td><span className={"side " + (showSide === "YES" ? "yes" : "no")}>{showSide}</span></td>
                    <td>{(showP * 100).toFixed(0)}%</td>
                    <td>{(t.mktP * 100).toFixed(0)}%</td>
                    <td><EdgeCell edge={showEdge} /></td>
                    <td>{t.entry}¢</td>
                    <td className={isFilled ? "hi" : "muted"}>{isFilled ? t.computedQty : "—"}</td>
                    <td><span className={"pill-status " + t.fill}>{t.fill}</span></td>
                    <td>{t.won === null || skipped ? <span className="muted">—</span> : <span className={"outcome " + (wonShown ? "yes" : "no")}>{wonShown ? "WIN" : "LOSS"}</span>}</td>
                    <td className={!isFilled ? "muted" : cls(t.computedPnl)}>{!isFilled ? "—" : money(t.computedPnl)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </PanelBare>

      <PanelBare title="Strategy comparison" meta={`${d.city} · head-to-head model variants · |edge| ≥ ${(simEdge * 100).toFixed(0)}%`}>
        <table className="dt">
          <thead><tr>
            <th className="l">Model variant</th><th>Final balance</th><th>Return</th><th>Sharpe</th><th>Max DD</th><th>Win rate</th><th>Brier</th><th>Trades</th>
          </tr></thead>
          <tbody>
            {strat.length === 0 && <tr><td className="l muted" colSpan="8" style={{ padding: "16px 12px" }}>No strategy comparison data.</td></tr>}
            {strat.map((s, i) => (
              <tr key={i} className={s.chosen ? "chosen" : ""}>
                <td className="l hi">{s.name}{s.chosen && <span className="chosen-tag">live</span>}</td>
                <td className="hi">{moneyPlain(s.final)}</td>
                <td className={cls(s.ret)}>{pct(s.ret)}</td>
                <td className={s.sharpe >= 1 ? "pos" : ""}>{s.sharpe.toFixed(2)}</td>
                <td className="neg">{pct(s.maxDD)}</td>
                <td>{(s.win * 100).toFixed(0)}%</td>
                <td>{s.brier.toFixed(3)}</td>
                <td>{s.n}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </PanelBare>
    </div>
  );
}

// ====================================================================
// STREAMLIT APP SHELL
// ====================================================================
function StreamlitBacktestApp() {
  const [args, setArgs] = useState(window.StreamlitArgs);
  const containerRef = useRef(null);

  useEffect(() => {
    const onArgs = (e) => setArgs(e.detail);
    window.addEventListener("streamlit:args", onArgs);
    return () => window.removeEventListener("streamlit:args", onArgs);
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;
    const send = () => window.StreamlitBridge.sendHeight(document.body.scrollHeight + 40);
    send();
    const ro = new ResizeObserver(send);
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, [args]);

  if (args && args.payload) {
    window.BTDATA = args.payload;
  }
  window.BT_ON_CHANGE = (newState) => {
    window.StreamlitBridge.sendValue(newState);
  };

  if (!args) {
    return <div style={{ padding: 40, color: "var(--text-lo)" }}>Initializing…</div>;
  }
  if (!window.BTDATA) {
    return <div style={{ padding: 40, color: "var(--text-lo)" }}>Waiting for data…</div>;
  }
  return (
    <div ref={containerRef}>
      <BacktestTab key={args.payloadKey || "default"} initialState={args.initialState || {}} />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<StreamlitBacktestApp />);

// Tell Streamlit we're ready to receive args. Must be after mount so the
// render message can flow back into our event listener.
setTimeout(() => window.StreamlitBridge.sendReady(), 50);
