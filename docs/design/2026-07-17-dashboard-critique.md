# Dashboard frontend critique — ISOBAR live trading desk

`/impeccable critique` · 2026-07-17 · target: `dashboard/static/` (live view + backtest tab)
**Method: dual-agent** (A: independent design review, isolated · B: detector + browser-evidence + contrast, isolated).
B was truncated mid-run by an upstream 529; its full evidence set (detector JSON, browser-availability probe, WCAG contrast math) was recovered and completed by the orchestrator, so the run is complete — **not degraded**.
Register: **Product** (design serves the task; the tool should disappear into the operator's monitoring/research flow).

> ⚠️ **Screenshot limitation (read this).** No browser is installed on this host and there is no `DISPLAY`. This box is the live-money production server (7.6 GB RAM, **no swap**, live Postgres) with a documented history of OOM taking down live trading (2026-06-19). I deliberately did **not** install or launch a headless browser to capture pixels. Instead the critique is grounded in the full source — which for the accessibility/typography/spacing dimensions is *more* precise than eyeballing (exact token hex → computed contrast ratios, exact px sizes, exact grid definitions and breakpoints). Layout-gestalt claims (the card row, mobile overflow) are derived from the CSS grid math and confirmed against the live `/api/live` payload. If you want real screenshots at desktop/tablet/mobile, I can install a short-lived headless Chromium and capture 6 views — say the word and accept the (small, single-process) OOM risk.

---

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 3 | Rich (clock, ws/rest/age pill, cron countdown, HRRR freshness, kill state, per-poll flash) — but a **connected-but-stale** feed is shown as healthy green; no `ageMs` threshold (`updateLiveIndicator`, app.js:1445-1458). |
| 2 | Match system / real world | 4 | Speaks the quant's language natively (brackets, edge, EMOS, Benter, Sharpe, ¢, YES/NO); thermal = temperature is domain-true. |
| 3 | User control & freedom | 2 | The 2 s full-`innerHTML` rebuild wipes scroll position, collapses the params `<details>`, drops chart hover, and **evicts keyboard focus** every poll; no way to pause the poll. |
| 4 | Consistency & standards | 3 | Tokens/pills/tables reused well; green=up/red=down conventional — but **two saturated reds mean opposite things** (loss vs best-Sharpe), and legacy `--pos/--neg` still linger in `cronAlerts`. |
| 5 | Error prevention | 3 | Read-only telemetry; number inputs partly guarded (`btSetBankroll` min-100, app.js:1352). Small surface. |
| 6 | Recognition rather than recall | 3 | Labels + `title=` tooltips + legends everywhere — but the signal-strategy-vs-sim-strategy and ladder-edge-vs-sim-edge split taxes memory. |
| 7 | Flexibility & efficiency | 3 | Per-city auto-load-best-params (`findBestParams`, app.js:1360) is a real power win; native controls keyboard-reachable; no tab/hotkeys. |
| 8 | Aesthetic & minimalist | 3 | Live tab is clean and legible; Backtest tab is very dense with two *duplicated* control concepts. |
| 9 | Help recognize/recover errors | 3 | Kill banner with reason + timestamp (app.js:703), backfilling "no action needed", load-fail messages — but stale marks go undiagnosed. |
| 10 | Help & documentation | 3 | Inline: params expander documents live config + halt-file commands (app.js:779); every panel `.meta` explains itself. |
| **Total** | | **30 / 40** | **"Good"** — upper end of the typical 20–32 band. |

Honest caveat: Nielsen's 40 has no dedicated accessibility axis. Scored on its own, a11y is the soft underbelly (label-layer contrast fails AA, keyboard focus is destroyed every 2 s, SVGs are unlabeled) and would pull a separate a11y grade well below this.

---

## Anti-Patterns Verdict — does this look AI-generated?

**LLM assessment: above the slop line, with real, mostly-earned personality.** A Linear/Stripe/Bloomberg-fluent operator would largely *trust* this — it reads as a purpose-built trading desk, not a template. The usual tells are absent: domain-correct language throughout, disciplined `tabular-nums` so rows never reflow (components.css:9-10), restrained glass tint (`rgba(255,255,255,0.045)`), and — the standout — a **thermal ramp that is genuinely semantic, not decorative**: cold→hot maps to *temperature*, which is literally the traded quantity, and it drives the ensemble histogram, bracket-ladder rungs, and EMOS curve. That is the opposite of ornamental gradient-slop.

Where it still reads AI-adjacent / makes a fluent user pause:
- **Glassmorphism used as a default surface.** `backdrop-filter: blur(14px)` sits on the topbar, the hero, *and* all six status chips (live.css:52, shell.css:11, live.css:31). Over near-black `#090D15` with 4.5%-white glass the blur is barely perceptible — decorative glass that costs GPU for ~zero payoff. This is the one choice that trips the "Glassmorphism as default" ban.
- **Two nearly-identical reds meaning opposite things** (see P3 below).
- **A 2.4 s animated count-up before the P&L is legible** on a glance instrument reopened dozens of times a day (LOAD_MS, app.js:12).
- **A third font family (Space Grotesk) for ~two strings** (see Minor).

**Deterministic scan** (`detect.mjs`): `index.html` → exit 2, **1 finding**: `overused-font` (Space Grotesk, index.html:9, `warning`). `app.js` → effectively clean. **Reach caveat (important):** `index.html` is a 48-line shell; ~95 % of the rendered DOM is generated at runtime from `app.js` template strings and is invisible to a static markup scanner. A near-clean detector result here does **not** mean the rendered UI is clean — the real findings below came from source reasoning + computed contrast, not the scanner.

**Visual overlays: UNAVAILABLE** (no browser, no `DISPLAY`; not installed by policy on this live-money box). No user-visible overlay was injected; treat the deterministic scan + computed contrast as the machine evidence.

**Computed WCAG contrast** (sRGB-linearized, orchestrator-verified):

| Pair (foreground on background) | Ratio | AA (normal ≥4.5 / large ≥3.0) |
|---|---|---|
| `--text-hi` #EAF0FB on `--bg-1` #111826 | 15.52 | PASS |
| `--text-mid` #8E9CB4 on `--bg-1` (**table data / values**) | 6.40 | PASS |
| `--text-mid` on `--bg-2` #182032 | 5.86 | PASS |
| `--text-lo` #58657E on `--bg-1` (**most labels/eyebrows/meta**) | **3.03** | **FAIL (normal)** |
| `--text-lo` on `--bg-2` (uppercase `th` labels) | **2.77** | **FAIL** |
| `--text-faint` #3E495E on `--bg-1` (**`.ms` sub-values, recon line, axes**) | **1.96** | **FAIL** |
| `--text-faint` on `--bg-2` | **1.80** | **FAIL** |
| `--up` #2FD08A on `--bg-1` | 8.89 | PASS |
| `--down` #F4476B on `--bg-1` | 5.04 | PASS |
| `--warn` #FBBF24 on `--bg-1` | 10.64 | PASS |
| `--accent` #38BDF8 on `--bg-1` | 8.29 | PASS |

The **data** is readable; the **label layer that tells you what each number is** is not. See P1-contrast.

---

## Overall Impression

This is a competent, characterful, above-average trading dashboard whose biggest problems are not aesthetic but **behavioral and accessible**. The single most consequential defect is the every-2-second full-`innerHTML` rebuild, which quietly makes the tool feel broken to anyone who tries to *interact* with it (scroll a table, keep a panel open, tab with a keyboard, read a tooltip). Right behind it is a **real-money trust gap**: a stale feed presented as healthy green. Fix those two and lift the label-contrast tier, and this jumps from "Good" to genuinely excellent. The design identity (the thermal ramp) is strong and worth protecting; the glass is the weakest borrowed idea and can be dialed back with no loss.

**Single biggest opportunity:** stop nuking the DOM. Patch it. Everything from interaction-state loss to keyboard-focus eviction to the "why won't this panel stay open" friction collapses into that one change.

---

## What's Working

1. **The thermal ramp is real domain semantics, not decoration.** Color encodes *temperature* — the traded quantity — consistently across the ensemble histogram (app.js:180), bracket boundaries, and the hottest→coldest bracket ladder (app.js). The "signature" *is* a data axis. This is what earned personality looks like, and it's rare.
2. **Color-plus-sign redundancy in every money formatter.** `money()`, `pct()`, `edgeCell()` all prepend `+`/`−` (U+2212) *in addition* to the green/red class (app.js:20-37, 298-302). P&L direction survives colorblindness, grayscale, and low-contrast rendering — textbook-correct financial formatting, and it's why the color-alone-semantics failure mode mostly does **not** apply here.
3. **Missing-data honesty + reduced-motion respect.** Every table has a purpose-written empty state ("No open positions — all flat", "No signals logged today"), charts degrade gracefully, the kill banner explains *why* trading halted with a timestamp, and `prefers-reduced-motion` is fully honored (rampClock jumps to final; tokens.css:133-142). Exactly the reassurance a real-money operator needs.

---

## Priority Issues

### [P1] Full `innerHTML` replacement every 2 s destroys interaction state
- **What:** `renderLive()` sets `root.innerHTML = …` on every 2 s poll (app.js:788; loop in `startLivePolling`, app.js:1442). This wipes `scrollTop` inside every `.tbl-scroll` (positions/signals scroll at max-height 320 px), collapses `<details class="params">` (app.js:779 — no `open` reinstated), clears chart hover overlays, and **destroys keyboard focus and text selection**.
- **Why it matters:** the operator cannot keep the strategy-params panel open, cannot scroll the signals table without it snapping to top, cannot finish reading a chart tooltip, and (for keyboard/SR users) is ejected from the tab — every two seconds. On a *monitoring* tool this is the most-felt defect, and it's a hard accessibility blocker (effectively **P0 for keyboard/screen-reader users**).
- **Fix:** diff-patch instead of nuke — the code already keeps `prevLive` and tweens individual numbers; extend that to node-level updates of the tables/chips. Minimum viable: snapshot/restore each `.tbl-scroll` `scrollTop` and the `<details open>` state around the `innerHTML` swap in `renderLive()`.
- **Suggested command:** `/impeccable harden` (state preservation / edge cases), then `/impeccable optimize`.

### [P1] Stale live marks are presented as healthy
- **What:** `updateLiveIndicator` colors the refresh dot `var(--pos)` (green) whenever `lv.connected` is truthy and **ignores `lv.ageMs`** (app.js:1457). Assessment A observed the live payload at `ageMs ≈ 917 000` (~15 min stale) still pulsing green with label "ws · 9 live · 917s". (At write time it was a healthy 12.6 s — the point is structural: no staleness threshold exists anywhere.) The green `pulse` animation (`.dot.live`, shell.css:43) is also never swapped to `pulse-red`.
- **Why it matters:** a frozen feed shown as live is dangerous on a real-money desk — the operator monitors against marks that aren't moving under a reassuring green light. The first time they notice, trust collapses.
- **Fix:** threshold `ageMs` in `updateLiveIndicator` (e.g. >120 s → amber `--warn`, >600 s → red, switch the dot to the existing `pulse-red`), and mirror the same state into the "Live feed" status chip (app.js:699). The token + animation already exist (`pulse-red`, live.css:59).
- **Suggested command:** `/impeccable clarify` (status truthfulness) or a targeted `/impeccable harden`.

### [P1] The label layer fails WCAG AA contrast
- **What (computed):** on `--bg-1`, `--text-faint` ≈ **1.96:1** and `--text-lo` ≈ **3.03:1** (2.77 on `--bg-2`). These carry the *bulk* of labeling at 9.5–10.5 px: `.ms` sub-values ("settled"/"open mark", live.css:102), table `th` eyebrows (9.5 px, components.css:16), `.section-label` (shell.css:97), `.panel-h .meta`, chip `.l` labels, chart-axis text. Compounding it: **no `aria-live`** on the polling numbers and **no text alternative** on any SVG (P&L, ensemble, bracket ladder, calibration) — the ladder encodes edge as bar-width + color only, invisible to a screen reader.
- **Why it matters:** in dense telemetry the label tells you what the number *is*; sub-3:1 labels at sub-10 px are effectively decorative, and the whole tab is unusable to a screen-reader/low-vision operator.
- **Fix:** lift `--text-lo` to ≈ `#7A88A0` (~4.6:1) and reserve `--text-faint` for non-text hairlines only (tokens.css:21-22) — the cheapest global win in the file. Add `aria-live="polite"` to the hero P&L region and `role="img" aria-label="…"` (or a visually-hidden summary) to each chart.
- **Suggested command:** `/impeccable audit` (a11y sweep) → `/impeccable colorize`/`typeset` for the ink ramp.

### [P2] The per-city row doesn't reconcile, and its grid silently degrades
- **What:** two problems in one row. (a) The payload carries a top-level `otherCities` block (**confirmed present** in `/api/live`) but `cityCard` is only mapped over `d.cities` (app.js:791 is the sole call site) → `otherCities` is **never rendered**, and the dedicated `.city.other` styling (live.css:94-96) is **dead code**. The four visible cards therefore don't sum to the hero cumulative. (b) `renderLive` builds `.grid g-${d.cities.length}` (app.js:787), but shell.css only defines `.g-2…g-5` (shell.css:85-88). Today `cities.length === 4` → `g-4` (fine). At **6+ cities**, `.g-6` doesn't exist → `.grid` falls back to a single implicit column and every card stacks full-width at *every* breakpoint. `.g-2` also has no responsive override.
- **Why it matters:** the live universe is already growing (Chicago/Miami/Dallas/Phoenix live today; Seattle on watch). At 6 the layout collapses with no warning, and *right now* the operator sees a per-city sum that doesn't equal the headline number.
- **Fix:** replace the whole `.g-N` family for this row with `grid-template-columns: repeat(auto-fit, minmax(240px, 1fr))` (one rule kills the class family and its responsive overrides), and either render `otherCities` as its `.city.other` card or fold it into a visible reconciliation line under the hero.
- **Suggested command:** `/impeccable adapt` (responsive) + `/impeccable layout`.

### [P2] The bracket ladder overflows on mobile (horizontal body scroll)
- **What:** `.rung` is a fixed six-column grid `118px 1fr 52px 92px 118px 56px` (~500 px + gaps, backtest.css:80-81) with **no** `overflow-x` wrapper and **no** `<720 px` override (responsive.css has no `.rung`/`.ladder` rule). The ladder panel is *not* inside a `.tbl-scroll`. On a phone this forces either a crushed track or horizontal scroll of the whole page body.
- **Why it matters:** violates the baseline "wide content scrolls inside its own container; the page body never scrolls horizontally." The data tables are safe (they sit in `.tbl-scroll`); the ladder is the leak.
- **Fix:** wrap `.ladder` in an `overflow-x: auto` container with a `min-width`, or add a `<720 px` rule that drops the ladder to a stacked label/track/value layout.
- **Suggested command:** `/impeccable adapt`.

### [P3] Semantic red collision — loss red ≈ best-Sharpe heat red
- **What:** `--down` (loss, #F4476B) and `--extreme` (record heat, #EF5350) are near-identical saturated reds (tokens.css:30, 42), and `btSharpeColor` (app.js:908-913) maps Sharpe **≥ 2 → `--extreme`**. So the *best* config — and the strategy at/above the **deploy bar (2.5 OOS Sharpe)** — glows in a red almost indistinguishable from a losing position.
- **Why it matters:** red=loss is the strongest convention in the app; painting "best / deployable" in the same red is a legibility trap on the exact metric the operator cares most about.
- **Fix:** don't route Sharpe through the temperature ramp. Use a neutral→`--up` "quality" scale for Sharpe; keep the thermal ramp exclusively for actual °F.
- **Suggested command:** `/impeccable colorize`.

---

## Persona Red Flags

**Alex (power user).** Params `<details>` won't stay open and `.tbl-scroll` resets every 2 s (app.js:788) — kills fast triage. No way to pause/freeze the live poll; no keyboard shortcut for tab switch (`switchTab` is click-only, app.js:1461). The signal-strategy vs sim-strategy and ladder-edge vs sim-edge duplication is powerful but not glanceable — which picker drives which panel isn't obvious.

**Sam (accessibility / SR / keyboard / contrast).** **Keyboard focus is destroyed every 2 s** by the live `innerHTML` swap — a keyboard user is ejected every poll (hard blocker). No `aria-live` on polling numbers; no text alternative on any SVG (the bracket ladder's edge is bar-width + color only). Sub-10 px type: `th` 9.5 px, `.dial .inner` 8.5 px (live.css:110), `.chosen-tag` 8.5 px (components.css:30), plus the `--text-lo`/`--text-faint` contrast failures. `.ico.err` conveys "error" by red + animation (live.css:58), though most chips do pair a text value.

**Riley (stress-tester).** 6 cities → single-column stack at all widths (`.g-6` undefined). 0 cities → "0/0 cities live" under a lonely section label. `otherCities` present in payload but never drawn → hero doesn't reconcile to the cards. Mid-poll: scroll/details/hover/focus all reset. Mobile: the bracket ladder overflows the body. `class="pill-status —"` emitted when a signal `fill` is the em-dash placeholder (app.js:745) — harmless but sloppy. Long tickers truncated with a *leading* "…" hide the series prefix.

---

## Minor Observations

- **Space Grotesk** (`--display`) is a whole third font family loaded for ~two strings (`.brand .name`, `.city .nm`). Detector-flagged as overused; question whether it earns the network cost — or promote it to more headings so it pulls its weight.
- **Dead motion CSS:** the View-Transitions cross-fade block (shell.css:73-80) is inert — `switchTab` never calls `document.startViewTransition`. Ships as "progressive enhancement" but does nothing.
- **`--glow` token** (tokens.css:75) is defined but effectively unused; real glows are inlined per component.
- **Legacy color aliases** `--pos/--neg` still referenced in `cronAlerts` (app.js:771) while the rest migrated to `--up/--down`; the alias block (tokens.css:48-59) is load-bearing until that's finished.
- **Entrance stagger** caps at the 9th child (`nth-child(n+9)`, live.css:25) — extra panels all fire on the same frame. Fine, just won't extend.
- **2.4 s count-up (LOAD_MS)** feels premium once, then becomes a valley on a glance tool. Consider ~800 ms, or first-session-load only.

---

## Questions to Consider

- On a real-money monitor, is a 2.4 s count-up ever worth making the operator wait to read their P&L? What breaks if it drops to ~800 ms or fires only on first session load?
- The Backtest tab carries **two** strategy selectors and **two** edge selectors. Is "signal strategy ≠ sim strategy" a workflow the operator actually uses, or complexity that exists because the code *can*? Would one strategy + a single "compare all three" table lower load without losing power?
- Is the per-city row meant to be an *exhaustive ledger* (then render `otherCities` and make it sum to the hero) or a *watchlist* (then label it "live cities" so the non-reconciliation is honest)? The answer picks the P2 fix.
- The thermal ramp is the strongest idea here. Lean harder (e.g. hero tinting toward heat as cumulative return climbs) — or keep temperature-color sacred to actual °F so it never goes ambiguous? (If you keep it sacred, that's another reason to pull Sharpe off the heat ramp — see P3.)

---

## REDESIGN BRIEF (direction for the next agent)

**Don't redesign the look — it's already good and identity-forward. Re-engineer the behavior, fix the a11y floor, and tighten the backtest tab. Preserve the thermal ramp as the signature.**

**Non-negotiable invariant:** the JS↔Python sim parity slice in `app.js` (`jsComputeSim` … `BTMetric`, roughly app.js:309-623) is byte-tested by `tests/test_sim_parity.py`. Do not touch it, or edit `dashboard/sim_python.py` in lockstep. Design/render changes must stay outside that slice.

**Direction, in priority order:**
1. **Make the live tab stateful, not re-rendered.** Replace the 2 s `innerHTML` nuke with targeted node updates (extend the existing `prevLive` diff to tables/chips/details). This one change fixes scroll loss, the collapsing params panel, hover loss, and keyboard-focus eviction simultaneously. This is the whole ballgame.
2. **Tell the truth about freshness.** Age-threshold the live indicator + status chip; green only when marks are actually fresh. Add `aria-live="polite"` to the hero while you're in there.
3. **Lift the ink floor.** Bump `--text-lo` to ~4.6:1, retire `--text-faint` from all text roles, add SVG text alternatives. Keep the passing data/`--up`/`--down`/`--warn` colors as-is.
4. **Fix the per-city row for growth.** `auto-fit minmax(240px,1fr)`; render `otherCities` (or relabel the row) so it reconciles to the hero.
5. **Contain wide content on mobile.** Wrap the bracket ladder (and audit any other fixed-width grid) so the body never scrolls horizontally.
6. **Quiet the borrowed bits.** Reduce glass to purposeful surfaces (topbar only, or drop it), pull Sharpe off the heat ramp, and either justify or drop the third font and the dead View-Transitions/`--glow` code.
7. **Consider collapsing the backtest's duplicated strategy/edge controls** — the highest-leverage cognitive-load win, pending the workflow answer above.

**What to protect:** the thermal ramp semantics, the sign+color redundancy in the money formatters, the empty-state/kill-banner honesty, and reduced-motion support. Those are the parts that make this feel built, not generated.

---

## Recommended next commands (run any order; I can run these for you)
1. `/impeccable harden dashboard/static/app.js` — stateful live updates + freshness thresholding (P1 ×2).
2. `/impeccable audit dashboard/static` — a11y sweep: contrast, `aria-live`, SVG alternatives, focus (P1-contrast + persona Sam).
3. `/impeccable adapt dashboard/static` — per-city grid + bracket-ladder mobile overflow (P2 ×2).
4. `/impeccable colorize dashboard/static/css/tokens.css` — Sharpe off the heat ramp; ink-floor lift (P3 + P1-contrast).
5. `/impeccable distill` on the backtest controls — collapse duplicated strategy/edge selectors (cognitive load), *after* confirming the workflow.

Re-run `/impeccable critique` after fixes to watch 30/40 climb.
