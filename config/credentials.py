"""Credentials management module"""
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class CredentialsManager:
    """Load and manage API credentials from credentials.json file"""

    CREDENTIALS_FILE = Path(__file__).parent / "credentials.json"
    CREDENTIALS_EXAMPLE = Path(__file__).parent / "credentials.example.json"

    def __init__(self, credentials_path: Optional[Path] = None):
        """Initialize credentials manager"""
        self.credentials_path = credentials_path or self.CREDENTIALS_FILE
        self._credentials: Optional[Dict[str, Any]] = None

    def load_credentials(self) -> Dict[str, Any]:
        """Load credentials from JSON file"""
        if self._credentials:
            return self._credentials

        try:
            if not self.credentials_path.exists():
                raise FileNotFoundError(
                    f"Credentials file not found at {self.credentials_path}. "
                    f"Please copy {self.CREDENTIALS_EXAMPLE} to {self.credentials_path} "
                    f"and fill in your API keys."
                )

            with open(self.credentials_path, "r") as f:
                self._credentials = json.load(f)
                logger.info(f"Credentials loaded from {self.credentials_path}")
                return self._credentials

        except FileNotFoundError as e:
            logger.error(str(e))
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in credentials file: {e}")
            raise
        except Exception as e:
            logger.error(f"Error loading credentials: {e}")
            raise

    def get_google_api_key(self) -> str:
        """Get Google Maps API key"""
        creds = self.load_credentials()
        api_key = creds.get("google_maps", {}).get("api_key")

        if not api_key or api_key == "YOUR_GOOGLE_MAPS_API_KEY_HERE":
            raise ValueError(
                "Google Maps API key not configured. "
                "Please update config/credentials.json with your API key."
            )

        return api_key

    def get_database_url(self) -> str:
        """Construct database URL from credentials"""
        creds = self.load_credentials()
        db = creds.get("database", {})

        db_type = db.get("type", "sqlite")

        if db_type == "sqlite":
            path = db.get("path", "./rmc_delivery.db")
            return f"sqlite:///{path}"
        else:
            # PostgreSQL
            username = db.get("username", "user")
            password = db.get("password", "password")
            host = db.get("host", "localhost")
            port = db.get("port", 5432)
            database = db.get("database", "rmc_delivery")
            return f"postgresql://{username}:{password}@{host}:{port}/{database}"

    def get_google_config(self) -> Dict[str, Any]:
        """Get Google Maps configuration"""
        creds = self.load_credentials()
        return creds.get("google_maps", {})


# Global credentials manager instance
_credentials_manager = None


def get_credentials_manager() -> CredentialsManager:
    """Get or create credentials manager singleton"""
    global _credentials_manager
    if _credentials_manager is None:
        _credentials_manager = CredentialsManager()
    return _credentials_manager
