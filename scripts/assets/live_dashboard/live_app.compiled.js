// ===== components.jsx =====
/* Shared atoms + charts. Exported to window for cross-file use. */
const {
  useState,
  useEffect,
  useRef
} = React;

/* ---------- formatters ---------- */
function money(v, {
  sign = true,
  dp = 2
} = {}) {
  if (v === null || v === undefined) return "—";
  const s = v < 0 ? "\u2212" : sign ? "+" : "";
  return s + "$" + Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp
  });
}
function moneyPlain(v) {
  if (v === null || v === undefined) return "—";
  return "$" + v.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}
function pct(v, dp = 1) {
  if (v === null || v === undefined) return "—";
  const s = v < 0 ? "\u2212" : "+";
  return s + Math.abs(v).toFixed(dp) + "%";
}
function cls(v) {
  return v > 0 ? "pos" : v < 0 ? "neg" : "muted";
}

/* ---------- inline sparkline ---------- */
function Spark({
  data,
  w = 132,
  h = 34,
  color
}) {
  const vals = data.map(d => d.v);
  const min = Math.min(0, ...vals),
    max = Math.max(0, ...vals);
  const span = max - min || 1;
  const x = i => i / (data.length - 1) * w;
  const y = v => h - (v - min) / span * h;
  const line = data.map((d, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(d.v).toFixed(1)}`).join(" ");
  const area = `${line} L${w},${h} L0,${h} Z`;
  const last = vals[vals.length - 1];
  const c = color || (last >= 0 ? "var(--pos)" : "var(--neg)");
  const gid = "sg" + Math.random().toString(36).slice(2, 7);
  return /*#__PURE__*/React.createElement("svg", {
    width: w,
    height: h,
    viewBox: `0 0 ${w} ${h}`
  }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
    id: gid,
    x1: "0",
    y1: "0",
    x2: "0",
    y2: "1"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0",
    stopColor: c,
    stopOpacity: "0.22"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "1",
    stopColor: c,
    stopOpacity: "0"
  }))), /*#__PURE__*/React.createElement("path", {
    d: area,
    fill: `url(#${gid})`
  }), /*#__PURE__*/React.createElement("path", {
    d: line,
    fill: "none",
    stroke: c,
    strokeWidth: "1.5",
    strokeLinejoin: "round",
    strokeLinecap: "round"
  }));
}

