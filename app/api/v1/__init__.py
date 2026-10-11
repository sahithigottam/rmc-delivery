"""API v1 endpoints"""
from fastapi import APIRouter, Depends

from app.auth import get_current_principal
from app.api.v1.endpoints import auth, catalogue, geography, job_sites, plants, predictions, routes, trips

api_router = APIRouter(dependencies=[Depends(get_current_principal)])
api_router.include_router(auth.router)
api_router.include_router(plants.router)
api_router.include_router(catalogue.router)
api_router.include_router(geography.router)
api_router.include_router(job_sites.router)
api_router.include_router(routes.router)
api_router.include_router(trips.router)
api_router.include_router(predictions.router)

__all__ = ["api_router"]
