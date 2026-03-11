"""FastAPI dependencies"""
from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import GoogleMapsService, RouteService


async def get_google_maps_client() -> GoogleMapsService:
    """Dependency for Google Maps client"""
    return GoogleMapsService()


def get_route_service(
    db: Session = Depends(get_db),
    google_maps: GoogleMapsService = Depends(get_google_maps_client),
) -> RouteService:
    """Dependency for Route service"""
    return RouteService(db, google_maps)
