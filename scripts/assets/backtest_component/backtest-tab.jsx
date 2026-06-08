/* Backtest / Forecast View tab */
const { useState: useStateB, useEffect: useEffectB, useRef: useRefB } = React;

function erf(x) {
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return x >= 0 ? y : -y;
}
const normCdf = (x, mu, s) => 0.5 * (1 + erf((x - mu) / (s * Math.SQRT2)));
const normPdf = (x, mu, s) => Math.exp(-0.5 * ((x - mu) / s) ** 2) / (s * Math.sqrt(2 * Math.PI));

/* ---------- ensemble distribution chart ---------- */
function EnsembleChart({ d, height = 248 }) {
  const wrapRef = useRefB(null);
  const [w, setW] = useStateB(760);
  useEffectB(() => {
    const ro = new ResizeObserver(es => { for (const e of es) setW(e.contentRect.width); });
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  const padL = 16, padR = 16, padT = 16, padB = 30;
  const iw = w - padL - padR, ih = height - padT - padB;
  const lo = Math.floor(Math.min(...d.members, d.observed) - 1.5);
  const hi = Math.ceil(Math.max(...d.members, d.observed) + 1.5);
  const X = t => padL + ((t - lo) / (hi - lo)) * iw;

  // 1°F histogram
  const bins = {};
  for (let t = lo; t <= hi; t++) bins[t] = 0;
  d.members.forEach(m => { const b = Math.round(m); if (bins[b] !== undefined) bins[b]++; });
  const maxCount = Math.max(...Object.values(bins), 1);
  const barW = iw / (hi - lo) * 0.82;

  // gaussian overlay scaled to peak bar
  const pdfPeak = normPdf(d.emosMu, d.emosMu, d.emosSigma);
  const curve = [];
  for (let i = 0; i <= 80; i++) {
    const t = lo + (hi - lo) * (i / 80);
    const yv = (normPdf(t, d.emosMu, d.emosSigma) / pdfPeak) * (maxCount * 0.92);
    curve.push(`${i === 0 ? "M" : "L"}${X(t).toFixed(1)},${(padT + ih - (yv / maxCount) * ih).toFixed(1)}`);
  }

  const boundaries = [...new Set(d.brackets.flatMap(b => [b.lo, b.hi]).filter(v => v > lo && v < hi && Math.abs(v) < 90))];

  return (
    <div className="chart-wrap" ref={wrapRef}>
      <svg width={w} height={height} viewBox={`0 0 ${w} ${height}`}>
        {/* bracket boundary lines */}
        {boundaries.map((bv, i) => (
          <line key={i} x1={X(bv + 0.5)} x2={X(bv + 0.5)} y1={padT} y2={padT + ih}
            stroke="var(--border)" strokeWidth="1" strokeDasharray="2 4" />
        ))}
        {/* histogram bars */}
        {Object.entries(bins).map(([t, c], i) => c > 0 && (
          <rect key={i} x={X(+t) - barW / 2} y={padT + ih - (c / maxCount) * ih}
            width={barW} height={(c / maxCount) * ih} rx="1.5" fill="var(--bg-3)" />
        ))}
        {/* EMOS gaussian */}
        <path d={curve.join(" ")} fill="none" stroke="var(--warn)" strokeWidth="2" />
        {/* mean line */}
        <line x1={X(d.ensMean)} x2={X(d.ensMean)} y1={padT} y2={padT + ih} stroke="var(--text-lo)" strokeWidth="1" strokeDasharray="3 3" />
        {/* observed high */}
        <line x1={X(d.observed)} x2={X(d.observed)} y1={padT - 2} y2={padT + ih} stroke="var(--pos)" strokeWidth="2" />
        <g transform={`translate(${Math.min(X(d.observed) + 6, padL + iw - 70)},${padT + 4})`}>
          <rect width="64" height="18" rx="4" fill="var(--pos-dim)" stroke="var(--pos-line)" />
          <text x="7" y="13" fill="var(--pos)" style={{ font: "600 10px var(--mono)" }}>obs {d.observed}°</text>
        </g>
        {/* x axis temp labels */}
        {Array.from({ length: hi - lo + 1 }, (_, i) => lo + i).filter(t => t % 2 === 0).map((t, i) => (
          <text key={i} x={X(t)} y={height - 9} textAnchor="middle" className="chart-axis-x">{t}°</text>
        ))}
      </svg>
    </div>
  );
}

/* ---------- generic balance curve ---------- */
function BalanceChart({ curve, height = 210 }) {
  const wrapRef = useRefB(null);
  const [w, setW] = useStateB(720);
  useEffectB(() => {
    const ro = new ResizeObserver(es => { for (const e of es) setW(e.contentRect.width); });
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);
  const padL = 14, padR = 56, padT = 14, padB = 22;
  const iw = w - padL - padR, ih = height - padT - padB;
  const start = curve[0];
  let min = Math.min(...curve), max = Math.max(...curve);
  const pd = (max - min) * 0.1 || 1; min -= pd; max += pd;
  const span = max - min;
  const X = i => padL + (i / (curve.length - 1)) * iw;
  const Y = v => padT + (1 - (v - min) / span) * ih;
  const last = curve[curve.length - 1];
  const c = last >= start ? "var(--pos)" : "var(--neg)";
  const line = curve.map((v, i) => `${i === 0 ? "M" : "L"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const ticks = 4;
  const tickVals = Array.from({ length: ticks + 1 }, (_, i) => min + (span * i) / ticks);
  return (
    <div className="chart-wrap" ref={wrapRef}>
      <svg width={w} height={height} viewBox={`0 0 ${w} ${height}`}>
        <defs><linearGradient id="balfill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={c} stopOpacity="0.16" /><stop offset="1" stopColor={c} stopOpacity="0.01" />
        </linearGradient></defs>
        {tickVals.map((tv, i) => (
          <g key={i}>
            <line x1={padL} x2={padL + iw} y1={Y(tv)} y2={Y(tv)} stroke="var(--border)" strokeWidth="1" strokeDasharray="2 4" />
            <text x={padL + iw + 8} y={Y(tv) + 3.5} fill="var(--text-faint)" style={{ font: "500 10px var(--mono)" }}>${Math.round(tv)}</text>
          </g>
        ))}
        <line x1={padL} x2={padL + iw} y1={Y(start)} y2={Y(start)} stroke="var(--border-strong)" strokeWidth="1" />
        <path d={`${line} L${X(curve.length - 1)},${Y(min)} L${X(0)},${Y(min)} Z`} fill="url(#balfill)" />
        <path d={line} fill="none" stroke={c} strokeWidth="2" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

/* ---------- forecast context bar (top) ---------- */
function ControlsBar({ platform, setPlatform, cityCode, setCityCode, date, setDate, edge, setEdge }) {
  // Cities come from whatever BTDATA was loaded (data-driven, not hardcoded).
  const availableCities = (window.BTDATA && window.BTDATA.cities) || [cityCode];
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
          {setDate
            ? <input type="date" value={date} onChange={e => setDate(e.target.value)} />
            : <span className="static-val">{date}</span>}
        </div>
        {setEdge && (
          <div className="ctrl">
            <span className="cl">Edge filter</span>
            <select value={edge} onChange={e => setEdge(+e.target.value)}>
              {[0.05, 0.10, 0.15, 0.20, 0.25, 0.30].map(v => <option key={v} value={v}>≥ {(v * 100).toFixed(0)}%</option>)}
            </select>
          </div>
        )}
      </div>
    </div>
  );
}

/* ---------- simulation parameter strip (inside P&L sim panel) ---------- */
function SimControls({ edge, setEdge, minEntry, setMinEntry, sizing, setSizing, exec, setExec, depth, setDepth, amount, setAmount }) {
  return (
    <div className="controls sim-controls">
      <div className="ctrl"><span className="cl">Edge filter</span>
        <select value={edge} onChange={e => setEdge(+e.target.value)}>
          {[0.05, 0.10, 0.15, 0.20, 0.25].map(v => <option key={v} value={v}>≥ {(v * 100).toFixed(0)}%</option>)}
        </select>
      </div>
      <div className="ctrl"><span className="cl">Min entry</span>
        <select value={minEntry} onChange={e => setMinEntry(+e.target.value)}>
          {[0, 5, 10, 20, 30].map(v => <option key={v} value={v}>{v === 0 ? "any" : "≥ " + v + "¢"}</option>)}
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
      <div className="ctrl"><span className="cl">Execution</span>
        <select value={exec} onChange={e => setExec(e.target.value)}>
          <option>post_inside_spread</option><option>cross_at_ask</option><option>cross_with_premium</option>
        </select>
      </div>
      <div className="ctrl"><span className="cl">Depth cap</span>
        <input type="number" value={depth} onChange={e => setDepth(e.target.value)} step="50" />
      </div>
    </div>
  );
}

function BTMetric({ label, value, sub, tone }) {
  return <div className="m"><div className="ml">{label}</div><div className={"mv " + (tone || "")}>{value}</div><div className="ms">{sub}</div></div>;
}

function BacktestTab({ initialState }) {
  const init = initialState || {};
  const defaultCity = init.cityCode || (window.BTDATA && window.BTDATA.cities && window.BTDATA.cities[0]) || "KORD";
  const [platform, setPlatform_] = useStateB(init.platform || "Kalshi");
  const [cityCode, setCityCode_] = useStateB(defaultCity);
  const [sizing, setSizing_] = useStateB(init.sizing || "amount");
  const [exec, setExec_] = useStateB(init.exec || "post_inside_spread");
  const [depth, setDepth_] = useStateB(init.depth ?? 500);
  const [edge, setEdge_] = useStateB(init.edge ?? 0.10);
  const [minEntry, setMinEntry_] = useStateB(init.minEntry ?? 0);
  const [amount, setAmount_] = useStateB(init.amount ?? 50);

  // Notify the Streamlit Python layer whenever any state changes so it can
  // recompute the payload (city/date trigger fresh data; sizing/edge/exec/
  // depth/minEntry/amount trigger a fresh sim run with new parameters).
  const notify = (partial) => {
    if (typeof window.BT_ON_CHANGE === "function") {
      window.BT_ON_CHANGE({
        platform, cityCode, sizing, exec, depth, edge, minEntry, amount,
        date: init.date || (window.BTDATA[cityCode] || {}).date,
        ...partial,
      });
    }
  };
  const setPlatform  = (v) => { setPlatform_(v);  notify({ platform: v }); };
  const setCityCode  = (v) => { setCityCode_(v);  notify({ cityCode: v }); };
  const setSizing    = (v) => { setSizing_(v);    notify({ sizing: v }); };
  const setExec      = (v) => { setExec_(v);      notify({ exec: v }); };
  const setDepth     = (v) => { setDepth_(Number(v) || 0); notify({ depth: Number(v) || 0 }); };
  const setEdge      = (v) => { setEdge_(Number(v));       notify({ edge: Number(v) }); };
  const setMinEntry  = (v) => { setMinEntry_(Number(v));   notify({ minEntry: Number(v) }); };
  const setAmount    = (v) => { setAmount_(Number(v) || 0); notify({ amount: Number(v) || 0 }); };

  const d = window.BTDATA[cityCode] || window.BTDATA[defaultCity];
  if (!d) {
    return <div style={{ padding: 24, color: "var(--text-lo)" }}>No data for {cityCode}.</div>;
  }
  const sim = d.sim[sizing] || d.sim.amount || {};

  const setDate = (v) => { notify({ date: v }); };

  return (
    <div className="wrap">
      <ControlsBar {...{ platform, setPlatform, cityCode, setCityCode,
                          date: d.date, setDate, edge, setEdge }} />

      {/* FORECAST */}
      <div className="section-label">Forecast — combined GEFS + ECMWF ensemble · {d.city} · {d.date}</div>
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

      {/* EDGE BY BRACKET */}
      <PanelBare title="Edge by bracket" meta={`signal fires when |edge| ≥ ${(edge * 100).toFixed(0)}% · set in P&L parameters`}>
        <table className="dt">
          <thead><tr>
            <th className="l">Bracket</th><th>Model P</th><th>Market P</th><th>Edge</th><th>Signal</th><th>Resolved</th>
          </tr></thead>
          <tbody>
            {d.brackets.map((b, i) => {
              const e = b.modelP - b.mktP;
              const fires = Math.abs(e) >= edge;
              const side = e > 0 ? "YES" : "NO";
              return (
                <tr key={i}>
                  <td className="l hi">{b.label}</td>
                  <td>{(b.modelP * 100).toFixed(0)}%</td>
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

      {/* P&L SIMULATION */}
      <div className="section-label">P&amp;L simulation — tweak the run parameters below</div>
      <PanelBare title="Simulation results" meta={`${d.city} · ${sizing} · |edge| ≥ ${(edge * 100).toFixed(0)}%${minEntry ? " · entry ≥ " + minEntry + "¢" : ""}`}>
        <SimControls {...{ edge, setEdge, minEntry, setMinEntry, sizing, setSizing, exec, setExec, depth, setDepth, amount, setAmount }} />
        <div className="bt-metrics" style={{ borderBottom: "1px solid var(--border)" }}>
          <BTMetric label="Final balance" value={moneyPlain(sim.final)} sub={pct(sim.ret)} tone={sim.ret >= 0 ? "pos" : "neg"} />
          <BTMetric label="Resolved" value={`${Math.round(sim.n * sim.win)}/${sim.n}`} sub={`${(sim.win * 100).toFixed(0)}% win rate`} />
          <BTMetric label="Sharpe (ann.)" value={sim.sharpe.toFixed(2)} sub="risk-adjusted" tone={sim.sharpe >= 1 ? "pos" : ""} />
          <BTMetric label="Max drawdown" value={pct(sim.maxDD)} sub="peak-to-trough" tone="neg" />
          <BTMetric label="Pending" value={sim.pending} sub="unresolved" />
          <BTMetric label="Filtered / total" value={`${sim.n} / ${sim.total}`} sub="passed filter" />
        </div>
        <div style={{ padding: "12px 12px 4px" }}><BalanceChart curve={sim.curve} /></div>
        <div className="panel-b" style={{ paddingTop: 4 }}>
          <div className="chart-legend"><span><span className="sw" style={{ background: sim.ret >= 0 ? "var(--pos)" : "var(--neg)" }} />balance curve · start ${sim.curve[0].toLocaleString()} → ${sim.final.toLocaleString()}</span></div>
        </div>
      </PanelBare>

      {/* TRADE LOG */}
      <PanelBare title="Trade-by-trade detail" meta="every paper trade in the curve">
        <div className="tbl-scroll" style={{ maxHeight: 280 }}>
          <table className="dt">
            <thead><tr>
              <th className="l">Date</th><th className="l">Bracket</th><th>Side</th><th>Model P</th><th>Market P</th><th>Edge</th><th>Entry</th><th>Qty</th><th>Fill</th><th>Result</th><th>P&amp;L</th>
            </tr></thead>
            <tbody>
              {d.trades.map((t, i) => (
                <tr key={i}>
                  <td className="l">{t.date}</td>
                  <td className="l hi">{t.bracket}</td>
                  <td><span className={"side " + (t.side === "YES" ? "yes" : "no")}>{t.side}</span></td>
                  <td>{(t.modelP * 100).toFixed(0)}%</td>
                  <td>{(t.mktP * 100).toFixed(0)}%</td>
                  <td><EdgeCell edge={t.edge} /></td>
                  <td>{t.entry}¢</td>
                  <td>{t.qty}</td>
                  <td><span className={"pill-status " + t.fill}>{t.fill}</span></td>
                  <td>{t.won === null ? <span className="muted">—</span> : <span className={"outcome " + (t.won ? "yes" : "no")}>{t.won ? "WIN" : "LOSS"}</span>}</td>
                  <td className={t.fill === "unfilled" ? "muted" : cls(t.pnl)}>{t.fill === "unfilled" ? "—" : money(t.pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </PanelBare>

      {/* STRATEGY COMPARISON */}
      <PanelBare title="Strategy comparison" meta={`${d.city} · head-to-head model variants · |edge| ≥ ${(edge * 100).toFixed(0)}%`}>
        <table className="dt">
          <thead><tr>
            <th className="l">Model variant</th><th>Final balance</th><th>Return</th><th>Sharpe</th><th>Max DD</th><th>Win rate</th><th>Brier</th><th>Trades</th>
          </tr></thead>
          <tbody>
            {d.strat.map((s, i) => (
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

Object.assign(window, { BacktestTab });
