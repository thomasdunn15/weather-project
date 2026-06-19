# ClipCurator — Frontend Architecture & Stack Reference

> Context document for refactoring another project's frontend to match this setup.

## 0. TL;DR — what this frontend actually is

This is **not** a Node/React/Vite/Next SPA. There is **no `package.json`, no `node_modules`, no
build step, no bundler, no transpiler, and no framework**. It is a deliberately minimal,
**zero-dependency vanilla frontend**:

- **3 static files**: `index.html`, `style.css`, `app.js`
- Served verbatim by a **FastAPI** backend (`dashboard/app.py`) via `StaticFiles`
- Plain ES2020+ JavaScript (`"use strict"`), no modules/imports, no JSX
- Hand-written CSS using native CSS custom properties (variables) — no Tailwind/Sass/CSS-in-JS
- Fonts loaded from Google Fonts CDN; everything else is local

**Implication for a refactor target:** if the goal is to *match* this setup, the target should be
stripped down to a no-build, framework-free static frontend backed by a Python (FastAPI) JSON API.
If the goal is to *modernize* this into a framework, treat this document as the spec of behavior to
reproduce. Both readings are supported below.

---

## 1. Project Structure

The frontend lives entirely under `dashboard/`. Full tree (frontend-relevant paths only):

```
/opt/clipcurator/
├── dashboard/
│   ├── app.py                  # FastAPI backend: serves the frontend + JSON API
│   └── static/                 # the entire frontend — served at /static/*
│       ├── index.html          # single HTML page (the whole UI shell)
│       ├── style.css           # all styling (≈420 lines, hand-written)
│       └── app.js              # all behavior (≈427 lines, vanilla JS)
├── config.py                   # paths + scoring weights (backend reads these, API exposes some)
├── main.py                     # pipeline entrypoint (launched by the dashboard "hunt" feature)
├── data/                       # runtime data the frontend renders (not in git)
│   ├── report.json             # pipeline output → GET /api/clips
│   ├── state.json              # per-clip watched/favorite → POST /api/state/{id}
│   ├── seen.json               # dedupe ledger
│   └── kept/                   # video files + posters/, served at /videos/*
└── deploy/                     # systemd units + nginx reverse-proxy config
```

- **Source dir:** `dashboard/static/` (also the served/"public" dir — source == deploy artifact)
- **Build dir:** none (no build)
- **Public/static dir:** `dashboard/static/` mounted at `/static`; media at `/videos`
- **Test dir:** none (no frontend tests exist)
- **Monorepo:** no — single app, single backend, no workspaces

---

## 2. Technology Stack

| Concern | Choice |
|---|---|
| Framework | **None** (vanilla JS) |
| Language | JavaScript (ES2020+), strict mode; **no TypeScript** |
| Build tool | **None** (no Vite/Webpack/Rollup/esbuild) |
| Package manager | **None** for frontend (no `package.json`); Python uses `pip` + `venv` |
| Module system | Classic scripts (single `<script src>` global scope) — no ESM, no `import` |
| HTTP client | Native `fetch()` |
| Backend serving it | **FastAPI** + **uvicorn** (ASGI), Python 3.12 |
| CSS | Hand-written CSS with native custom properties |
| Fonts | Google Fonts CDN (Bricolage Grotesque, IBM Plex Sans, IBM Plex Mono) |
| Node version | N/A (no Node in the project) |

**Backend dependencies relevant to the frontend** (from `requirements.txt` / `dashboard/app.py`):
`fastapi`, `uvicorn`, `pydantic`. These provide the JSON API and static file serving the
frontend depends on.

**Cache-busting** is manual via query strings, bumped by hand on each release:
```html
<link rel="stylesheet" href="/static/style.css?v=8">
<script src="/static/app.js?v=8"></script>
```

---

## 3. Architecture & Code Organization

### Overall pattern
A **single-page, single-file** app. `index.html` defines the entire DOM shell (masthead, filter
controls, an empty `<section class="grid">`, an empty modal). `app.js` fetches data, renders cards
into the grid via `innerHTML` template strings, and wires up all event listeners imperatively.
State lives in **module-level globals**, not a store.

### "Component" structure & naming
There are no components in the framework sense. The equivalent units are **render functions** that
return DOM nodes or HTML strings:

