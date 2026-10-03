"""API routes endpoints for Routing Microservice"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from schemas import RouteCreate, RouteResponse, RerouteRequest, RerouteResponse, ErrorResponse
from route_service import RouteService, get_route_cache_stats
from google_maps import GoogleMapsService
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/routes", tags=["routes"])


def get_route_service(db: Session = Depends(get_db)) -> RouteService:
    """Dependency to get RouteService"""
    google_maps = GoogleMapsService()
    return RouteService(db, google_maps)


@router.post(
    "/estimate",
    response_model=RouteResponse,
    responses={
        400: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def estimate_route(
    route_request: RouteCreate,
    route_service: RouteService = Depends(get_route_service),
) -> RouteResponse:
    """
    Feature 1: Route Calculation
    
    Estimate the shortest/fastest route between two street addresses with real-time traffic data.
    
    ### Request Parameters (Minimal - Only start and end required):
    - **start**: Starting location (street address or location name)
    - **end**: Destination (street address or location name)
    - **vehicle_type**: Type of vehicle (default: "rmc_truck" - RMC Heavy Truck)
    - **vehicle_id**: Optional vehicle identifier
    - **load_weight**: Optional load weight in kg
    - **load_volume**: Optional load volume in m³
    - **departure_datetime**: Optional departure time (ISO format, for traffic calculation)
    - **priority**: Route priority - "normal", "urgent", or "economy" (default: "normal")
    - **max_delivery_minutes**: Maximum delivery time in minutes
    - **avoid**: Features to avoid: ["tolls", "highways", "ferries"]
    
    ### Response:
    Returns route details including:
    - Resolved start and end addresses (geocoded from input)
    - Distance in meters
    - Estimated duration in seconds
    - Traffic delay in seconds (if applicable)
    - Polyline for map visualization
    - Step-by-step instructions
    - Route ID for future reference
    """
    try:
        logger.info(
            f"Route estimate request: {route_request.start.address} "
            f"to {route_request.end.address}"
        )

        result = await route_service.estimate_route(route_request)
        return result

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to calculate route. Please try again later.",
        )


@router.get(
    "/{route_id}",
    response_model=RouteResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_route(
    route_id: int,
    route_service: RouteService = Depends(get_route_service),
) -> RouteResponse:
    """
    Retrieve a previously calculated route by ID.
    
    ### Parameters:
    - **route_id**: The ID of the route to retrieve
    
    ### Response:
    Returns the full route details including all calculations and steps.
    """
    try:
        result = route_service.get_route(route_id)
        if not result:
            raise HTTPException(status_code=404, detail=f"Route {route_id} not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving route: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve route")


@router.get(
    "",
    response_model=list[RouteResponse],
)
async def get_route_history(
    vehicle_id: Optional[str] = Query(None, description="Filter by vehicle ID"),
    limit: int = Query(10, ge=1, le=100, description="Maximum number of routes"),
    route_service: RouteService = Depends(get_route_service),
) -> list[RouteResponse]:
    """
    Retrieve route history.
    
    ### Parameters:
    - **vehicle_id**: Optional filter by specific vehicle
    - **limit**: Maximum number of routes to return (default 10, max 100)
    
    ### Response:
    Returns list of previously calculated routes, sorted by creation date (newest first).
    """
    try:
        results = route_service.get_route_history(
            vehicle_id=vehicle_id, limit=limit
        )
        return results
    except Exception as e:
        logger.error(f"Error retrieving route history: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve route history")


@router.post(
    "/reroute",
    response_model=RerouteResponse,
    responses={
        400: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def check_reroute(
    reroute_request: RerouteRequest,
    original_duration: Optional[float] = Query(None, description="Original trip duration in seconds"),
    route_service: RouteService = Depends(get_route_service),
) -> RerouteResponse:
    """
    Check if a reroute is recommended from the truck's current position.

    Accepts lat/lng coordinates directly (no geocoding of start position).
    Returns fresh directions with a `reroute_recommended` flag and reason.
    Does NOT save to DB — this is a lightweight traffic probe.

    ### Example Request:
    ```json
    {
      "current_lat": -36.848,
      "current_lng": 174.762,
      "end": {"address": "Hamilton City"},
      "vehicle_type": "rmc_truck",
      "priority": "normal"
    }
    ```
    
    ### Response:
    - **reroute_recommended**: True if new route significantly differs from original
    - **reason**: Explanation of recommendation (if applicable)
    - **distance_meters**: New route distance
    - **duration_seconds**: Estimated duration from current position to destination
    """
    try:
        result = await route_service.check_reroute(
            current_lat=reroute_request.current_lat,
            current_lng=reroute_request.current_lng,
            end_address=reroute_request.end.address,
            vehicle_type=reroute_request.vehicle_type,
            priority=reroute_request.priority,
            avoid=reroute_request.avoid,
            original_duration=original_duration,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Reroute check error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to check reroute. Please try again later.",
        )


@router.get("/stats/cache")
def get_route_cache_stats_endpoint():
    """Get route caching statistics"""
    return get_route_cache_stats()
