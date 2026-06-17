"""Pre-build the dashboard's React frontends.

Why this exists (lessons from the 2026-06-16 outage):
  - The old build loaded React + Babel from a CDN (unpkg) at render time, so
    the dashboard went blank whenever the browser couldn't reach the CDN
    (campus network / outage).
  - Vendoring a 3MB babel.min.js into the declared-component dir made Streamlit
    serve 3MB through the port-forward → "trouble loading component frontend
    assets" timeout.
  - Transpiling JSX with py_mini_racer (V8) at RENDER time runs V8 inside
    Streamlit's worker thread, which could crash the whole process on connect.

So: do ALL Babel/V8 work HERE, once, in a standalone process (main thread,
safe), and produce static artifacts the renderer just reads. The browser gets
inline React + already-compiled JS — no CDN, no Babel, no sub-asset fetches,
and no V8 in Streamlit.

Outputs:
  1. assets/backtest_component/index.html  — self-contained (inline React +
     compiled app); source of truth is backtest_component/app.jsx.
  2. assets/live_dashboard/live_app.compiled.js — the live tab app, transpiled;
     source of truth is components.jsx + live-tab.jsx + the app shell in
     live_dashboard_renderer.live_jsx_bundle().

Run after editing any dashboard .jsx / app.jsx:
    uv run python scripts/build_dashboard_components.py
"""
import json
import re
import sys
import types
from pathlib import Path

SCRIPTS = Path(__file__).parent
ASSETS = SCRIPTS / "assets"
VENDOR = ASSETS / "vendor"
BACKTEST = ASSETS / "backtest_component"
LIVE = ASSETS / "live_dashboard"

LIBS_START, LIBS_END = "<!--LIBS:START-->", "<!--LIBS:END-->"
APP_START, APP_END = "<!--APP:START-->", "<!--APP:END-->"


def transpile(jsx: str) -> str:
    """JSX → plain JS via the vendored Babel in V8. Runs in this standalone
    process's main thread (safe), never in Streamlit's render thread.

    Uses ONLY the React preset with the CLASSIC runtime:
      - classic runtime compiles JSX to React.createElement using the global
        `React` we inline — it does NOT emit `import {jsx} from "react/jsx-
        runtime"`. The automatic runtime's import statement, loaded as a plain
        <script>, throws "Cannot use import statement outside a module" (the
        2026-06-17 blank dashboard).
      - preset-env is intentionally omitted: it down-levels modern syntax
        (e.g. for...of) into helper functions/imports the plain script can't
        resolve. The dashboard targets a current browser, so JSX is the only
        transform actually needed.
    """
    from py_mini_racer import MiniRacer
    ctx = MiniRacer()
    ctx.eval((VENDOR / "babel.min.js").read_text())
    ctx.eval("globalThis.__s = " + json.dumps(jsx))
    out = ctx.eval(
        "Babel.transform(globalThis.__s, "
        "{presets: [['react', {runtime: 'classic'}]]}).code"
    )
    if not out:
        raise RuntimeError("Babel produced empty output")
    if "import " in out or "\nimport(" in out:
        raise RuntimeError("compiled output still contains an import statement")
    return out


def build_backtest() -> None:
    """Generate the self-contained backtest index.html from app.jsx + vendored
    React. Marker regions <!--LIBS--> / <!--APP--> make this idempotent."""
    index = BACKTEST / "index.html"
    app_jsx = BACKTEST / "app.jsx"
    idx = index.read_text()

    if not app_jsx.exists():
        m = re.search(r'<script type="text/babel"[^>]*>(.*?)</script>', idx, re.S)
        if not m:
            raise SystemExit("backtest: no app.jsx and no inline JSX block to extract")
        app_jsx.write_text(m.group(1).strip() + "\n")
        print(f"  extracted JSX -> {app_jsx}")

    if APP_START not in idx:
        idx = re.sub(
            r'<script[^>]*src="[^"]*react\.production[^"]*"></script>\s*'
            r'<script[^>]*src="[^"]*react-dom\.production[^"]*"></script>\s*'
            r'<script[^>]*src="[^"]*babel(?:\.min)?\.js"></script>',
            LIBS_START + LIBS_END, idx, flags=re.S)
        idx = re.sub(r'<script type="text/babel"[^>]*>.*?</script>',
                     APP_START + APP_END, idx, flags=re.S)
        if LIBS_START not in idx or APP_START not in idx:
            raise SystemExit("backtest: could not insert build markers")

    react = (VENDOR / "react.production.min.js").read_text()
    react_dom = (VENDOR / "react-dom.production.min.js").read_text()
    compiled = transpile(app_jsx.read_text())

    libs = (f"{LIBS_START}\n<!-- React + ReactDOM inlined (no CDN, no sub-fetch) -->\n"
            f"<script>{react}</script>\n<script>{react_dom}</script>\n{LIBS_END}")
    app = (f"{APP_START}\n<!-- pre-transpiled from app.jsx -->\n"
           f"<script>\n{compiled}\n</script>\n{APP_END}")
    idx = re.sub(re.escape(LIBS_START) + r".*?" + re.escape(LIBS_END), lambda _m: libs, idx, flags=re.S)
    idx = re.sub(re.escape(APP_START) + r".*?" + re.escape(APP_END), lambda _m: app, idx, flags=re.S)

    index.write_text(idx)
    assert 'src="https://unpkg' not in idx and 'src="./vendor/' not in idx
    assert 'type="text/babel"' not in idx and "@license React" in idx
    print(f"  backtest index.html: {len(idx)} bytes, compiled {len(compiled)} bytes (self-contained)")


def build_live() -> None:
    """Transpile the live-tab JSX bundle → live_app.compiled.js."""
    # Stub streamlit so importing the renderer (for live_jsx_bundle) is cheap
    # and side-effect-free in this build context.
    for name, mod in {
        "streamlit": types.ModuleType("streamlit"),
        "streamlit.components": types.ModuleType("streamlit.components"),
        "streamlit.components.v1": types.ModuleType("streamlit.components.v1"),
    }.items():
        sys.modules.setdefault(name, mod)
    sys.modules["streamlit"].components = sys.modules["streamlit.components"]
    sys.modules["streamlit.components"].v1 = sys.modules["streamlit.components.v1"]
    sys.modules["streamlit.components.v1"].html = lambda *a, **k: None
    sys.modules["streamlit"].cache_data = lambda *a, **k: (lambda f: f)
    sys.modules["streamlit"].fragment = lambda *a, **k: (lambda f: f)

    sys.path.insert(0, str(SCRIPTS))
    import live_dashboard_renderer as L
    compiled = transpile(L.live_jsx_bundle())
    out = LIVE / "live_app.compiled.js"
    out.write_text(compiled)
    print(f"  live_app.compiled.js: {len(compiled)} bytes")


def main() -> None:
    print("Building dashboard frontends (no CDN, no browser Babel, no runtime V8)...")
    build_backtest()
    build_live()
    print("Done.")


if __name__ == "__main__":
    main()
