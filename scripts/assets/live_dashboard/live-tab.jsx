/* Live Trading tab */
const { useState: useStateL } = React;

function Hero({ d }) {
  const t = d.today, c = d.cumulative;
  return (
    <div className="hero">
      <div>
        <div className="k">Today's P&amp;L</div>
        <div className={"v " + cls(t.total)}>{money(t.total)}</div>
        <div className="sub">
          <span>realized <b className={cls(t.realized)}>{money(t.realized)}</b></span>
          <span>unrealized <b className={cls(t.unrealized)}>{money(t.unrealized)}</b></span>
          <span><b>{t.trades}</b> trades · <b>{t.open}</b> open</span>
        </div>
      </div>
      <div>
        <div className="k">Cumulative P&amp;L <span className="tag-pill">since first live trade</span></div>
        <div className={"v " + cls(c.total)}>{money(c.total)}</div>
        <div className="sub">
          <span>return <b className={cls(c.returnPct)}>{pct(c.returnPct)}</b></span>
          <span>win rate <b>{(c.winRate * 100).toFixed(0)}%</b></span>
          <span><b>{c.nSettled}</b> settled</span>
        </div>
        <div className="spark"><Spark data={d.series} /></div>
      </div>
      <div>
        <div className="k">Account value <span className="tag-pill">cash + portfolio</span></div>
        <div className="v sm" style={{ color: "var(--text-hi)" }}>{moneyPlain(d.balance)}</div>
        <div className="sub">
          <span>cash <b>{moneyPlain(d.cashBalance != null ? d.cashBalance : d.balance)}</b></span>
          <span>portfolio <b>{moneyPlain(d.portfolioValue || 0)}</b></span>
          <span><b>{d.openOrders.contracts.toLocaleString()}</b> contracts · <b>{d.openOrders.count}</b> orders</span>
        </div>
      </div>
    </div>
  );
}

function StatusStrip({ d, countdown }) {
  const killOk = d.killArmed;
  return (
    <div className="status-strip">
      <div className="chip">
        <span className={"ico " + (killOk ? "ok" : "err")} />
        <span className="txt">
          <span className="l">Kill switch</span>
          <span className="d" style={{ color: killOk ? "var(--pos)" : "var(--neg)" }}>{killOk ? "ARMED" : "TRIGGERED"}</span>
        </span>
      </div>
      <div className="chip">
        <span className={"ico " + (d.nextCron.inMin === null ? "err" : "ok")} />
        <span className="txt">
          <span className="l">Next cron · {d.nextCron.label}</span>
          <span className="d">{d.nextCron.at} {d.nextCron.inMin !== null && <small>· in {countdown}</small>}</span>
        </span>
      </div>
      <div className="chip">
        <span className={"ico " + (d.openOrders.count > 0 ? "ok" : "")} />
        <span className="txt">
          <span className="l">Open orders</span>
          <span className="d">{d.openOrders.count} resting <small>· {d.openOrders.contracts.toLocaleString()} contracts</small></span>
        </span>
      </div>
      <div className="chip">
        <span className={"ico " + (d.hrrr.status === "ok" ? "ok" : "warn")} />
        <span className="txt">
          <span className="l">HRRR data</span>
          <span className="d" style={{ color: d.hrrr.status === "ok" ? "var(--text-hi)" : "var(--warn)" }}>
            {d.hrrr.status === "ok" ? "fresh" : "stale"} <small>· {d.hrrr.age} ago</small>
          </span>
        </span>
      </div>
      <div className="chip">
        <span className="ico ok" />
        <span className="txt">
          <span className="l">Positions</span>
          <span className="d">{d.positions.length} open <small>· {d.cities.filter(c => c.status === "active").length}/2 cities live</small></span>
        </span>
      </div>
    </div>
  );
}

function KillBanner({ d }) {
  if (d.killArmed) return null;
  return (
    <div className="alert">
      <span className="bang">⛔</span>
      <div className="body">
        <div className="t">Kill switch triggered — all trading halted</div>
        <div className="d">{d.killReason}</div>
      </div>
      <span className="ts">15:12:04 UTC</span>
    </div>
  );
}