- `card(c)` — builds one clip `<article class="card">` (creates element, sets `innerHTML`, attaches listeners). `app.js:116`
- `openModal(c)` — builds the detail modal body. `app.js:332`
- `renderStats(visible)` — builds the masthead stat chips. `app.js:90`
- `renderColophon()` — footer line. `app.js:196`
- `buildShowFilter()` — populates the "Show" `<select>`. `app.js:45`
- `render()` — top-level: read filters → filter/sort → repaint grid. `app.js:186`

Naming conventions: lowercase function names; CSS classes are kebab-case BEM-ish
(`.card`, `.card-body`, `.card-title`, `.dial-wrap`, `.hunt-form`, `.modal-grid`).

### "Routing"
No router and no routes — it is one screen. The only navigation is a **modal** (open/close via
`hidden` attribute + `document.body.style.overflow`). Element IDs are the addressing scheme
(`$("#grid")`, `$("#modal")`, etc.).

### State management
No library. State is plain globals in `app.js`:
```js
let CLIPS = [];   // the clip array from /api/clips (source of truth, mutated in place)
let META  = {};   // generated_at, last_run, etc.
let SCORING = {…} // scoring weights/penalties, used to render the score breakdown
```
Mutations: `toggleState()` flips `c.watched`/`c.favorite` on the in-memory object, calls
`render()` immediately (optimistic update), then POSTs; on failure it reverts and re-renders
(`app.js:170`). Filter/sort "state" is **read directly from the DOM** each render via
`currentFilters()` (`app.js:55`) rather than stored.

### Service / API layer
There is no abstraction layer — `fetch()` is called inline at each call site. Endpoints consumed
(all same-origin, JSON):

| Method & path | Purpose | Call site |
|---|---|---|
| `GET /api/clips` | list clips + scoring config + run meta | `load()` `app.js:34` |
| `POST /api/state/{clip_id}` | set `watched`/`favorite` | `toggleState()` `app.js:170` |
| `DELETE /api/clips/{clip_id}` | delete a clip (file + state) | modal delete handler `app.js:399` |
| `GET /api/run/defaults` | prefill the hunt form from config | `prefillHuntForm()` `app.js:242` |
| `POST /api/run` | launch a pipeline run | hunt form submit `app.js:267` |
| `GET /api/run/status` | poll run progress (2.5s interval) | `pollRunStatus()` `app.js:291` |

Media: `<video src="/videos/...">` served by FastAPI `StaticFiles` (supports HTTP Range, so
seeking works — see `dashboard/app.py:223`).

### Hooks
N/A — no React, so no hooks. The DOM-lifecycle equivalents are imperative
`addEventListener` calls and a `setInterval` poll loop.

---

## 4. Styling System

- **Approach:** a single hand-written global stylesheet, `dashboard/static/style.css`. No
  preprocessor, no utility framework, no CSS-in-JS, no CSS Modules.
- **Design tokens:** native CSS custom properties declared on `:root` (`style.css:4`):
  ```css
  :root {
    --bg:#0f1218; --surface:#161b24; --surface-2:#1c2230; --line:#262d3b;
    --ink:#ede7da; --ink-dim:#9aa2b1; --ink-faint:#6b7383;
    --dial:#f0b441;            /* marigold accent — the score dial */
    --teal:#67b8a6; --rose:#e0697e;
    --radius:14px;
    --font-display:"Bricolage Grotesque", system-ui, sans-serif;
    --font-body:"IBM Plex Sans", system-ui, sans-serif;
    --font-mono:"IBM Plex Mono", ui-monospace, monospace;
  }
  ```
- **Theme / dark mode:** dark-only by design. `html { color-scheme: dark; }` (`style.css:24`). No
  light theme and no theme toggle.
- **Layout:** CSS Grid for the card grid (`grid-template-columns: repeat(auto-fill, minmax(300px,1fr))`),
  Flexbox for masthead/controls/actions.
- **Responsive:** mobile-first refinements via `@media (max-width:720px)` blocks, iPhone-tuned
  (16px inputs to defeat iOS auto-zoom, `env(safe-area-inset-*)` padding, per-clip aspect ratios
  set inline via a `--ar` custom property to avoid letterboxing). Also honors
  `@media (prefers-reduced-motion: reduce)`.