/* ---------- 7-day cumulative P&L line chart (right Y-axis, fin convention) ---------- */
function PnlChart({
  data,
  height = 232
}) {
  const wrapRef = useRef(null);
  const [w, setW] = useState(720);
  const [hover, setHover] = useState(null);
  useEffect(() => {
    const ro = new ResizeObserver(es => {
      for (const e of es) setW(e.contentRect.width);
    });
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);
  const padL = 14,
    padR = 58,
    padT = 14,
    padB = 26;
  const iw = w - padL - padR,
    ih = height - padT - padB;
  const vals = data.map(d => d.v);
  let min = Math.min(0, ...vals),
    max = Math.max(0, ...vals);
  const pad = (max - min) * 0.12 || 1;
  min -= pad;
  max += pad;
  const span = max - min || 1;
  const X = i => padL + i / (data.length - 1) * iw;
  const Y = v => padT + (1 - (v - min) / span) * ih;

  // nice-ish ticks
  const ticks = 4;
  const tickVals = Array.from({
    length: ticks + 1
  }, (_, i) => min + span * i / ticks);
  const zeroY = Y(0);
  const last = vals[vals.length - 1];
  const c = last >= 0 ? "var(--pos)" : "var(--neg)";
  const line = data.map((d, i) => `${i === 0 ? "M" : "L"}${X(i).toFixed(1)},${Y(d.v).toFixed(1)}`).join(" ");
  const area = `${line} L${X(data.length - 1)},${zeroY} L${X(0)},${zeroY} Z`;
  const dayLabels = ["6d", "5d", "4d", "3d", "2d", "1d", "yest", "today"];
  return /*#__PURE__*/React.createElement("div", {
    className: "chart-wrap",
    ref: wrapRef
  }, /*#__PURE__*/React.createElement("svg", {
    width: w,
    height: height,
    viewBox: `0 0 ${w} ${height}`,
    onMouseLeave: () => setHover(null),
    onMouseMove: e => {
      const r = e.currentTarget.getBoundingClientRect();
      const px = (e.clientX - r.left) * (w / r.width);
      let best = 0,
        bd = 1e9;
      data.forEach((d, i) => {
        const dist = Math.abs(X(i) - px);
        if (dist < bd) {
          bd = dist;
          best = i;
        }
      });
      setHover(best);
    }
  }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
    id: "pnlfill",
    x1: "0",
    y1: "0",
    x2: "0",
    y2: "1"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0",
    stopColor: c,
    stopOpacity: "0.20"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "1",
    stopColor: c,
    stopOpacity: "0.01"
  }))), tickVals.map((tv, i) => /*#__PURE__*/React.createElement("g", {
    key: i
  }, /*#__PURE__*/React.createElement("line", {
    x1: padL,
    x2: padL + iw,
    y1: Y(tv),
    y2: Y(tv),
    stroke: "var(--border)",
    strokeWidth: "1",
    strokeDasharray: Math.abs(tv) < 1e-6 ? "0" : "2 4"
  }), /*#__PURE__*/React.createElement("text", {
    x: padL + iw + 8,
    y: Y(tv) + 3.5,
    fill: "var(--text-faint)",
    style: {
      font: "500 10px var(--mono)"
    }
  }, (tv >= 0 ? "" : "\u2212") + "$" + Math.abs(Math.round(tv))))), /*#__PURE__*/React.createElement("line", {
    x1: padL,
    x2: padL + iw,
    y1: zeroY,
    y2: zeroY,
    stroke: "var(--border-strong)",
    strokeWidth: "1"
  }), /*#__PURE__*/React.createElement("path", {
    d: area,
    fill: "url(#pnlfill)"
  }), /*#__PURE__*/React.createElement("path", {
    d: line,
    fill: "none",
    stroke: c,
    strokeWidth: "2",
    strokeLinejoin: "round",
    strokeLinecap: "round"
  }), data.map((d, i) => /*#__PURE__*/React.createElement("text", {
    key: i,
    x: X(i),
    y: height - 8,
    textAnchor: "middle",
    fill: "var(--text-faint)",
    style: {
      font: "500 9.5px var(--mono)"
    }
  }, dayLabels[i] || i)), hover !== null && /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("line", {
    x1: X(hover),
    x2: X(hover),
    y1: padT,
    y2: padT + ih,
    stroke: "var(--border-strong)",
    strokeWidth: "1"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: X(hover),
    cy: Y(data[hover].v),
    r: "3.5",
    fill: c,
    stroke: "var(--bg-1)",
    strokeWidth: "2"
  }), /*#__PURE__*/React.createElement("g", {
    transform: `translate(${Math.min(X(hover) + 8, padL + iw - 78)},${padT + 2})`
  }, /*#__PURE__*/React.createElement("rect", {
    width: "74",
    height: "20",
    rx: "4",
    fill: "var(--bg-3)",
    stroke: "var(--border-strong)"
  }), /*#__PURE__*/React.createElement("text", {
    x: "8",
    y: "14",
    fill: "var(--text-hi)",
    style: {
      font: "600 11px var(--mono)"
    }
  }, money(data[hover].v, {
    sign: true,
    dp: 0
  }))))));
}

/* ---------- panel wrapper ---------- */
function Panel({
  title,
  meta,
  children,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "panel",
    style: style
  }, /*#__PURE__*/React.createElement("div", {
    className: "panel-h"
  }, /*#__PURE__*/React.createElement("h3", null, title), meta && /*#__PURE__*/React.createElement("span", {
    className: "meta"
  }, meta)), /*#__PURE__*/React.createElement("div", {
    className: "panel-b"
  }, children));
}
function PanelBare({
  title,
  meta,
  children,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "panel",
    style: style
  }, /*#__PURE__*/React.createElement("div", {
    className: "panel-h"
  }, /*#__PURE__*/React.createElement("h3", null, title), meta && /*#__PURE__*/React.createElement("span", {
    className: "meta"
  }, meta)), children);
}

/* ---------- risk bar ---------- */
function RiskBar({
  name,
  used,
  limit,
  fmt
}) {
  const r = Math.min(1, used / limit);
  const lvl = r >= 0.8 ? "err" : r >= 0.5 ? "warn" : "ok";
  return /*#__PURE__*/React.createElement("div", {
    className: "riskrow"
  }, /*#__PURE__*/React.createElement("div", {
    className: "rl"
  }, /*#__PURE__*/React.createElement("span", {
    className: "name"
  }, name), /*#__PURE__*/React.createElement("span", {
    className: "val"
  }, fmt ? fmt(used) : used, " ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-faint)"
    }
  }, "/ ", fmt ? fmt(limit) : limit))), /*#__PURE__*/React.createElement("div", {
    className: "bar"
  }, /*#__PURE__*/React.createElement("span", {
    className: lvl,
    style: {
      width: (r * 100).toFixed(0) + "%"
    }
  })));
}
Object.assign(window, {
  money,
  moneyPlain,
  pct,
  cls,
  Spark,
  PnlChart,
  Panel,
  PanelBare,
  RiskBar
});