function CityCard({ c }) {
  return (
    <div className="panel city">
      <div className="ch">
        <span className="nm">{c.name}</span>
        <span className="code">{c.code}</span>
        <span className={"badge " + (c.status === "active" ? "active" : "halted")}>{c.status}</span>
        <span className="model">{c.model}</span>
      </div>
      <div className="cbody">
        <div className="m"><div className="ml">Realized</div><div className={"mv " + cls(c.realized)}>{money(c.realized)}</div><div className="ms">settled</div></div>
        <div className="m"><div className="ml">Unrealized</div><div className={"mv " + cls(c.unrealized)}>{money(c.unrealized)}</div><div className="ms">open mark</div></div>
        <div className="m"><div className="ml">Today</div><div className={"mv " + cls(c.today)}>{money(c.today)}</div><div className="ms">{c.orders} orders</div></div>
      </div>
      <div className="cfoot">
        {c.haltNote
          ? <div className="halt-note">{c.haltNote}</div>
          : <div className="activity"><span>budget <b>${c.budget}</b></span><span><b>{c.contracts.toLocaleString()}</b> contracts</span><span>edge ≥ <b>{c.edgeThresh}</b></span><span>size <b>{c.stake}</b></span></div>}
        <RiskBar name="Cumulative" used={c.risk.cumUsed} limit={c.risk.cumKill} fmt={v => "$" + v.toFixed(0)} />
        <RiskBar name="Today" used={c.risk.todayUsed} limit={c.risk.todayKill} fmt={v => "$" + v.toFixed(0)} />
      </div>
    </div>
  );
}

function AggRisk({ d }) {
  const a = d.agg;
  const cumUsed = a.cumPnl < 0 ? Math.abs(a.cumPnl) : 0;
  const todayUsed = a.todayPnl < 0 ? Math.abs(a.todayPnl) : 0;
  return (
    <div className="panel" style={{ display: "flex", flexDirection: "column" }}>
      <div className="panel-h"><h3>Aggregate risk envelope</h3><span className="meta">cross-city</span></div>
      <div className="panel-b aggm" style={{ flex: 1 }}>
        <div className="a">
          <div className="top"><span className="lbl">Cumulative drawdown</span><span className={"num " + cls(a.cumPnl)}>{money(a.cumPnl)}</span></div>
          <div className="bar"><span className={cumUsed / a.cumKill >= 0.8 ? "err" : cumUsed / a.cumKill >= 0.5 ? "warn" : "ok"} style={{ width: Math.min(100, cumUsed / a.cumKill * 100) + "%" }} /></div>
          <span className="cap">kill at −${a.cumKill} · {(cumUsed / a.cumKill * 100).toFixed(0)}% used</span>
        </div>
        <div className="a">
          <div className="top"><span className="lbl">Daily loss</span><span className={"num " + cls(a.todayPnl)}>{money(a.todayPnl)}</span></div>
          <div className="bar"><span className={todayUsed / a.dailyKill >= 0.8 ? "err" : todayUsed / a.dailyKill >= 0.5 ? "warn" : "ok"} style={{ width: Math.min(100, todayUsed / a.dailyKill * 100) + "%" }} /></div>
          <span className="cap">halt at −${a.dailyKill} · {(todayUsed / a.dailyKill * 100).toFixed(0)}% used</span>
        </div>
        <div className="a">
          <div className="top"><span className="lbl">Open contracts</span><span className="num">{a.openContracts.toLocaleString()}</span></div>
          <div className="bar"><span className="ok" style={{ width: Math.min(100, a.openContracts / a.contractCap * 100) + "%" }} /></div>
          <span className="cap">cap {a.contractCap.toLocaleString()} (sum of city caps)</span>
        </div>
      </div>
    </div>
  );
}

