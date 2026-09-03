from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env file."""

    database_url: str
    nyc_latitude: float = 40.7794
    nyc_longitude: float = - 73.9692
    nyc_station_id: str = "KNYC"
    data_dir: Path = Path.home() / "data" / "gefs"
    log_level: str = "INFO"

    # Kalshi API. kalshi_key_path points to an RSA private key (.pem). Demo
    # base url by default so smoke tests can't move real money. Switch to
    # https://api.elections.kalshi.com/trade-api/v2 once Phase 3 passes.
    kalshi_key_id: str | None = None
    kalshi_key_path: Path | None = None
    kalshi_api_base: str = "https://demo-api.kalshi.co/trade-api/v2"

    # Polymarket US API (polymarket.us, operated by QCX LLC, CFTC-regulated).
    # Auth: Ed25519 signing per docs.polymarket.us/api-reference/authentication.
    polymarket_key_id: str | None = None
    polymarket_secret: str | None = None  # base64-encoded Ed25519 private key

    # polymarketdata.co (3rd-party historical data — only covers international
    # Polymarket, NOT Polymarket US weather contracts. Kept for completeness.)
    polymarketdata_api_key: str | None = None

    # IBKR Client Portal Web API — ForecastEx execution only (market data comes
    # from forecastex.com, which needs no auth). Default points at the local
    # Client Portal Gateway; hosted OAuth would be https://api.ibkr.com/v1/api.
    ibkr_api_base: str = "https://localhost:5000/v1/api"
    ibkr_account_id: str | None = None

    # Claude API (reasoning engine). Falls back to ANTHROPIC_API_KEY env if unset.
    anthropic_api_key: str | None = None

    # Claude Code CLI (subscription backend for human-triggered research).
    # Generate with `claude setup-token`. Falls back to the process env.
    claude_code_oauth_token: str | None = None

    # Dashboard login — single operator, see dashboard/auth.py. All three must be
    # set or the dashboard refuses every request (fails closed). The hash comes
    # from `uv run python -m dashboard.auth hash`, the secret from `... secret`.
    dashboard_user: str | None = None
    dashboard_password_hash: str | None = None   # scrypt$<salt>$<hash>
    dashboard_secret: str | None = None          # HMAC key for the session cookie

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()