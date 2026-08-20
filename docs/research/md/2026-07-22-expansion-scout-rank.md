# Breadth-expansion ranked opportunity report — 2026-07-22 18:29Z

Deterministic scorecard (no LLM). Verdicts: GO is always paper-first;
nothing goes live without the walk-forward OOS Sharpe > 2.5 bar or an
explicit operator override. Ceiling estimates are heuristic — run the
walk-book capacity tools before sizing anything.

| # | candidate | verdict | score | est. ceiling | fee/edge | deploy-bar status |
|---|-----------|---------|-------|--------------|----------|-------------------|
| 1 | kalshi-denver | GO (paper-first) [prior: HOLD per 2026-07-07 per-city optimization (not robust at baseline)] | 28/30 | ~700 | taker 2c / maker 1c at 50c; paper mean abs edge 20.9% | backtestable now (2686 paper rows, 391d) — walk-forward OOS Sharpe vs the 2.5 bar can be computed |
| 2 | kalshi-nyc | GO (paper-first) [prior: HOLD per 2026-07-07 per-city optimization] | 28/30 | ~700 | taker 2c / maker 1c at 50c; paper mean abs edge 25.1% | backtestable now (7284 paper rows, 786d) — walk-forward OOS Sharpe vs the 2.5 bar can be computed |
| 3 | forecastex-miami | GO (paper-first) | 25/30 | ~700 | taker 1c / maker 1c at 50c; paper mean abs edge 20.5% | backtestable now (2135 paper rows, 391d) — walk-forward OOS Sharpe vs the 2.5 bar can be computed |
| 4 | forecastex-dallas | GO (paper-first) | 25/30 | ~700 | taker 1c / maker 1c at 50c; paper mean abs edge 22.6% | backtestable now (779 paper rows, 161d) — walk-forward OOS Sharpe vs the 2.5 bar can be computed |
| 5 | kalshi-lows-chicago | GO (paper-first) | 25/30 | ~441 | taker 2c / maker 1c at 50c; paper mean abs edge 24.0% | backtestable now (3655 paper rows, 391d) — walk-forward OOS Sharpe vs the 2.5 bar can be computed |
| 6 | kalshi-kxhightsfo | GO (paper-first) | 24/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 7 | kalshi-kxhightmin | GO (paper-first) | 24/30 | ~644 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 8 | kalshi-kxhightdc | GO (paper-first) | 24/30 | ~621 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 9 | kalshi-kxhighphil | GO (paper-first) | 24/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 10 | kalshi-kxhighthou | GO (paper-first) | 24/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 11 | kalshi-kxhightatl | GO (paper-first) | 24/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 12 | kalshi-kxhightbos | GO (paper-first) | 24/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 13 | kalshi-kxhightokc | GO (paper-first) | 24/30 | ~604 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 14 | kalshi-kxtempdch | GO (paper-first) | 23/30 | ~231 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 15 | kalshi-kxtempnych | GO (paper-first) | 23/30 | ~233 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 16 | kalshi-kxtempchih | GO (paper-first) | 23/30 | ~302 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 17 | kalshi-kxhmonthrange | GO (paper-first) | 23/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 18 | kalshi-kxtempaush | GO (paper-first) | 23/30 | ~288 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 19 | kalshi-kxtemplaxh | GO (paper-first) | 23/30 | ~301 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 20 | forecastex-chicago | GO (paper-first) | 21/30 | unknown | taker 1c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 21 | kalshi-kxlowtphil | GO (paper-first) | 21/30 | ~217 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 22 | kalshi-kxlowtmin | GO (paper-first) | 21/30 | ~213 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 23 | kalshi-kxlowtsfo | GO (paper-first) | 21/30 | ~149 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 24 | kalshi-kxlowtdc | GO (paper-first) | 21/30 | ~215 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 25 | kalshi-kxlowtokc | GO (paper-first) | 21/30 | ~240 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 26 | kalshi-kxlowtbos | GO (paper-first) | 21/30 | ~133 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 27 | kalshi-kxlowtatl | GO (paper-first) | 21/30 | ~181 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 28 | kalshi-kxlowthou | GO (paper-first) | 21/30 | ~202 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 29 | kalshi-kxhightsatx | GO (paper-first) | 21/30 | ~435 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 30 | kalshi-kxlowtsatx | GO (paper-first) | 21/30 | ~162 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 31 | kalshi-highaus | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 32 | kalshi-hmonthrange | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 33 | kalshi-tempmon | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 34 | kalshi-temp | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 35 | kalshi-kxholidaytmin | GO (paper-first) | 20/30 | ~564 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 36 | kalshi-kxtempmiah | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 37 | kalshi-kxdvhigh | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 38 | kalshi-kxhouhigh | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 39 | kalshi-kxrainmiam | GO (paper-first) | 20/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 40 | kalshi-kxraindalm | GO (paper-first) | 20/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 41 | kalshi-kxrainnycm | GO (paper-first) | 20/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 42 | kalshi-highny | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 43 | kalshi-kxtempbosh | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 44 | kalshi-kxtempmon | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 45 | kalshi-kxrainseam | GO (paper-first) | 20/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 46 | kalshi-kxholidaytmax | GO (paper-first) | 20/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 47 | kalshi-kxphilhigh | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 48 | kalshi-kxrainsfom | GO (paper-first) | 20/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 49 | kalshi-kxrainhoum | GO (paper-first) | 20/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 50 | kalshi-kxtxuri | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 51 | kalshi-kxtemp | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 52 | kalshi-kxraindenm | GO (paper-first) | 20/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 53 | kalshi-highchi | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 54 | kalshi-michtemp | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 55 | kalshi-highmia | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 56 | kalshi-kxdenhigh | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 57 | kalshi-kxmichtemp | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 58 | kalshi-highus | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 59 | kalshi-kxcitiesweather | GO (paper-first) | 20/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 60 | kalshi-kxhighou | WATCH | 18/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 61 | kalshi-kxhighhou | WATCH | 18/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 62 | kalshi-kxlowden | WATCH | 18/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 63 | kalshi-kxhightempden | WATCH | 18/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 64 | kalshi-kxhighus | WATCH | 18/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 65 | kalshi-kxlowaus | WATCH | 18/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 66 | kalshi-kxlowmia | WATCH | 18/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 67 | kalshi-kxlownyc | WATCH | 18/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 68 | kalshi-kxlowny | WATCH | 18/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 69 | kalshi-kxlowchi | WATCH | 18/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 70 | kalshi-kxlowlax | WATCH | 18/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 71 | kalshi-kxhighnyd | WATCH | 18/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 72 | kalshi-kxlowphil | WATCH | 18/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 73 | kalshi-kxrain | WATCH | 17/30 | ~175 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 74 | kalshi-kxrainausm | WATCH | 17/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 75 | kalshi-kxrainchim | WATCH | 17/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 76 | kalshi-kxhmonth | NO-GO (gate: data) | 16/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 77 | kalshi-kxtornado | NO-GO (gate: data) | 16/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 78 | kalshi-rainsea | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 79 | kalshi-kxraind | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 80 | kalshi-kxsfosnowm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 81 | kalshi-kxrainsea | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 82 | kalshi-kxdensnowm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 83 | kalshi-kxsnowstorm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 84 | kalshi-kxrainnyc | WATCH | 14/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 85 | kalshi-kxrainstpm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 86 | kalshi-kxjacwsnowm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 87 | kalshi-kxsnowchim | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 88 | kalshi-rainnyc | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 89 | kalshi-kxlaxsnowm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 90 | kalshi-kxmiasnowm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 91 | kalshi-kxhousnowm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 92 | kalshi-kxchisnowm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 93 | kalshi-kxdetsnowm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 94 | kalshi-snowny | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 95 | kalshi-kxphilsnowm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 96 | kalshi-kxsnownyc | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 97 | kalshi-kxsnownym | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 98 | kalshi-kxrainholiday | WATCH | 14/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 99 | kalshi-kxdensnowxmas | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 100 | kalshi-kxdensnowmb | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 101 | kalshi-kxdcsnowm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 102 | kalshi-kxnycsnowm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 103 | kalshi-kxraindnyc | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 104 | kalshi-kxsnowny | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 105 | kalshi-kxdalsnowm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 106 | kalshi-kxnycsnowxmas | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 107 | kalshi-rainnycm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 108 | kalshi-kxbossnowm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 109 | kalshi-snowchim | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 110 | kalshi-kxrainlaxm | WATCH | 14/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 111 | kalshi-kxaussnowm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 112 | kalshi-kxsnowaz | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 113 | kalshi-snownym | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 114 | kalshi-kxseasnowm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 115 | kalshi-kxaspsnowm | WATCH | 14/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 116 | kalshi-kxmead | NO-GO (gate: data) | 13/30 | ~541 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 117 | kalshi-kxdroughtlevel | NO-GO (gate: data) | 13/30 | ~259 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 118 | kalshi-kxhurctotmaj | NO-GO (gate: data) | 13/30 | ~179 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 119 | kalshi-kxvei4 | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 120 | kalshi-kxwarming | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 121 | kalshi-hurcmaj | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 122 | kalshi-kxhurwil | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 123 | kalshi-kxheatwarning | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 124 | kalshi-emergencysf | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 125 | kalshi-snow | NO-GO (gate: resolution) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 126 | kalshi-kxevshare | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 127 | kalshi-hurcoasttex | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 128 | kalshi-kxhurmia | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 129 | kalshi-hotyear | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 130 | kalshi-hursav | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 131 | kalshi-kxercotx | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 132 | kalshi-emergencyla | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 133 | kalshi-kxusclimate | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 134 | kalshi-kxbiggestquake | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 135 | kalshi-kxhurnj | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 136 | kalshi-kxearthquakem | NO-GO (gate: data) | 10/30 | ~498 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 137 | kalshi-hurcal | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 138 | kalshi-kxxflare | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 139 | kalshi-avgtemp | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 140 | kalshi-kxco2 | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 141 | kalshi-kxemergencystl | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 142 | kalshi-kxhurpathhawaii | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 143 | kalshi-kxhursav | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 144 | kalshi-kxaqicity | NO-GO (gate: data) | 10/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 145 | kalshi-kxslcsnowm | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 146 | kalshi-kxemergencywil | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 147 | kalshi-hurnj | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 148 | kalshi-tornado | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 149 | kalshi-kxhurcati | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 150 | kalshi-hurcland | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 151 | kalshi-kxspurrerupt | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 152 | kalshi-hurmia | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 153 | kalshi-kxhurno | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 154 | kalshi-hurctot | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 155 | kalshi-fema | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 156 | kalshi-kxindiaclimate | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 157 | kalshi-emergencynola | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 158 | kalshi-kxemergencysf | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 159 | kalshi-kxhurctot | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 160 | kalshi-kxemergencylou | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 161 | kalshi-kxhurpathscarolina | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 162 | kalshi-kxhurcath | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 163 | kalshi-usclimate | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 164 | kalshi-hurcath | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 165 | kalshi-arcticicemin | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 166 | kalshi-kxarcticicemax | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 167 | kalshi-kxhurhat | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 168 | kalshi-kxemergencymia | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 169 | kalshi-kxfirsthurricane | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 170 | kalshi-kxhurricanenames | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 171 | kalshi-hurnyc | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 172 | kalshi-kxcoriver | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 173 | kalshi-kxearthquakem7 | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 174 | kalshi-kxemergencyhou | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 175 | kalshi-emergencyjac | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 176 | kalshi-emergencydes | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 177 | kalshi-kxeclipsecover | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 178 | kalshi-kxhurmyr | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 179 | kalshi-kxearthquakejapan | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 180 | kalshi-minnyc | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 181 | kalshi-emergencyrap | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 182 | kalshi-hurwil | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 183 | kalshi-kxco2level | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 184 | kalshi-kxeruptsuper | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 185 | kalshi-arcticicemax | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 186 | kalshi-coriver | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 187 | kalshi-hurnor | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 188 | kalshi-kxtsunami | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 189 | kalshi-kxhurpathgulfcoast | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 190 | kalshi-kxchisnowxmas | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 191 | kalshi-kxkilauea | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 192 | kalshi-kxhurorl | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 193 | kalshi-tropstorm | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 194 | kalshi-kxearthquake | NO-GO (gate: data) | 10/30 | ~700 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 195 | kalshi-hurctotmaj | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 196 | kalshi-kxeclipsecoverbuff | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 197 | kalshi-kxhurcmaj | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 198 | kalshi-kxgtemp | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 199 | kalshi-emergencyhou | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 200 | kalshi-emergencymia | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 201 | kalshi-evshare | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 202 | kalshi-kxminnyc | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 203 | kalshi-kxearthquakejapantatsuki | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 204 | kalshi-gtemp | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 205 | kalshi-kxemergencydes | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 206 | kalshi-kxhurpathhou | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 207 | kalshi-kxwasdestatcorn | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 208 | kalshi-kxhotyear | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 209 | kalshi-hurjackfl | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 210 | kalshi-kxnexthurdate | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 211 | kalshi-kxfema | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 212 | kalshi-emergencylou | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 213 | kalshi-kxemergencyphil | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 214 | kalshi-mead | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 215 | kalshi-kxeruptetna | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 216 | kalshi-kxhurnor | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 217 | kalshi-tsunami | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 218 | kalshi-kxarticice | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 219 | kalshi-kxhurcatfl | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 220 | kalshi-emergencycol | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 221 | kalshi-indiaclimate | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 222 | kalshi-emergencywil | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 223 | kalshi-kxhurricane | NO-GO (gate: data) | 10/30 | ~1 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 224 | kalshi-kxhurtb | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 225 | kalshi-kxhurcal | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 226 | kalshi-rainmia | NO-GO (gate: resolution) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 227 | kalshi-kxhurpathgeneral | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 228 | kalshi-kilauea | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 229 | kalshi-eclipsecover | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 230 | kalshi-kxhurcat | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 231 | kalshi-kxmaxtemp100 | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 232 | kalshi-hurcharl | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 233 | kalshi-kxelnino | NO-GO (gate: data) | 10/30 | ~437 | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 234 | kalshi-kxhurjackfl | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 235 | kalshi-hurcat | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 236 | kalshi-articice | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 237 | kalshi-kxemergencycol | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 238 | kalshi-kxhurcoasttex | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 239 | kalshi-kxhurpathgeneralmajor | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 240 | kalshi-ercotx | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 241 | kalshi-kxearthquakela | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 242 | kalshi-euclimate | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 243 | kalshi-hurtb | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 244 | kalshi-kxnextcat5hurdate | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 245 | kalshi-kxhurpathfla | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 246 | kalshi-eclipsecoverbuff | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 247 | kalshi-kxarcticicemin | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 248 | kalshi-hurhat | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 249 | kalshi-kxroni | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 250 | kalshi-kxhurcland | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 251 | kalshi-kxnamedstorm | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 252 | kalshi-co2 | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 253 | kalshi-kxemergencyjac | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 254 | kalshi-kxavgtemp | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 255 | kalshi-hurorl | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 256 | kalshi-hurno | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 257 | kalshi-hurcatfl | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 258 | kalshi-kxearthquakecalifornia | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 259 | kalshi-kxemergencynola | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 260 | kalshi-kxemergencyrap | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 261 | kalshi-earthquake | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 262 | kalshi-kxeruptkiluaea | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 263 | kalshi-kxeuclimate | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 264 | kalshi-hurcati | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 265 | kalshi-emergencystl | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 266 | kalshi-kxbossnowxmas | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 267 | kalshi-kxtropstorm | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 268 | kalshi-hmonth | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 269 | kalshi-kxhurcharl | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 270 | kalshi-hurmyr | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 271 | kalshi-kxhurnyc | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 272 | kalshi-kxsnows | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 273 | kalshi-emergencyphil | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |
| 274 | kalshi-kxemergencyla | NO-GO (gate: data) | 10/30 | unknown | taker 2c / maker 1c at 50c | cannot clear the 2.5 OOS-Sharpe bar yet — needs a paper-only period first |

