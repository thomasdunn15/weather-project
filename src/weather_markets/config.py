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

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()