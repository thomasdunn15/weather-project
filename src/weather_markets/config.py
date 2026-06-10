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

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()