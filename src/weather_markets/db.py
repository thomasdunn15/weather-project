from weather_markets.config import settings
import psycopg

def get_connection():
    """Open a connection to the Postgres database."""
    return psycopg.connect(settings.database_url)