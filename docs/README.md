# docs/ — index

Map of all project documentation. Start at [/CLAUDE.md](../CLAUDE.md) for orientation;
this page lists everything by category. New agents: read **context/** first.

## context/ — agent onboarding (read these first)
Authored from the code + live DB; kept current. Uniform template (TL;DR → tables → Sources → See also).

| File | What it covers |
|---|---|
| [context/architecture.md](context/architecture.md) | End-to-end pipeline + module/scripts map |
| [context/data-model.md](context/data-model.md) | The `weather` Postgres schema (7 tables, exact columns/units) |
| [context/strategy.md](context/strategy.md) | EMOS → edge → Benter blend → sizing/execution/risk; CITY_CONFIG |
| [context/dashboard.md](context/dashboard.md) | FastAPI endpoints, payload→UI contract, live WS marks, sim parity |
| [context/operations.md](context/operations.md) | Cron schedule, trading-day timeline, kill switches, how to run |
| [context/conventions.md](context/conventions.md) | Hard rules: uv, tmux, crontab, freeze, secrets, tests |
| [context/glossary.md](context/glossary.md) | Domain terms (EMOS, edge, blend, T-series, hypertable, …) |

## reference/ — living technical references
| File | What it covers |
|---|---|
| [reference/frontend-architecture.md](reference/frontend-architecture.md) | Dashboard stack deep-dive + how to extend |
| [reference/investor-overview.md](reference/investor-overview.md) | Non-technical business overview |
| [reference/roadmap.md](reference/roadmap.md) | Month-by-month project plan (some sections predate live trading) |
| `/Research.md` (repo root) | Deep GEFS/Kalshi/market-mechanics reference. **Local-only — gitignored**, not in clones. |

## operations
| File | What it covers |
|---|---|
| [crontab.txt](crontab.txt) | **Authoritative** cron schedule. Edit here → `crontab docs/crontab.txt`. |
| [backlog.md](backlog.md) | Strategy research backlog (ideas deferred to the next config re-eval). |

## decisions/ — dated, static decision & methodology records
| File | What it covers |
|---|---|
| [decisions/config-freeze-2026-06-12.md](decisions/config-freeze-2026-06-12.md) | Frozen params (until 2026-07-10) and why |
| [decisions/edge-test-protocol.md](decisions/edge-test-protocol.md) | Pre-registration protocol for new cities |
| [decisions/live-trading-plan.md](decisions/live-trading-plan.md) | Pre-launch checklist |
| [decisions/halt-2026-06-06.md](decisions/halt-2026-06-06.md) | Why live trading was halted 2026-06-06 |
| [decisions/precommits/](decisions/precommits/) | Per-city/phase pre-registered decisions (chicago-resume, miami-resume, miami-only-amount, chicago-miami-live, cross-city) |
| [decisions/archive/](decisions/archive/) | Obsolete one-offs (e.g. the scripts-cleanup triage) |

## Also relevant (outside docs/)
- Auto-memory (session continuity, not in the repo): `~/.claude/projects/-home-tdunn/memory/` — empirical findings (`project_*_finding`) and feedback rules.
- Code: [src/weather_markets/](../src/weather_markets/), [scripts/](../scripts/), [dashboard/](../dashboard/), [tests/](../tests/).
