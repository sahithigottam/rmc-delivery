"""API v1 routes endpoints - Feature 1: Route Calculation"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_route_service
from app.schemas import RouteCreate, RouteResponse, ErrorResponse
from app.services.route import RouteService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/routes", tags=["routes"])


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
    
    ### Response:
    Returns route details including:
    - Resolved start and end addresses (geocoded from input)
    - Distance in meters
    - Estimated duration in seconds
    - Traffic delay in seconds (if applicable)
    - Polyline for map visualization
    - Step-by-step instructions
    - Route ID for future reference
    
    ### Example Request (Minimal):
    ```json
    {
      "start": {"address": "Queen Street, Auckland"},
      "end": {"address": "Hamilton City"}
    }
    ```
    
    ### Example Request (Full):
    ```json
    {
      "start": {"address": "Queen Street, Auckland"},
      "end": {"address": "Hamilton City"},
      "vehicle_type": "rmc_truck",
      "vehicle_id": "RMC-001",
      "load_weight": 8000,
      "load_volume": 10,
      "departure_datetime": "2026-03-12T14:30:00",
      "priority": "normal"
    }
    ```
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