_Detail sections below cover the top 20 of 274 candidates; the table above is complete._

## kalshi-denver

- **data** 2/2 — GEFS/IFS/HRRR TMAX (already ingested)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: NWS Climatological Report
- **market** 2/2 — avg settled volume 9,479, median spread 1c
- **fees** 1/2 — taker 2c / maker 1c at 50c
- **durability** 2/2 — 2686 paper signals over 391d for this station
- **capital** 1/2 — T+1: capital locked until day-after settlement.
- **regulatory** 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

## kalshi-nyc

- **data** 2/2 — GEFS/IFS/HRRR TMAX (already ingested)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: NWS Climatological Report
- **market** 2/2 — avg settled volume 37,152, median spread 2c
- **fees** 1/2 — taker 2c / maker 1c at 50c
- **durability** 2/2 — 7284 paper signals over 786d for this station
- **capital** 1/2 — T+1: capital locked until day-after settlement.
- **regulatory** 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

## forecastex-miami

Exact station port (same KMIA settlement). Trades through resolution day, ~1/2 Kalshi fee. Open Qs: morning depth, rulebook PDF, account access.

- **data** 2/2 — GEFS/IFS/HRRR TMAX (already ingested)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: NWS Climatological Report Miami
- **market** 1/2 — own depth unknown — morning depth unknown (needs a snapshotter before sizing); Kalshi same-station proxy: avg volume 32,125, spread 1c
- **fees** 2/2 — ~1/2 Kalshi: taker 1c vs 2c at 50c
- **durability** 2/2 — 2135 paper signals over 391d for this station
- **capital** 2/2 — Same-day trading through resolution; only cash settles T+1.
- **regulatory** 1/2 — CFTC-regulated DCM via IBKR; US persons OK pending account-access check. OPEN: Germany/US-only account access unresolved — do not circumvent