- **Notable techniques:** `conic-gradient` + `radial-gradient` to draw the circular score "dial"
  (`.dial-wrap`, `style.css:138`), `backdrop-filter: blur()` on the sticky masthead and modal
  backdrop, `color-mix()` for the translucent masthead background.
- **Config files:** none — there is no `tailwind.config.js`/`postcss.config.js` because there is
  no CSS toolchain.

---

## 5. Development & Build Setup

### Dev server / run command
There is no frontend dev server. The FastAPI backend serves the static files directly:
```bash
uvicorn dashboard.app:app --host 127.0.0.1 --port 8000      # local dev
```
(from `dashboard/app.py` docstring, line 10). Editing `index.html`/`style.css`/`app.js` and
reloading the browser is the entire dev loop — bump the `?v=` query string to bust cache.

### Build process
None. The files shipped to production are byte-for-byte the source files. "Deploying" = the files
already being on the box at `/opt/clipcurator/dashboard/static/`.

### Environment variables
The frontend reads **no** env vars (it has no build step to inject them). All config the UI needs
is delivered at runtime through the API (`GET /api/clips` returns `scoring`; `GET /api/run/defaults`
returns form defaults). Backend env lives in `/opt/clipcurator/.env` (`.env.example` present),
loaded by systemd's `EnvironmentFile=` — not exposed to the browser.

### Production deployment (`deploy/`)
- `clipcurator-dashboard.service` — systemd unit running uvicorn bound to `127.0.0.1:8000`.
- `nginx-clipcurator.conf` — nginx reverse proxy on :80 with HTTP Basic Auth (or IP allowlist),
  `proxy_buffering off` so video playback/seeking starts immediately.
- `clipcurator-pipeline.{service,timer}` — systemd timer running the curation pipeline twice daily
  (the same pipeline the dashboard's "Look for clips" button launches on demand).

### Scripts
No `package.json` scripts. Operational commands are the systemd units above plus the uvicorn
command. There is nothing to `npm run`.

---

## 6. Testing & Quality

- **Testing framework:** none for the frontend (no Jest/Vitest/Testing Library/Playwright, no test
  files). Backend has no test suite checked in either.
- **Linting/formatting:** no ESLint/Prettier config in the repo. Code style is hand-maintained and
  consistent: 2-space indent, double quotes, `"use strict"`, terminal semicolons, small pure
  helpers. Python side shows `# noqa` hints implying a flake8/ruff-style linter is used for backend
  but no config file is committed.
- **Pre-commit hooks / CI:** none present in the repo.

> For a refactor that must "match," the honest baseline here is **no automated frontend quality
> gate**. If the target project already has ESLint/Prettier/tests, matching this project means you
> would be *removing* them — only do that if minimalism is the explicit goal; otherwise treat this
> section as a gap to improve rather than replicate.

---

## 7. Key Code Patterns

### Data fetching
Native `fetch` + `await res.json()`, called inline. Canonical load (`app.js:34`):
```js
async function load() {
  const res = await fetch("/api/clips");
  const data = await res.json();
  CLIPS = data.clips;
  META = data;
  SCORING = data.scoring || SCORING;
  buildShowFilter();
  render();
  renderColophon();
}
```

### Optimistic mutation with rollback (`app.js:170`)
```js
async function toggleState(c, field, value) {
  const next = value !== undefined ? value : !c[field];
  c[field] = next;
  render();                                   // update UI immediately
  try {
    await fetch(`/api/state/${encodeURIComponent(c.id)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [field]: next }),
    });
  } catch {
    c[field] = !next;                         // revert on failure
    render();
  }
}
```

### Polling for long-running jobs (`app.js:291`)
`setInterval(tick, 2500)` polls `GET /api/run/status`, streams the log tail into a `<pre>`,
auto-scrolls only if the user is at the bottom, swaps a spinner→done state, and calls `load()` to
refresh the grid when the run finishes.

### Form handling
Plain `<form>` + `submit` listener with `e.preventDefault()`; values pulled from inputs by id and
coerced (`num()` helper turns empty strings into `null`). No form library, no controlled inputs —
the DOM is the form state. Submit handler at `app.js:255`.

### Rendering
Build HTML as template strings → assign `el.innerHTML` → `grid.replaceChildren(...nodes)`
(`app.js:192`). **All interpolated user/data strings go through an `esc()` HTML-escaper**
(`app.js:113`) — this is the project's XSS defense in lieu of a framework's auto-escaping. Match
this discipline if porting: every `${...}` inside an HTML string is wrapped in `esc(...)`.

### Error handling & notifications
No toast/notification library. Errors are surfaced inline: failed run-start writes a message into
`#hunt-status-text` and distinguishes `409` (run already in progress) from other failures
(`app.js:272`). Destructive delete uses a native `confirm()` (`app.js:398`). Network failures in
`toggleState` silently roll back.