function PositionsTable({ rows }) {
  return (
    <PanelBare title="Current positions" meta={`mark = bid/ask mid · ${rows.length} open`}>
      <div className="tbl-scroll">
        <table className="dt">
          <thead><tr>
            <th className="l">Ticker</th><th className="l">Bracket</th><th>Side</th><th>Qty</th><th>Avg</th><th>Mark</th><th>Unreal</th><th>%</th>
          </tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td className="l muted" colSpan="8" style={{ padding: "20px 12px" }}>No open positions — all flat.</td></tr>}
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="l hi">{r.ticker}</td>
                <td className="l">{r.bracket}</td>
                <td><span className={"side " + (r.side === "YES" ? "yes" : "no")}>{r.side}</span></td>
                <td>{r.qty}</td>
                <td>{r.avg}¢</td>
                <td className="hi">{r.mark}¢</td>
                <td className={cls(r.unreal)}>{money(r.unreal)}</td>
                <td className={cls(r.unreal)}>{pct(r.unrealPct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PanelBare>
  );
}

function EdgeCell({ edge }) {
  const positive = edge >= 0;
  const w = Math.min(100, Math.abs(edge) / 0.4 * 100);
  return (
    <span className="edge-cell">
      <span className={positive ? "pos" : "neg"}>{(edge >= 0 ? "+" : "\u2212") + (Math.abs(edge) * 100).toFixed(0) + "%"}</span>
      <span className="edge-bar"><span style={{ width: w / 2 + "%", [positive ? "left" : "right"]: "50%", background: positive ? "var(--pos)" : "var(--neg)" }} /></span>
    </span>
  );
}

function SignalsTable({ rows }) {
  return (
    <PanelBare title="Today's signals → fills" meta="every logged signal · placed? · fill status">
      <div className="tbl-scroll">
        <table className="dt">
          <thead><tr>
            <th className="l">Ticker</th><th className="l">Bracket</th><th>Model P</th><th>Market P</th><th>Edge</th><th>Signal</th><th>Order</th><th>Fill</th><th>P&amp;L</th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="l hi">{r.ticker.replace("KXHIGH", "").replace("-26JUN08", "")}</td>
                <td className="l">{r.bracket}</td>
                <td>{(r.modelP * 100).toFixed(0)}%</td>
                <td>{(r.mktP * 100).toFixed(0)}%</td>
                <td><EdgeCell edge={r.edge} /></td>
                <td><span className={"side " + (r.side === "YES" ? "yes" : "no")}>BUY {r.side}</span></td>
                <td><span className={"pill-status " + (r.placed === "placed" ? "placed" : "skipped")}>{r.placed}</span></td>
                <td><span className={"pill-status " + r.fill}>{r.fill}</span></td>
                <td className={r.pnl === null ? "muted" : cls(r.pnl)}>{r.pnl === null ? "—" : money(r.pnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PanelBare>
  );
}

function OrdersTable({ rows }) {
  return (
    <PanelBare title="Today's live orders" meta="live_trades view">
      <div className="tbl-scroll" style={{ maxHeight: 240 }}>
        <table className="dt">
          <thead><tr><th className="l">Time</th><th className="l">Ticker</th><th>Side</th><th>Qty</th><th>Limit</th><th>Fill</th><th>Status</th></tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td className="l muted" colSpan="7" style={{ padding: "18px 12px" }}>No orders placed today.</td></tr>}
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="l">{r.time}</td>
                <td className="l hi">{r.ticker}</td>
                <td><span className={"side " + (r.side === "YES" ? "yes" : "no")}>{r.side}</span></td>
                <td>{r.qty}</td>
                <td>{r.limit}¢</td>
                <td className="hi">{r.fillPx === null ? "—" : r.fillPx + "¢"}</td>
                <td><span className={"pill-status " + r.status}>{r.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PanelBare>
  );
}

function OpenOrders({ rows }) {
  return (
    <PanelBare title="Open orders on Kalshi" meta={`${rows.length} resting`}>
      <div className="tbl-scroll" style={{ maxHeight: 200 }}>
        <table className="dt">
          <thead><tr><th className="l">Ticker</th><th>Side</th><th>Qty</th><th>Limit</th><th>Age</th></tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td className="l muted" colSpan="5" style={{ padding: "16px 12px" }}>No resting orders.</td></tr>}
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="l hi">{r.ticker}</td>
                <td><span className={"side " + (r.side === "YES" ? "yes" : "no")}>{r.side}</span></td>
                <td>{r.qty}</td><td>{r.limit}¢</td><td className="muted">{r.age}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PanelBare>
  );
}

function RecentFills({ rows }) {
  return (
    <PanelBare title="Recent fills (7 days)" meta={`${rows.length} fills`}>
      <div className="tbl-scroll" style={{ maxHeight: 200 }}>
        <table className="dt">
          <thead><tr><th className="l">Date</th><th className="l">Ticker</th><th>Side</th><th>Qty</th><th>Px</th><th>Settled P&amp;L</th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="l">{r.date}</td>
                <td className="l hi">{r.ticker}</td>
                <td><span className={"side " + (r.side === "YES" ? "yes" : "no")}>{r.side}</span></td>
                <td>{r.qty}</td><td>{r.px}¢</td>
                <td className={r.pnl === null ? "muted" : cls(r.pnl)}>{r.pnl === null ? "open" : money(r.pnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PanelBare>
  );
}

function CronAlerts({ d }) {
  const dot = s => s === "ok" ? "ok" : s === "error" ? "err" : "warn";
  return (
    <div className="panel">
      <div className="panel-h"><h3>Cron health &amp; alerts</h3><span className="meta">4 daily jobs</span></div>
      <div className="panel-b" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
          {d.crons.map((c, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span className={"ico " + dot(c.status)} style={{ width: 8, height: 8, borderRadius: "50%", background: c.status === "ok" ? "var(--pos)" : c.status === "error" ? "var(--neg)" : "var(--warn)", flex: "none" }} />
              <span className="mono" style={{ fontSize: 12, color: "var(--text-hi)", minWidth: 104 }}>{c.name}</span>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-lo)" }}>{c.last}</span>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-faint)", marginLeft: "auto" }}>{c.desc}</span>
            </div>
          ))}
        </div>
        <div style={{ borderLeft: "1px solid var(--border)", paddingLeft: 18, display: "flex", flexDirection: "column", gap: 8 }}>
          {d.alerts.map((a, i) => (
            <div key={i} className={"logline " + a.lvl} style={{ display: "flex", gap: 9 }}>
              <span className="tt">{a.ts}</span>
              <span style={{ color: a.lvl === "err" ? "var(--neg)" : a.lvl === "warn" ? "var(--warn)" : "var(--text-mid)" }}>{a.msg}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ParamsExpander({ d }) {
  return (
    <details className="params">
      <summary>Strategy parameters in effect (live from live_trade.py)</summary>
      <div className="pbody">
        <div><b style={{ color: "var(--text-hi)" }}>Filter:</b> |edge| ≥ per-city threshold, no entry-price floor · <b style={{ color: "var(--text-hi)" }}>Execution:</b> <code>post_inside_spread</code></div>
        <div><b style={{ color: "var(--text-hi)" }}>Aggregate kills:</b> daily loss −$150, cumulative drawdown −$500, 4wk avg spread &gt; 5¢</div>
        <div style={{ marginTop: 6 }}>
          {d.cities.map((c, i) => (
            <div key={i}>— <b style={{ color: "var(--text-hi)" }}>{c.name}</b> ({c.code}) — edge ≥ {c.edgeThresh}, size {c.stake}, daily ${c.risk.todayKill}, cumulative ${c.risk.cumKill}, max {c.risk.cumKill === 500 ? "5,000" : "5,000"} contracts</div>
          ))}
        </div>
        <div style={{ marginTop: 8 }}>Halt files: <code>touch halt/KORD</code> <code>touch halt/KMIA</code> <code>touch halt/ALL</code></div>
      </div>
    </details>
  );
}

function LiveTab({ d, countdown }) {
  return (
    <div className="wrap">
      <KillBanner d={d} />
      <Hero d={d} />
      <StatusStrip d={d} countdown={countdown} />

      <div className="section-label">Per-city · realized + unrealized + risk</div>
      <div className="grid g-3">
        {d.cities.map((c, i) => <CityCard key={i} c={c} />)}
        <AggRisk d={d} />
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1.45fr 1fr" }}>
        <PanelBare title="Cumulative P&amp;L" meta="last 7 days · since first live trade">
          <div style={{ padding: "10px 12px 4px" }}><PnlChart data={d.series} /></div>
          <div className="panel-b" style={{ paddingTop: 0 }}>
            <div className="chart-legend"><span><span className="sw" style={{ background: d.cumulative.total >= 0 ? "var(--pos)" : "var(--neg)" }} />cumulative realized P&amp;L · right axis</span></div>
          </div>
        </PanelBare>
        <PositionsTable rows={d.positions} />
      </div>

      <SignalsTable rows={d.signals} />

      <div className="grid g-2">
        <OrdersTable rows={d.orders} />
        <div className="grid" style={{ gridTemplateRows: "auto auto", gap: 14 }}>
          <OpenOrders rows={d.openOrdersTbl} />
          <RecentFills rows={d.fills} />
        </div>
      </div>

      <CronAlerts d={d} />
      <ParamsExpander d={d} />
    </div>
  );
}

Object.assign(window, { LiveTab });