## forecastex-dallas

Exact station port; Dallas already live on Kalshi (operator override).

- **data** 2/2 — GEFS/IFS/HRRR TMAX (already ingested)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: NWS Climatological Report Dallas FW
- **market** 1/2 — own depth unknown — morning depth unknown (needs a snapshotter before sizing); Kalshi same-station proxy: avg volume 10,180, spread 2c
- **fees** 2/2 — ~1/2 Kalshi: taker 1c vs 2c at 50c
- **durability** 2/2 — 779 paper signals over 161d for this station
- **capital** 2/2 — Same-day trading through resolution; only cash settles T+1.
- **regulatory** 1/2 — CFTC-regulated DCM via IBKR; US persons OK pending account-access check. OPEN: Germany/US-only account access unresolved — do not circumvent

## kalshi-lows-chicago

Daily LOW brackets — same ingest + EMOS on TMIN; lows backfill script exists.

- **data** 2/2 — GEFS/IFS/HRRR TMIN (same ingest, lows backfill exists)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: NWS Climatological Report Chicago Midway
- **market** 1/2 — tradeable but thin: avg volume 4,412, spread 2c
- **fees** 1/2 — taker 2c / maker 1c at 50c
- **durability** 2/2 — 3655 paper signals over 391d for this station
- **capital** 1/2 — T+1: capital locked until day-after settlement.
- **regulatory** 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