### Auth
No app-level auth in the frontend. Access control is entirely **nginx HTTP Basic Auth** in front of
the localhost-bound uvicorn (see `deploy/nginx-clipcurator.conf`). The browser app assumes it is
already behind that gate.

### Utility helpers (`app.js:1–32, 111–114`)
- `$ = (sel) => document.querySelector(sel)` — the only DOM selector helper
- `fmt` object: `likes` (K/M abbreviation), `duration` (`m:ss`), `ago` (relative days),
  `watchTime` (`Hh Mm`)
- `esc()` HTML-escaper, `short()` (strips trailing "clips"), `srcName()` (YouTube vs TikTok from URL)

---

## 8. Configuration Files

There are **no** standard frontend config files in this project. For completeness, here is the
status of each item the brief asked about:

| File | Present? | Notes |
|---|---|---|
| `package.json` | ❌ | No Node/npm in the project |
| `tsconfig.json` | ❌ | No TypeScript |
| `vite.config.*` / `webpack.config.*` / `next.config.*` | ❌ | No bundler/framework |
| `tailwind.config.js` / `postcss.config.js` | ❌ | Hand-written CSS, no toolchain |
| `.eslintrc` / `.prettierrc` | ❌ | No committed lint/format config |
| `.env` / `.env.example` | ✅ (backend only) | `/opt/clipcurator/.env`, loaded by systemd; never reaches the browser |

**The closest things to "frontend config"** are:
- `config.py` — backend constants. The API surfaces a subset to the UI: scoring
  `WEIGHT_LIKES/RECENCY/RESOLUTION`, `PENALTY_KISSING/EDIT_EFFECTS`, `MAX_AGE_DAYS`, and the hunt
  defaults (`KEYWORDS`, `MIN_LIKES`, `MIN_DURATION_S`, `MAX_DURATION_S`, `MAX_CANDIDATES_PER_KEYWORD`).
  Path constants (`KEPT_DIR`, `REPORT_PATH`, `STATE_PATH`, `DATA_DIR`) define where served media and
  rendered JSON live (`config.py:16–24`).
- `dashboard/app.py` — the static mounts and route table that define the frontend's runtime contract:
  ```python
  app.mount("/videos", StaticFiles(directory=config.KEPT_DIR), name="videos")
  app.mount("/static", StaticFiles(directory=STATIC_DIR),      name="static")
  @app.get("/")           # returns dashboard/static/index.html
  ```

---

## 9. Reproducing this architecture in another project

To make a target frontend *match* ClipCurator:

1. **Delete the build pipeline.** No bundler, no `package.json`, no TS. Three files:
   `index.html` (DOM shell), `style.css` (one global sheet with `:root` tokens), `app.js`
   (`"use strict"`, classic script).
2. **Back it with a FastAPI app** that (a) `mount`s the static dir, (b) serves `index.html` at `/`,
   (c) exposes a small JSON API, and (d) `mount`s a media dir via `StaticFiles` for Range-capable
   video.
3. **State = module globals + DOM.** Read filter state from inputs each render; keep the data array
   as the single mutable source of truth; re-render by rebuilding `innerHTML` and
   `replaceChildren`.
4. **Always wrap interpolated data in an `esc()` escaper** — this is the only XSS protection.
5. **Optimistic updates** with try/catch rollback for state mutations; **`setInterval` polling**
   for long jobs with a log-tail `<pre>`.
6. **Design tokens via CSS custom properties** on `:root`; dark-only (`color-scheme: dark`);
   responsive via a single `@media (max-width:720px)` block with iOS-specific tweaks
   (16px inputs, `env(safe-area-inset-*)`, per-item `--ar` aspect ratios).
7. **Manual cache-busting** with `?v=N` query strings on the CSS/JS links.
8. **Deploy** as uvicorn-on-localhost behind nginx (Basic Auth + `proxy_buffering off` for media),
   managed by systemd.
