/* Backtest / Forecast View mock data. Two cities, internally consistent
   with the live tab. Forecast = today's combined ensemble vs Kalshi mids.
   Sim variants are precomputed per sizing mode so the toggle is live. */

window.BTDATA = (function () {
  // deterministic pseudo-ensemble around a mean/spread (member daily highs °F)
  function ensemble(mean, spread, n, seed) {
    let s = seed;
    const rnd = () => { s = (s * 9301 + 49297) % 233280; return s / 233280; };
    const out = [];
    for (let i = 0; i < n; i++) {
      // Box-Muller for gaussian-ish member spread
      const u1 = Math.max(1e-6, rnd()), u2 = rnd();
      const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
      out.push(Math.round((mean + z * spread) * 10) / 10);
    }
    return out;
  }

  const CHI = {
    code: "KORD", city: "Chicago", date: "2025-06-08",
    members: ensemble(88.4, 2.1, 62, 7),
    nMembers: 62, ensMean: 88.4, ensSpread: 2.1, emosMu: 88.9, emosSigma: 2.6,
    observed: 89,
    brackets: [
      { label: "≤85°F",  lo: -99, hi: 85,  modelP: 0.04, mktP: 0.07, resolved: "NO"  },
      { label: "86–87°F", lo: 86,  hi: 87,  modelP: 0.16, mktP: 0.20, resolved: "NO"  },
      { label: "88–89°F", lo: 88,  hi: 89,  modelP: 0.42, mktP: 0.27, resolved: "YES" },
      { label: "90–91°F", lo: 90,  hi: 91,  modelP: 0.28, mktP: 0.26, resolved: "NO"  },
      { label: "92–93°F", lo: 92,  hi: 93,  modelP: 0.08, mktP: 0.13, resolved: "NO"  },
      { label: "≥94°F",  lo: 94,  hi: 99,  modelP: 0.02, mktP: 0.07, resolved: "NO"  },
    ],
    sim: {
      unit:    { final: 1180, ret: 18.0, sharpe: 1.42, maxDD: -8.2,  win: 0.58, n: 64, filled: 58, avg: 2.81, pending: 3, total: 71,
                 curve: [1000,1040,1010,1090,1060,1130,1095,1160,1140,1175,1180] },
      amount:  { final: 1310, ret: 31.0, sharpe: 1.55, maxDD: -9.1,  win: 0.58, n: 64, filled: 58, avg: 4.82, pending: 3, total: 71,
                 curve: [1000,1070,1030,1150,1100,1210,1170,1255,1230,1290,1310] },
      kelly:   { final: 1890, ret: 89.0, sharpe: 1.21, maxDD: -22.4, win: 0.58, n: 64, filled: 58, avg: 12.4, pending: 3, total: 71,
                 curve: [1000,1180,1040,1360,1230,1520,1410,1690,1560,1820,1890] },
      scaling: { final: 2640, ret: 164.0, sharpe: 0.98, maxDD: -34.1, win: 0.58, n: 64, filled: 58, avg: 19.1, pending: 3, total: 71,
                 curve: [1000,1240,1010,1520,1300,1880,1640,2210,1980,2520,2640] },
    },
    trades: [
      { date: "06-08", bracket: "88–89°F", side: "YES", modelP: 0.42, mktP: 0.27, edge: 0.15, entry: 41, qty: 200, fill: "filled", won: true,  pnl: 118.00 },
      { date: "06-07", bracket: "86–87°F", side: "YES", modelP: 0.51, mktP: 0.33, edge: 0.18, entry: 38, qty: 200, fill: "filled", won: true,  pnl: 124.00 },
      { date: "06-06", bracket: "≥90°F",  side: "NO",  modelP: 0.18, mktP: 0.41, edge: -0.23,entry: 66, qty: 200, fill: "filled", won: false, pnl: -132.00 },
      { date: "06-05", bracket: "82–83°F", side: "YES", modelP: 0.47, mktP: 0.31, edge: 0.16, entry: 44, qty: 150, fill: "filled", won: true,  pnl: 84.00 },
      { date: "06-04", bracket: "84–85°F", side: "YES", modelP: 0.39, mktP: 0.29, edge: 0.10, entry: 52, qty: 150, fill: "unfilled",won: null,  pnl: 0.00 },
      { date: "06-03", bracket: "88–89°F", side: "YES", modelP: 0.44, mktP: 0.26, edge: 0.18, entry: 35, qty: 200, fill: "filled", won: true,  pnl: 130.00 },
    ],
    strat: [
      { name: "GEFS only",      final: 1040, ret: 4.0,  sharpe: 0.42, maxDD: -14.2, win: 0.52, brier: 0.214, n: 64 },
      { name: "Combined",       final: 1310, ret: 31.0, sharpe: 1.55, maxDD: -9.1,  win: 0.58, brier: 0.181, n: 64 },
      { name: "Combined+HRRR",  final: 1520, ret: 52.0, sharpe: 1.78, maxDD: -7.4,  win: 0.61, brier: 0.169, n: 64, chosen: true },
    ],
  };

  const MIA = {
    code: "KMIA", city: "Miami", date: "2025-06-08",
    members: ensemble(91.6, 1.4, 62, 21),
    nMembers: 62, ensMean: 91.6, ensSpread: 1.4, emosMu: 91.9, emosSigma: 1.8,
    observed: 92,
    brackets: [
      { label: "≤89°F",  lo: -99, hi: 89,  modelP: 0.03, mktP: 0.06, resolved: "NO"  },
      { label: "90–91°F", lo: 90,  hi: 91,  modelP: 0.31, mktP: 0.28, resolved: "NO"  },
      { label: "92–93°F", lo: 92,  hi: 93,  modelP: 0.46, mktP: 0.39, resolved: "YES" },
      { label: "94–95°F", lo: 94,  hi: 95,  modelP: 0.16, mktP: 0.19, resolved: "NO"  },
      { label: "≥96°F",  lo: 96,  hi: 99,  modelP: 0.04, mktP: 0.08, resolved: "NO"  },
    ],
    sim: {
      unit:    { final: 1090, ret: 9.0,  sharpe: 0.61, maxDD: -12.8, win: 0.51, n: 58, filled: 49, avg: 1.84, pending: 4, total: 66,
                 curve: [1000,1030,1005,1060,1020,1075,1045,1080,1060,1085,1090] },
      amount:  { final: 1140, ret: 14.0, sharpe: 0.68, maxDD: -14.0, win: 0.51, n: 58, filled: 49, avg: 2.86, pending: 4, total: 66,
                 curve: [1000,1050,1010,1090,1040,1110,1070,1120,1090,1130,1140] },
      kelly:   { final: 1260, ret: 26.0, sharpe: 0.49, maxDD: -28.6, win: 0.51, n: 58, filled: 49, avg: 5.31, pending: 4, total: 66,
                 curve: [1000,1110,1000,1210,1080,1280,1150,1300,1190,1240,1260] },
      scaling: { final: 1410, ret: 41.0, sharpe: 0.34, maxDD: -41.2, win: 0.51, n: 58, filled: 49, avg: 8.41, pending: 4, total: 66,
                 curve: [1000,1180,980,1360,1120,1480,1240,1520,1300,1380,1410] },
    },
    trades: [
      { date: "06-08", bracket: "92–93°F", side: "YES", modelP: 0.46, mktP: 0.39, edge: 0.07, entry: 47, qty: 300, fill: "filled", won: true,  pnl: 159.00 },
      { date: "06-07", bracket: "90–91°F", side: "YES", modelP: 0.41, mktP: 0.30, edge: 0.11, entry: 44, qty: 300, fill: "filled", won: false, pnl: -132.00 },
      { date: "06-06", bracket: "≥94°F",  side: "NO",  modelP: 0.21, mktP: 0.36, edge: -0.15,entry: 61, qty: 300, fill: "filled", won: true,  pnl: 117.00 },
      { date: "06-05", bracket: "92–93°F", side: "YES", modelP: 0.49, mktP: 0.41, edge: 0.08, entry: 46, qty: 300, fill: "unfilled",won: null,  pnl: 0.00 },
      { date: "06-04", bracket: "91–92°F", side: "YES", modelP: 0.44, mktP: 0.35, edge: 0.09, entry: 42, qty: 300, fill: "filled", won: true,  pnl: 174.00 },
    ],
    strat: [
      { name: "GEFS only",      final: 980,  ret: -2.0, sharpe: 0.08, maxDD: -19.4, win: 0.47, brier: 0.236, n: 58 },
      { name: "Combined",       final: 1140, ret: 14.0, sharpe: 0.68, maxDD: -14.0, win: 0.51, brier: 0.198, n: 58, chosen: true },
      { name: "Combined+HRRR",  final: 1110, ret: 11.0, sharpe: 0.59, maxDD: -15.1, win: 0.50, brier: 0.205, n: 58 },
    ],
  };

  return { KORD: CHI, KMIA: MIA, cities: ["KORD", "KMIA"] };
})();
