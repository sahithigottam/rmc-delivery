"""Application configuration settings"""
import logging
import json
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings from environment variables or credentials.json"""

    # Environment
    env: str = "development"
    debug: bool = False

    # Database
    database_url: str = "sqlite:///./rmc_delivery.db"
    db_echo: bool = False

    # Google Maps API
    google_maps_api_key: str = ""

    # LLM for risk narratives: ollama (default) | openrouter | gemini. Keys belong in .env only.
    llm_provider: str = "ollama"
    llm_model: str = ""  # empty = provider default
    openrouter_api_key: str = ""
    gemini_api_key: str = ""

    # Cloud Routing Service
    routing_service_url: str = "https://rmc-routing-service-production.up.railway.app"

    # FastAPI
    log_level: str = "INFO"
    slow_request_ms: int = Field(2000, ge=1)
    api_v1_prefix: str = "/api/v1"
    api_title: str = "RMC Delivery Route Optimizer"
    api_version: str = "1.0.0"

    # Clerk authentication. These are public verification settings, not API secrets.
    clerk_jwks_url: str = ""
    clerk_issuer: str = ""
    clerk_authorized_parties: str = ""
    super_admin_user_id: str = ""  # Semicolon-separated verified Clerk user IDs.

    # Rate Limiting
    rate_limit_requests: int = 100
    rate_limit_window: int = 60

    class Config:
        env_file = ".env"
        case_sensitive = False


def load_settings() -> Settings:
    """Load settings, using credentials.json only to fill missing values."""
    settings = Settings()

    # Try to load from credentials.json if it exists.
    # Environment variables stay authoritative for deploy targets like Cloud Run.
    credentials_file = Path(__file__).parent.parent / "config" / "credentials.json"

    if credentials_file.exists():
        try:
            with open(credentials_file, "r") as f:
                creds = json.load(f)

            # Load debug setting only if it was not set explicitly via env.
            if "debug" in creds and "DEBUG" not in settings.model_fields_set:
                settings.debug = creds.get("debug", False)
                logger.info(f"Debug mode: {settings.debug}")

            # Load Google Maps API key from credentials.json only if env left it empty.
            google_key = creds.get("google_maps", {}).get("api_key")
            if (
                not settings.google_maps_api_key
                and google_key
                and google_key != "YOUR_GOOGLE_MAPS_API_KEY_HERE"
            ):
                settings.google_maps_api_key = google_key
                logger.info("Google Maps API key loaded from config/credentials.json")

            # Load database URL from credentials.json only if env left the default in place.
            db_config = creds.get("database", {})
            if db_config and settings.database_url == Settings.model_fields["database_url"].default:
                db_type = db_config.get("type", "sqlite")
                
                if db_type == "sqlite":
                    # SQLite database
                    db_path = db_config.get("path", "./rmc_delivery.db")
                    db_url = f"sqlite:///{db_path}"
                else:
                    # PostgreSQL database
                    username = db_config.get("username", "user")
                    password = db_config.get("password", "password")
                    host = db_config.get("host", "localhost")
                    port = db_config.get("port", 5432)
                    database = db_config.get("database", "rmc_delivery")
                    db_url = f"postgresql://{username}:{password}@{host}:{port}/{database}"
                
                settings.database_url = db_url
                logger.info("Database configured: %s", db_type)

        except Exception as e:
            logger.warning("Could not load credentials configuration (%s)", type(e).__name__)
            logger.info("Falling back to environment variables")

    return settings


# Global settings instance
settings = load_settings()
