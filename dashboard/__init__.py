"""Vanilla-JS + FastAPI dashboard for weather-project.

Replaces the former Streamlit app (scripts/dashboard.py). The FastAPI backend
(app.py) serves a zero-build static frontend (static/) plus a small JSON API
backed by the pure data functions in data_live.py / data_backtest.py.

Run:
    uv run uvicorn dashboard.app:app --host 127.0.0.1 --port 8000
"""