## kalshi-kxhightsfo

auto-discovered from catalog: San Francisco High Temperature Daily

- **data** 1/2 — GEFS/IFS/HRRR TMAX/TMIN (already ingested); station not in STATIONS yet (add lat/lon + NWS obs)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: NWS Climatological Report San Francisco
- **market** 2/2 — avg settled volume 14,240, median spread 2c
- **fees** 1/2 — taker 2c / maker 1c at 50c
- **durability** 1/2 — same signal family as proven cities; no station-specific evidence yet
- **capital** 1/2 — T+1: capital locked until day-after settlement.
- **regulatory** 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

## kalshi-kxhightmin

auto-discovered from catalog: Minneapolis Daily High Temperature

- **data** 1/2 — GEFS/IFS/HRRR TMAX/TMIN (already ingested); station not in STATIONS yet (add lat/lon + NWS obs)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: NWS Climatological Report Minneapolis
- **market** 2/2 — avg settled volume 6,442, median spread 2c
- **fees** 1/2 — taker 2c / maker 1c at 50c
- **durability** 1/2 — same signal family as proven cities; no station-specific evidence yet
- **capital** 1/2 — T+1: capital locked until day-after settlement.
- **regulatory** 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

## kalshi-kxhightdc

auto-discovered from catalog: Washington DC Daily Max Temp

