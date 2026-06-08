/* Shared atoms + charts. Exported to window for cross-file use. */
const { useState, useEffect, useRef } = React;

/* ---------- formatters ---------- */
function money(v, { sign = true, dp = 2 } = {}) {
  if (v === null || v === undefined) return "—";
  const s = v < 0 ? "\u2212" : (sign ? "+" : "");
  return s + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}
function moneyPlain(v) {
  if (v === null || v === undefined) return "—";
  return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function pct(v, dp = 1) {
  if (v === null || v === undefined) return "—";
  const s = v < 0 ? "\u2212" : "+";
  return s + Math.abs(v).toFixed(dp) + "%";
}
function cls(v) { return v > 0 ? "pos" : v < 0 ? "neg" : "muted"; }

/* ---------- inline sparkline ---------- */
function Spark({ data, w = 132, h = 34, color }) {
  const vals = data.map(d => d.v);
  const min = Math.min(0, ...vals), max = Math.max(0, ...vals);
  const span = (max - min) || 1;
  const x = i => (i / (data.length - 1)) * w;
  const y = v => h - ((v - min) / span) * h;
  const line = data.map((d, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(d.v).toFixed(1)}`).join(" ");
  const area = `${line} L${w},${h} L0,${h} Z`;
  const last = vals[vals.length - 1];
  const c = color || (last >= 0 ? "var(--pos)" : "var(--neg)");
  const gid = "sg" + Math.random().toString(36).slice(2, 7);
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={c} stopOpacity="0.22" />
          <stop offset="1" stopColor={c} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gid})`} />
      <path d={line} fill="none" stroke={c} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/* ---------- 7-day cumulative P&L line chart (right Y-axis, fin convention) ---------- */
function PnlChart({ data, height = 232 }) {
  const wrapRef = useRef(null);
  const [w, setW] = useState(720);
  const [hover, setHover] = useState(null);
  useEffect(() => {
    const ro = new ResizeObserver(es => { for (const e of es) setW(e.contentRect.width); });
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  const padL = 14, padR = 58, padT = 14, padB = 26;
  const iw = w - padL - padR, ih = height - padT - padB;
  const vals = data.map(d => d.v);
  let min = Math.min(0, ...vals), max = Math.max(0, ...vals);
  const pad = (max - min) * 0.12 || 1; min -= pad; max += pad;
  const span = (max - min) || 1;
  const X = i => padL + (i / (data.length - 1)) * iw;
  const Y = v => padT + (1 - (v - min) / span) * ih;

  // nice-ish ticks
  const ticks = 4;
  const tickVals = Array.from({ length: ticks + 1 }, (_, i) => min + (span * i) / ticks);
  const zeroY = Y(0);

  const last = vals[vals.length - 1];
  const c = last >= 0 ? "var(--pos)" : "var(--neg)";
  const line = data.map((d, i) => `${i === 0 ? "M" : "L"}${X(i).toFixed(1)},${Y(d.v).toFixed(1)}`).join(" ");
  const area = `${line} L${X(data.length - 1)},${zeroY} L${X(0)},${zeroY} Z`;
  const dayLabels = ["6d", "5d", "4d", "3d", "2d", "1d", "yest", "today"];

  return (
    <div className="chart-wrap" ref={wrapRef}>
      <svg width={w} height={height} viewBox={`0 0 ${w} ${height}`}
        onMouseLeave={() => setHover(null)}
        onMouseMove={e => {
          const r = e.currentTarget.getBoundingClientRect();
          const px = (e.clientX - r.left) * (w / r.width);
          let best = 0, bd = 1e9;
          data.forEach((d, i) => { const dist = Math.abs(X(i) - px); if (dist < bd) { bd = dist; best = i; } });
          setHover(best);
        }}>
        <defs>
          <linearGradient id="pnlfill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={c} stopOpacity="0.20" />
            <stop offset="1" stopColor={c} stopOpacity="0.01" />
          </linearGradient>
        </defs>
        {/* gridlines + right axis labels */}
        {tickVals.map((tv, i) => (
          <g key={i}>
            <line x1={padL} x2={padL + iw} y1={Y(tv)} y2={Y(tv)}
              stroke="var(--border)" strokeWidth="1"
              strokeDasharray={Math.abs(tv) < 1e-6 ? "0" : "2 4"} />
            <text x={padL + iw + 8} y={Y(tv) + 3.5} fill="var(--text-faint)"
              style={{ font: "500 10px var(--mono)" }}>{(tv >= 0 ? "" : "\u2212") + "$" + Math.abs(Math.round(tv))}</text>
          </g>
        ))}
        {/* zero line emphasis */}
        <line x1={padL} x2={padL + iw} y1={zeroY} y2={zeroY} stroke="var(--border-strong)" strokeWidth="1" />
        <path d={area} fill="url(#pnlfill)" />
        <path d={line} fill="none" stroke={c} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {/* x labels */}
        {data.map((d, i) => (
          <text key={i} x={X(i)} y={height - 8} textAnchor="middle" fill="var(--text-faint)"
            style={{ font: "500 9.5px var(--mono)" }}>{dayLabels[i] || i}</text>
        ))}
        {/* hover */}
        {hover !== null && (
          <g>
            <line x1={X(hover)} x2={X(hover)} y1={padT} y2={padT + ih} stroke="var(--border-strong)" strokeWidth="1" />
            <circle cx={X(hover)} cy={Y(data[hover].v)} r="3.5" fill={c} stroke="var(--bg-1)" strokeWidth="2" />
            <g transform={`translate(${Math.min(X(hover) + 8, padL + iw - 78)},${padT + 2})`}>
              <rect width="74" height="20" rx="4" fill="var(--bg-3)" stroke="var(--border-strong)" />
              <text x="8" y="14" fill="var(--text-hi)" style={{ font: "600 11px var(--mono)" }}>
                {money(data[hover].v, { sign: true, dp: 0 })}
              </text>
            </g>
          </g>
        )}
      </svg>
    </div>
  );
}

/* ---------- panel wrapper ---------- */
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

/* ---------- risk bar ---------- */
function RiskBar({ name, used, limit, fmt }) {
  const r = Math.min(1, used / limit);
  const lvl = r >= 0.8 ? "err" : r >= 0.5 ? "warn" : "ok";
  return (
    <div className="riskrow">
      <div className="rl">
        <span className="name">{name}</span>
        <span className="val">{fmt ? fmt(used) : used} <span style={{ color: "var(--text-faint)" }}>/ {fmt ? fmt(limit) : limit}</span></span>
      </div>
      <div className="bar"><span className={lvl} style={{ width: (r * 100).toFixed(0) + "%" }} /></div>
    </div>
  );
}

Object.assign(window, { money, moneyPlain, pct, cls, Spark, PnlChart, Panel, PanelBare, RiskBar });
