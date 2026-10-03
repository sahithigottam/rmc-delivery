"""Configuration for Routing Microservice"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings - loads from environment variables"""
    
    # API Configuration
    API_TITLE: str = "RMC Routing Microservice"
    API_VERSION: str = "1.0.0"
    API_V1_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"
    
    # Database
    # For local: sqlite:///./rmc_routing.db
    # For cloud: provide full PostgreSQL URL or it will use in-memory SQLite
    DATABASE_URL: str = "sqlite:///:memory:"
    
    # Google Maps API
    GOOGLE_MAPS_API_KEY: str = ""
    
    # Rate limiting
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