- **data** 1/2 — GEFS/IFS/HRRR TMAX/TMIN (already ingested); station not in STATIONS yet (add lat/lon + NWS obs)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: NWS Climatological Report DC 
- **market** 2/2 — avg settled volume 6,217, median spread 3c
- **fees** 1/2 — taker 2c / maker 1c at 50c
- **durability** 1/2 — same signal family as proven cities; no station-specific evidence yet
- **capital** 1/2 — T+1: capital locked until day-after settlement.
- **regulatory** 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

## kalshi-kxhighphil

auto-discovered from catalog: Highest temperature in Philadelphia

- **data** 1/2 — GEFS/IFS/HRRR TMAX/TMIN (already ingested); station not in STATIONS yet (add lat/lon + NWS obs)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: NWS Climatological Report
- **market** 2/2 — avg settled volume 7,420, median spread 2c
- **fees** 1/2 — taker 2c / maker 1c at 50c
- **durability** 1/2 — same signal family as proven cities; no station-specific evidence yet
- **capital** 1/2 — T+1: capital locked until day-after settlement.
- **regulatory** 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

## kalshi-kxhighthou

auto-discovered from catalog: Daily High Temperature Houston

- **data** 1/2 — GEFS/IFS/HRRR TMAX/TMIN (already ingested); station not in STATIONS yet (add lat/lon + NWS obs)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: NWS Climatological Report Houston
- **market** 2/2 — avg settled volume 7,235, median spread 1c
- **fees** 1/2 — taker 2c / maker 1c at 50c
- **durability** 1/2 — same signal family as proven cities; no station-specific evidence yet
- **capital** 1/2 — T+1: capital locked until day-after settlement.
- **regulatory** 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