// ===== live-tab.jsx =====
/* Live Trading tab */
const {
  useState: useStateL
} = React;
function Hero({
  d
}) {
  const t = d.today,
    c = d.cumulative;
  return /*#__PURE__*/React.createElement("div", {
    className: "hero"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "Today's P&L"), /*#__PURE__*/React.createElement("div", {
    className: "v " + cls(t.total)
  }, money(t.total)), /*#__PURE__*/React.createElement("div", {
    className: "sub"
  }, /*#__PURE__*/React.createElement("span", null, "realized ", /*#__PURE__*/React.createElement("b", {
    className: cls(t.realized)
  }, money(t.realized))), /*#__PURE__*/React.createElement("span", null, "unrealized ", /*#__PURE__*/React.createElement("b", {
    className: cls(t.unrealized)
  }, money(t.unrealized))), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, t.trades), " trades · ", /*#__PURE__*/React.createElement("b", null, t.open), " open"))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "Cumulative P&L ", /*#__PURE__*/React.createElement("span", {
    className: "tag-pill"
  }, "since first live trade")), /*#__PURE__*/React.createElement("div", {
    className: "v " + cls(c.total)
  }, money(c.total)), /*#__PURE__*/React.createElement("div", {
    className: "sub"
  }, /*#__PURE__*/React.createElement("span", null, "return ", /*#__PURE__*/React.createElement("b", {
    className: cls(c.returnPct)
  }, pct(c.returnPct))), /*#__PURE__*/React.createElement("span", null, "win rate ", /*#__PURE__*/React.createElement("b", null, (c.winRate * 100).toFixed(0), "%")), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, c.nSettled), " settled")), /*#__PURE__*/React.createElement("div", {
    className: "spark"
  }, /*#__PURE__*/React.createElement(Spark, {
    data: d.series
  }))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "k"
  }, "Cash · Portfolio ", /*#__PURE__*/React.createElement("span", {
    className: "tag-pill"
  }, "free $ · total a/c value")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: 18,
      alignItems: "baseline"
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: "var(--text-lo)",
      letterSpacing: "0.1em",
      textTransform: "uppercase"
    }
  }, "cash"), /*#__PURE__*/React.createElement("div", {
    className: "v sm",
    style: {
      color: "var(--text-hi)"
    }
  }, moneyPlain(d.cashBalance != null ? d.cashBalance : d.balance))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "mono",
    style: {
      fontSize: 11,
      color: "var(--text-lo)",
      letterSpacing: "0.1em",
      textTransform: "uppercase"
    }
  }, "portfolio"), /*#__PURE__*/React.createElement("div", {
    className: "v sm pos"
  }, moneyPlain(d.balance)))), /*#__PURE__*/React.createElement("div", {
    className: "sub"
  }, /*#__PURE__*/React.createElement("span", null, "position value ", /*#__PURE__*/React.createElement("b", null, moneyPlain(d.portfolioValue || 0))), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, d.openOrders.contracts.toLocaleString()), " contracts · ", /*#__PURE__*/React.createElement("b", null, d.openOrders.count), " orders"))));
}
function StatusStrip({
  d,
  countdown
}) {
  const killOk = d.killArmed;
  return /*#__PURE__*/React.createElement("div", {
    className: "status-strip"
  }, /*#__PURE__*/React.createElement("div", {
    className: "chip"
  }, /*#__PURE__*/React.createElement("span", {
    className: "ico " + (killOk ? "ok" : "err")
  }), /*#__PURE__*/React.createElement("span", {
    className: "txt"
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "Kill switch"), /*#__PURE__*/React.createElement("span", {
    className: "d",
    style: {
      color: killOk ? "var(--pos)" : "var(--neg)"
    }
  }, killOk ? "ARMED" : "TRIGGERED"))), /*#__PURE__*/React.createElement("div", {
    className: "chip"
  }, /*#__PURE__*/React.createElement("span", {
    className: "ico " + (d.nextCron.inMin === null ? "err" : "ok")
  }), /*#__PURE__*/React.createElement("span", {
    className: "txt"
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "Next cron · ", d.nextCron.label), /*#__PURE__*/React.createElement("span", {
    className: "d"
  }, d.nextCron.at, " ", d.nextCron.inMin !== null && /*#__PURE__*/React.createElement("small", null, "· in ", countdown)))), /*#__PURE__*/React.createElement("div", {
    className: "chip"
  }, /*#__PURE__*/React.createElement("span", {
    className: "ico " + (d.openOrders.count > 0 ? "ok" : "")
  }), /*#__PURE__*/React.createElement("span", {
    className: "txt"
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "Open orders"), /*#__PURE__*/React.createElement("span", {
    className: "d"
  }, d.openOrders.count, " resting ", /*#__PURE__*/React.createElement("small", null, "· ", d.openOrders.contracts.toLocaleString(), " contracts")))), /*#__PURE__*/React.createElement("div", {
    className: "chip"
  }, /*#__PURE__*/React.createElement("span", {
    className: "ico " + (d.hrrr.status === "ok" ? "ok" : "warn")
  }), /*#__PURE__*/React.createElement("span", {
    className: "txt"
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "HRRR data"), /*#__PURE__*/React.createElement("span", {
    className: "d",
    style: {
      color: d.hrrr.status === "ok" ? "var(--text-hi)" : "var(--warn)"
    }
  }, d.hrrr.status === "ok" ? "fresh" : "stale", " ", /*#__PURE__*/React.createElement("small", null, "· ", d.hrrr.age, " ago")))), /*#__PURE__*/React.createElement("div", {
    className: "chip"
  }, /*#__PURE__*/React.createElement("span", {
    className: "ico ok"
  }), /*#__PURE__*/React.createElement("span", {
    className: "txt"
  }, /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "Positions"), /*#__PURE__*/React.createElement("span", {
    className: "d"
  }, d.positions.length, " open ", /*#__PURE__*/React.createElement("small", null, "· ", d.cities.filter(c => c.status === "active").length, "/2 cities live")))));
}
function KillBanner({
  d
}) {
  if (d.killArmed) return null;
  return /*#__PURE__*/React.createElement("div", {
    className: "alert"
  }, /*#__PURE__*/React.createElement("span", {
    className: "bang"
  }, "⛔"), /*#__PURE__*/React.createElement("div", {
    className: "body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "t"
  }, "Kill switch triggered — all trading halted"), /*#__PURE__*/React.createElement("div", {
    className: "d"
  }, d.killReason)), /*#__PURE__*/React.createElement("span", {
    className: "ts"
  }, "15:12:04 UTC"));
}
function CityCard({
  c
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "panel city"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ch"
  }, /*#__PURE__*/React.createElement("span", {
    className: "nm"
  }, c.name), /*#__PURE__*/React.createElement("span", {
    className: "code"
  }, c.code), /*#__PURE__*/React.createElement("span", {
    className: "badge " + (c.status === "active" ? "active" : "halted")
  }, c.status), /*#__PURE__*/React.createElement("span", {
    className: "model"
  }, c.model)), /*#__PURE__*/React.createElement("div", {
    className: "cbody"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ml"
  }, "Realized"), /*#__PURE__*/React.createElement("div", {
    className: "mv " + cls(c.realized)
  }, money(c.realized)), /*#__PURE__*/React.createElement("div", {
    className: "ms"
  }, "settled")), /*#__PURE__*/React.createElement("div", {
    className: "m"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ml"
  }, "Unrealized"), /*#__PURE__*/React.createElement("div", {
    className: "mv " + cls(c.unrealized)
  }, money(c.unrealized)), /*#__PURE__*/React.createElement("div", {
    className: "ms"
  }, "open mark")), /*#__PURE__*/React.createElement("div", {
    className: "m"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ml"
  }, "Today"), /*#__PURE__*/React.createElement("div", {
    className: "mv " + cls(c.today)
  }, money(c.today)), /*#__PURE__*/React.createElement("div", {
    className: "ms"
  }, c.orders, " orders"))), /*#__PURE__*/React.createElement("div", {
    className: "cfoot"
  }, c.haltNote ? /*#__PURE__*/React.createElement("div", {
    className: "halt-note"
  }, c.haltNote) : /*#__PURE__*/React.createElement("div", {
    className: "activity"
  }, /*#__PURE__*/React.createElement("span", null, "budget ", /*#__PURE__*/React.createElement("b", null, "$", c.budget)), /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("b", null, c.contracts.toLocaleString()), " contracts"), /*#__PURE__*/React.createElement("span", null, "edge ≥ ", /*#__PURE__*/React.createElement("b", null, c.edgeThresh)), /*#__PURE__*/React.createElement("span", null, "size ", /*#__PURE__*/React.createElement("b", null, c.stake))), /*#__PURE__*/React.createElement(RiskBar, {
    name: "Cumulative",
    used: c.risk.cumUsed,
    limit: c.risk.cumKill,
    fmt: v => "$" + v.toFixed(0)
  }), /*#__PURE__*/React.createElement(RiskBar, {
    name: "Today",
    used: c.risk.todayUsed,
    limit: c.risk.todayKill,
    fmt: v => "$" + v.toFixed(0)
  })));
}
function AggRisk({
  d
}) {
  const a = d.agg;
  const cumUsed = a.cumPnl < 0 ? Math.abs(a.cumPnl) : 0;
  const todayUsed = a.todayPnl < 0 ? Math.abs(a.todayPnl) : 0;
  return /*#__PURE__*/React.createElement("div", {
    className: "panel",
    style: {
      display: "flex",
      flexDirection: "column"
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "panel-h"
  }, /*#__PURE__*/React.createElement("h3", null, "Aggregate risk envelope"), /*#__PURE__*/React.createElement("span", {
    className: "meta"
  }, "cross-city")), /*#__PURE__*/React.createElement("div", {
    className: "panel-b aggm",
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "a"
  }, /*#__PURE__*/React.createElement("div", {
    className: "top"
  }, /*#__PURE__*/React.createElement("span", {
    className: "lbl"
  }, "Cumulative drawdown"), /*#__PURE__*/React.createElement("span", {
    className: "num " + cls(a.cumPnl)
  }, money(a.cumPnl))), /*#__PURE__*/React.createElement("div", {
    className: "bar"
  }, /*#__PURE__*/React.createElement("span", {
    className: cumUsed / a.cumKill >= 0.8 ? "err" : cumUsed / a.cumKill >= 0.5 ? "warn" : "ok",
    style: {
      width: Math.min(100, cumUsed / a.cumKill * 100) + "%"
    }
  })), /*#__PURE__*/React.createElement("span", {
    className: "cap"
  }, "kill at −$", a.cumKill, " · ", (cumUsed / a.cumKill * 100).toFixed(0), "% used")), /*#__PURE__*/React.createElement("div", {
    className: "a"
  }, /*#__PURE__*/React.createElement("div", {
    className: "top"
  }, /*#__PURE__*/React.createElement("span", {
    className: "lbl"
  }, "Daily loss"), /*#__PURE__*/React.createElement("span", {
    className: "num " + cls(a.todayPnl)
  }, money(a.todayPnl))), /*#__PURE__*/React.createElement("div", {
    className: "bar"
  }, /*#__PURE__*/React.createElement("span", {
    className: todayUsed / a.dailyKill >= 0.8 ? "err" : todayUsed / a.dailyKill >= 0.5 ? "warn" : "ok",
    style: {
      width: Math.min(100, todayUsed / a.dailyKill * 100) + "%"
    }
  })), /*#__PURE__*/React.createElement("span", {
    className: "cap"
  }, "halt at −$", a.dailyKill, " · ", (todayUsed / a.dailyKill * 100).toFixed(0), "% used")), /*#__PURE__*/React.createElement("div", {
    className: "a"
  }, /*#__PURE__*/React.createElement("div", {
    className: "top"
  }, /*#__PURE__*/React.createElement("span", {
    className: "lbl"
  }, "Open contracts"), /*#__PURE__*/React.createElement("span", {
    className: "num"
  }, a.openContracts.toLocaleString())), /*#__PURE__*/React.createElement("div", {
    className: "bar"
  }, /*#__PURE__*/React.createElement("span", {
    className: "ok",
    style: {
      width: Math.min(100, a.openContracts / a.contractCap * 100) + "%"
    }
  })), /*#__PURE__*/React.createElement("span", {
    className: "cap"
  }, "cap ", a.contractCap.toLocaleString(), " (sum of city caps)"))));
}
function PositionsTable({
  rows
}) {
  return /*#__PURE__*/React.createElement(PanelBare, {
    title: "Current positions",
    meta: `mark = bid/ask mid · ${rows.length} open`
  }, /*#__PURE__*/React.createElement("div", {
    className: "tbl-scroll"
  }, /*#__PURE__*/React.createElement("table", {
    className: "dt"
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", {
    className: "l"
  }, "Ticker"), /*#__PURE__*/React.createElement("th", {
    className: "l"
  }, "Bracket"), /*#__PURE__*/React.createElement("th", null, "Side"), /*#__PURE__*/React.createElement("th", null, "Qty"), /*#__PURE__*/React.createElement("th", null, "Avg"), /*#__PURE__*/React.createElement("th", null, "Mark"), /*#__PURE__*/React.createElement("th", null, "Unreal"), /*#__PURE__*/React.createElement("th", null, "%"))), /*#__PURE__*/React.createElement("tbody", null, rows.length === 0 && /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("td", {
    className: "l muted",
    colSpan: "8",
    style: {
      padding: "20px 12px"
    }
  }, "No open positions — all flat.")), rows.map((r, i) => /*#__PURE__*/React.createElement("tr", {
    key: i
  }, /*#__PURE__*/React.createElement("td", {
    className: "l hi"
  }, r.ticker), /*#__PURE__*/React.createElement("td", {
    className: "l"
  }, r.bracket), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
    className: "side " + (r.side === "YES" ? "yes" : "no")
  }, r.side)), /*#__PURE__*/React.createElement("td", null, r.qty), /*#__PURE__*/React.createElement("td", null, r.avg, "¢"), /*#__PURE__*/React.createElement("td", {
    className: "hi"
  }, r.mark, "¢"), /*#__PURE__*/React.createElement("td", {
    className: cls(r.unreal)
  }, money(r.unreal)), /*#__PURE__*/React.createElement("td", {
    className: cls(r.unreal)
  }, pct(r.unrealPct))))))));
}
function EdgeCell({
  edge
}) {
  const positive = edge >= 0;
  const w = Math.min(100, Math.abs(edge) / 0.4 * 100);
  return /*#__PURE__*/React.createElement("span", {
    className: "edge-cell"
  }, /*#__PURE__*/React.createElement("span", {
    className: positive ? "pos" : "neg"
  }, (edge >= 0 ? "+" : "\u2212") + (Math.abs(edge) * 100).toFixed(0) + "%"), /*#__PURE__*/React.createElement("span", {
    className: "edge-bar"
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: w / 2 + "%",
      [positive ? "left" : "right"]: "50%",
      background: positive ? "var(--pos)" : "var(--neg)"
    }
  })));
}
function SignalsTable({
  rows
}) {
  return /*#__PURE__*/React.createElement(PanelBare, {
    title: "Today's signals → fills",
    meta: "every logged signal · placed? · fill status"
  }, /*#__PURE__*/React.createElement("div", {
    className: "tbl-scroll"
  }, /*#__PURE__*/React.createElement("table", {
    className: "dt"
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", {
    className: "l"
  }, "Ticker"), /*#__PURE__*/React.createElement("th", {
    className: "l"
  }, "Bracket"), /*#__PURE__*/React.createElement("th", null, "Model P"), /*#__PURE__*/React.createElement("th", null, "Market P"), /*#__PURE__*/React.createElement("th", null, "Edge"), /*#__PURE__*/React.createElement("th", null, "Signal"), /*#__PURE__*/React.createElement("th", null, "Order"), /*#__PURE__*/React.createElement("th", null, "Fill"), /*#__PURE__*/React.createElement("th", null, "P&L"))), /*#__PURE__*/React.createElement("tbody", null, rows.map((r, i) => /*#__PURE__*/React.createElement("tr", {
    key: i
  }, /*#__PURE__*/React.createElement("td", {
    className: "l hi"
  }, r.ticker.replace("KXHIGH", "").replace("-26JUN08", "")), /*#__PURE__*/React.createElement("td", {
    className: "l"
  }, r.bracket), /*#__PURE__*/React.createElement("td", null, (r.modelP * 100).toFixed(0), "%"), /*#__PURE__*/React.createElement("td", null, (r.mktP * 100).toFixed(0), "%"), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement(EdgeCell, {
    edge: r.edge
  })), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
    className: "side " + (r.side === "YES" ? "yes" : "no")
  }, "BUY ", r.side)), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
    className: "pill-status " + (r.placed === "placed" ? "placed" : "skipped")
  }, r.placed)), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
    className: "pill-status " + r.fill
  }, r.fill)), /*#__PURE__*/React.createElement("td", {
    className: r.pnl === null ? "muted" : cls(r.pnl)
  }, r.pnl === null ? "—" : money(r.pnl))))))));
}
function OrdersTable({
  rows
}) {
  return /*#__PURE__*/React.createElement(PanelBare, {
    title: "Today's live orders",
    meta: "live_trades view"
  }, /*#__PURE__*/React.createElement("div", {
    className: "tbl-scroll",
    style: {
      maxHeight: 240
    }
  }, /*#__PURE__*/React.createElement("table", {
    className: "dt"
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", {
    className: "l"
  }, "Time"), /*#__PURE__*/React.createElement("th", {
    className: "l"
  }, "Ticker"), /*#__PURE__*/React.createElement("th", null, "Side"), /*#__PURE__*/React.createElement("th", null, "Qty"), /*#__PURE__*/React.createElement("th", null, "Limit"), /*#__PURE__*/React.createElement("th", null, "Fill"), /*#__PURE__*/React.createElement("th", null, "Status"))), /*#__PURE__*/React.createElement("tbody", null, rows.length === 0 && /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("td", {
    className: "l muted",
    colSpan: "7",
    style: {
      padding: "18px 12px"
    }
  }, "No orders placed today.")), rows.map((r, i) => /*#__PURE__*/React.createElement("tr", {
    key: i
  }, /*#__PURE__*/React.createElement("td", {
    className: "l"
  }, r.time), /*#__PURE__*/React.createElement("td", {
    className: "l hi"
  }, r.ticker), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
    className: "side " + (r.side === "YES" ? "yes" : "no")
  }, r.side)), /*#__PURE__*/React.createElement("td", null, r.qty), /*#__PURE__*/React.createElement("td", null, r.limit, "¢"), /*#__PURE__*/React.createElement("td", {
    className: "hi"
  }, r.fillPx === null ? "—" : r.fillPx + "¢"), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
    className: "pill-status " + r.status
  }, r.status))))))));
}
function OpenOrders({
  rows
}) {
  return /*#__PURE__*/React.createElement(PanelBare, {
    title: "Open orders on Kalshi",
    meta: `${rows.length} resting`
  }, /*#__PURE__*/React.createElement("div", {
    className: "tbl-scroll",
    style: {
      maxHeight: 200
    }
  }, /*#__PURE__*/React.createElement("table", {
    className: "dt"
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", {
    className: "l"
  }, "Ticker"), /*#__PURE__*/React.createElement("th", null, "Side"), /*#__PURE__*/React.createElement("th", null, "Qty"), /*#__PURE__*/React.createElement("th", null, "Limit"), /*#__PURE__*/React.createElement("th", null, "Age"))), /*#__PURE__*/React.createElement("tbody", null, rows.length === 0 && /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("td", {
    className: "l muted",
    colSpan: "5",
    style: {
      padding: "16px 12px"
    }
  }, "No resting orders.")), rows.map((r, i) => /*#__PURE__*/React.createElement("tr", {
    key: i
  }, /*#__PURE__*/React.createElement("td", {
    className: "l hi"
  }, r.ticker), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
    className: "side " + (r.side === "YES" ? "yes" : "no")
  }, r.side)), /*#__PURE__*/React.createElement("td", null, r.qty), /*#__PURE__*/React.createElement("td", null, r.limit, "¢"), /*#__PURE__*/React.createElement("td", {
    className: "muted"
  }, r.age)))))));
}
function RecentFills({
  rows
}) {
  return /*#__PURE__*/React.createElement(PanelBare, {
    title: "Recent fills (7 days)",
    meta: `${rows.length} fills`
  }, /*#__PURE__*/React.createElement("div", {
    className: "tbl-scroll",
    style: {
      maxHeight: 200
    }
  }, /*#__PURE__*/React.createElement("table", {
    className: "dt"
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", {
    className: "l"
  }, "Date"), /*#__PURE__*/React.createElement("th", {
    className: "l"
  }, "Ticker"), /*#__PURE__*/React.createElement("th", null, "Side"), /*#__PURE__*/React.createElement("th", null, "Qty"), /*#__PURE__*/React.createElement("th", null, "Px"), /*#__PURE__*/React.createElement("th", null, "Settled P&L"))), /*#__PURE__*/React.createElement("tbody", null, rows.map((r, i) => /*#__PURE__*/React.createElement("tr", {
    key: i
  }, /*#__PURE__*/React.createElement("td", {
    className: "l"
  }, r.date), /*#__PURE__*/React.createElement("td", {
    className: "l hi"
  }, r.ticker), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
    className: "side " + (r.side === "YES" ? "yes" : "no")
  }, r.side)), /*#__PURE__*/React.createElement("td", null, r.qty), /*#__PURE__*/React.createElement("td", null, r.px, "¢"), /*#__PURE__*/React.createElement("td", {
    className: r.pnl === null ? "muted" : cls(r.pnl)
  }, r.pnl === null ? "open" : money(r.pnl))))))));
}
function CronAlerts({
  d
}) {
  const dot = s => s === "ok" ? "ok" : s === "error" ? "err" : "warn";
  return /*#__PURE__*/React.createElement("div", {
    className: "panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "panel-h"
  }, /*#__PURE__*/React.createElement("h3", null, "Cron health & alerts"), /*#__PURE__*/React.createElement("span", {
    className: "meta"
  }, "4 daily jobs")), /*#__PURE__*/React.createElement("div", {
    className: "panel-b",
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 18
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: 9
    }
  }, d.crons.map((c, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: "flex",
      alignItems: "center",
      gap: 10
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "ico " + dot(c.status),
    style: {
      width: 8,
      height: 8,
      borderRadius: "50%",
      background: c.status === "ok" ? "var(--pos)" : c.status === "error" ? "var(--neg)" : "var(--warn)",
      flex: "none"
    }
  }), /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 12,
      color: "var(--text-hi)",
      minWidth: 104
    }
  }, c.name), /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 11,
      color: "var(--text-lo)"
    }
  }, c.last), /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 11,
      color: "var(--text-faint)",
      marginLeft: "auto"
    }
  }, c.desc)))), /*#__PURE__*/React.createElement("div", {
    style: {
      borderLeft: "1px solid var(--border)",
      paddingLeft: 18,
      display: "flex",
      flexDirection: "column",
      gap: 8
    }
  }, d.alerts.map((a, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    className: "logline " + a.lvl,
    style: {
      display: "flex",
      gap: 9
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "tt"
  }, a.ts), /*#__PURE__*/React.createElement("span", {
    style: {
      color: a.lvl === "err" ? "var(--neg)" : a.lvl === "warn" ? "var(--warn)" : "var(--text-mid)"
    }
  }, a.msg))))));
}
function ParamsExpander({
  d
}) {
  return /*#__PURE__*/React.createElement("details", {
    className: "params"
  }, /*#__PURE__*/React.createElement("summary", null, "Strategy parameters in effect (live from live_trade.py)"), /*#__PURE__*/React.createElement("div", {
    className: "pbody"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--text-hi)"
    }
  }, "Filter:"), " |edge| ≥ per-city threshold, no entry-price floor · ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--text-hi)"
    }
  }, "Execution:"), " ", /*#__PURE__*/React.createElement("code", null, "post_inside_spread")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--text-hi)"
    }
  }, "Aggregate kills:"), " daily loss −$150, cumulative drawdown −$500, 4wk avg spread > 5¢"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 6
    }
  }, d.cities.map((c, i) => /*#__PURE__*/React.createElement("div", {
    key: i
  }, "— ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--text-hi)"
    }
  }, c.name), " (", c.code, ") — edge ≥ ", c.edgeThresh, ", size ", c.stake, ", daily $", c.risk.todayKill, ", cumulative $", c.risk.cumKill, ", max ", c.risk.cumKill === 500 ? "5,000" : "5,000", " contracts"))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 8
    }
  }, "Halt files: ", /*#__PURE__*/React.createElement("code", null, "touch halt/KORD"), " ", /*#__PURE__*/React.createElement("code", null, "touch halt/KMIA"), " ", /*#__PURE__*/React.createElement("code", null, "touch halt/ALL"))));
}
function LiveTab({
  d,
  countdown
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "wrap"
  }, /*#__PURE__*/React.createElement(KillBanner, {
    d: d
  }), /*#__PURE__*/React.createElement(Hero, {
    d: d
  }), /*#__PURE__*/React.createElement(StatusStrip, {
    d: d,
    countdown: countdown
  }), /*#__PURE__*/React.createElement("div", {
    className: "section-label"
  }, "Per-city · realized + unrealized + risk"), /*#__PURE__*/React.createElement("div", {
    className: "grid g-3"
  }, d.cities.map((c, i) => /*#__PURE__*/React.createElement(CityCard, {
    key: i,
    c: c
  })), /*#__PURE__*/React.createElement(AggRisk, {
    d: d
  })), /*#__PURE__*/React.createElement("div", {
    className: "grid",
    style: {
      gridTemplateColumns: "1.45fr 1fr"
    }
  }, /*#__PURE__*/React.createElement(PanelBare, {
    title: "Cumulative P&L",
    meta: "last 7 days · since first live trade"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "10px 12px 4px"
    }
  }, /*#__PURE__*/React.createElement(PnlChart, {
    data: d.series
  })), /*#__PURE__*/React.createElement("div", {
    className: "panel-b",
    style: {
      paddingTop: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "chart-legend"
  }, /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("span", {
    className: "sw",
    style: {
      background: d.cumulative.total >= 0 ? "var(--pos)" : "var(--neg)"
    }
  }), "cumulative realized P&L · right axis")))), /*#__PURE__*/React.createElement(PositionsTable, {
    rows: d.positions
  })), /*#__PURE__*/React.createElement(SignalsTable, {
    rows: d.signals
  }), /*#__PURE__*/React.createElement("div", {
    className: "grid g-2"
  }, /*#__PURE__*/React.createElement(OrdersTable, {
    rows: d.orders
  }), /*#__PURE__*/React.createElement("div", {
    className: "grid",
    style: {
      gridTemplateRows: "auto auto",
      gap: 14
    }
  }, /*#__PURE__*/React.createElement(OpenOrders, {
    rows: d.openOrdersTbl
  }), /*#__PURE__*/React.createElement(RecentFills, {
    rows: d.fills
  }))), /*#__PURE__*/React.createElement(CronAlerts, {
    d: d
  }), /*#__PURE__*/React.createElement(ParamsExpander, {
    d: d
  }));
}
Object.assign(window, {
  LiveTab
});

// ===== App shell =====

const {
  useState: __useState,
  useEffect: __useEffect
} = React;
function App() {
  const d = window.DASH_DATA;
  const [tick, setTick] = __useState(0);
  __useEffect(() => {
    const t = setInterval(() => setTick(x => x + 1), 1000);
    return () => clearInterval(t);
  }, []);
  function fmt() {
    if (d.nextCron.inMin === null || d.nextCron.inMin === undefined) return "—";
    const totalSec = Math.max(0, d.nextCron.inMin * 60 - tick);
    const m = Math.floor(totalSec / 60),
      s = totalSec % 60;
    return m + "m " + String(s).padStart(2, "0") + "s";
  }
  return /*#__PURE__*/React.createElement(window.LiveTab, {
    d: d,
    countdown: fmt()
  });
}
ReactDOM.createRoot(document.getElementById("root")).render(/*#__PURE__*/React.createElement(App, null));