## kalshi-kxhightatl

auto-discovered from catalog: Atlanta Max Temperature

- **data** 1/2 — GEFS/IFS/HRRR TMAX/TMIN (already ingested); station not in STATIONS yet (add lat/lon + NWS obs)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: NWS Climatological Report Atlanta
- **market** 2/2 — avg settled volume 11,792, median spread 2c
- **fees** 1/2 — taker 2c / maker 1c at 50c
- **durability** 1/2 — same signal family as proven cities; no station-specific evidence yet
- **capital** 1/2 — T+1: capital locked until day-after settlement.
- **regulatory** 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

## kalshi-kxhightbos

auto-discovered from catalog: Boston Maximum Daily Temperature

- **data** 1/2 — GEFS/IFS/HRRR TMAX/TMIN (already ingested); station not in STATIONS yet (add lat/lon + NWS obs)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: NWS Climatological Report Boston
- **market** 2/2 — avg settled volume 9,337, median spread 1c
- **fees** 1/2 — taker 2c / maker 1c at 50c
- **durability** 1/2 — same signal family as proven cities; no station-specific evidence yet
- **capital** 1/2 — T+1: capital locked until day-after settlement.
- **regulatory** 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

## kalshi-kxhightokc

auto-discovered from catalog: Oklahoma City Maximum High Temperature

- **data** 1/2 — GEFS/IFS/HRRR TMAX/TMIN (already ingested); station not in STATIONS yet (add lat/lon + NWS obs)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: NWS Climatological Report OKC
- **market** 2/2 — avg settled volume 6,042, median spread 1c
- **fees** 1/2 — taker 2c / maker 1c at 50c
- **durability** 1/2 — same signal family as proven cities; no station-specific evidence yet
- **capital** 1/2 — T+1: capital locked until day-after settlement.
- **regulatory** 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

## kalshi-kxtempdch

auto-discovered from catalog: Hourly Directional DC Temperature

- **data** 2/2 — GEFS/IFS/HRRR TMAX/TMIN (already ingested)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: The Weather Company
- **market** 1/2 — tradeable but thin: avg volume 2,315, spread 4c
- **fees** 1/2 — taker 2c / maker 1c at 50c
- **durability** 1/2 — same signal family as proven cities; no station-specific evidence yet
- **capital** 1/2 — T+1: capital locked until day-after settlement.
- **regulatory** 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

## kalshi-kxtempnych

auto-discovered from catalog: Hourly Directional NYC Temperature

- **data** 2/2 — GEFS/IFS/HRRR TMAX/TMIN (already ingested)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: The Weather Company
- **market** 1/2 — tradeable but thin: avg volume 2,339, spread 2c
- **fees** 1/2 — taker 2c / maker 1c at 50c
- **durability** 1/2 — same signal family as proven cities; no station-specific evidence yet
- **capital** 1/2 — T+1: capital locked until day-after settlement.
- **regulatory** 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

## kalshi-kxtempchih

auto-discovered from catalog: Hourly Directional Chicago Temperature

- **data** 2/2 — GEFS/IFS/HRRR TMAX/TMIN (already ingested)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: The Weather Company
- **market** 1/2 — tradeable but thin: avg volume 3,023, spread 1c
- **fees** 1/2 — taker 2c / maker 1c at 50c
- **durability** 1/2 — same signal family as proven cities; no station-specific evidence yet
- **capital** 1/2 — T+1: capital locked until day-after settlement.
- **regulatory** 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

## kalshi-kxhmonthrange

auto-discovered from catalog: Monthly Temperature Increase (ºC)

- **data** 2/2 — GEFS/IFS/HRRR TMAX/TMIN (already ingested)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: National Oceanic and Atmospheric Administration
- **market** 1/2 — tradeable but thin: avg volume 17,917, spread 5c
- **fees** 1/2 — taker 2c / maker 1c at 50c
- **durability** 1/2 — same signal family as proven cities; no station-specific evidence yet
- **capital** 1/2 — T+1: capital locked until day-after settlement.
- **regulatory** 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

## kalshi-kxtempaush

auto-discovered from catalog: Hourly Directional Austin Temperature

- **data** 2/2 — GEFS/IFS/HRRR TMAX/TMIN (already ingested)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: The Weather Company
- **market** 1/2 — tradeable but thin: avg volume 2,884, spread 10c
- **fees** 1/2 — taker 2c / maker 1c at 50c
- **durability** 1/2 — same signal family as proven cities; no station-specific evidence yet
- **capital** 1/2 — T+1: capital locked until day-after settlement.
- **regulatory** 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

## kalshi-kxtemplaxh

auto-discovered from catalog: Hourly Directional Los Angeles Temperature

- **data** 2/2 — GEFS/IFS/HRRR TMAX/TMIN (already ingested)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 2/2 — settlement sources on series: The Weather Company
- **market** 1/2 — tradeable but thin: avg volume 3,015, spread 1c
- **fees** 1/2 — taker 2c / maker 1c at 50c
- **durability** 1/2 — same signal family as proven cities; no station-specific evidence yet
- **capital** 1/2 — T+1: capital locked until day-after settlement.
- **regulatory** 2/2 — CFTC-regulated DCM; US persons OK; live keys on this box.

## forecastex-chicago

ForecastEx Chicago settles KMDW, not KORD — basis risk vs our live KORD edge; KMDW paper backfill exists.

- **data** 2/2 — GEFS/IFS/HRRR TMAX (already ingested)
- **tract** 2/2 — EMOS Gaussian -> bracket integration, proven in production
- **resolution** 1/2 — NWS CLI report standard for temp; DH contracts trade THROUGH resolution day (last trade 11:59pm local); cash settles T+1. 5/6 station match; Chicago = KMDW, not KORD.
- **market** 1/2 — own depth unknown — morning depth unknown (needs a snapshotter before sizing)
- **fees** 2/2 — ~1/2 Kalshi: taker 1c vs 2c at 50c
- **durability** 1/2 — same signal family as proven cities; no station-specific evidence yet
- **capital** 2/2 — Same-day trading through resolution; only cash settles T+1.
- **regulatory** 1/2 — CFTC-regulated DCM via IBKR; US persons OK pending account-access check. OPEN: Germany/US-only account access unresolved — do not circumvent

