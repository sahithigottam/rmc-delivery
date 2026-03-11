"""Route optimization and calculation service (Feature 1)"""
import logging
from datetime import datetime
from typing import Dict, Optional, List

from sqlalchemy.orm import Session

from app.db.models import Route, TrafficSnapshot
from app.schemas import RouteCreate, RouteResponse, RouteStep, Coordinate, LocationRequest
from app.services.google_maps import GoogleMapsService

logger = logging.getLogger(__name__)


class RouteService:
    """Service for route calculation and optimization"""

    def __init__(self, db: Session, google_maps_client: GoogleMapsService):
        self.db = db
        self.google_maps = google_maps_client

    async def estimate_route(self, route_request: RouteCreate) -> RouteResponse:
        """
        Feature 1: Route Calculation
        Calculate route from street addresses with traffic-aware data from Google Maps API.

        Args:
            route_request: Route calculation request with start/end addresses

        Returns:
            RouteResponse with calculated distance, duration, traffic data
        """
        try:
            # Geocode addresses to coordinates
            logger.info(f"Geocoding start address: {route_request.start.address}")
            start_geo = await self.google_maps.geocode_address(
                route_request.start.address
            )
            
            logger.info(f"Geocoding end address: {route_request.end.address}")
            end_geo = await self.google_maps.geocode_address(
                route_request.end.address
            )

            # Get departure time for traffic calculation
            departure_time = None
            if route_request.departure_datetime:
                departure_time = int(route_request.departure_datetime.timestamp())

            # Call Google Directions API with geocoded coordinates
            directions_data = await self.google_maps.get_directions(
                start_lat=start_geo["latitude"],
                start_lng=start_geo["longitude"],
                end_lat=end_geo["latitude"],
                end_lng=end_geo["longitude"],
                departure_time=departure_time,
                traffic_model="best_guess",
            )

            # Parse response
            if directions_data.get("status") != "OK":
                error_msg = directions_data.get("error_message", "Unknown error")
                logger.error(f"Google Directions API error: {error_msg}")
                raise ValueError(f"Route calculation failed: {error_msg}")

            # Extract route data
            route_data = directions_data["routes"][0]
            leg = route_data["legs"][0]

            distance_meters = leg.get("distance", {}).get("value", 0)
            duration_seconds = leg.get("duration", {}).get("value", 0)
            duration_in_traffic = leg.get("duration_in_traffic", {}).get("value")
            traffic_delay = None

            if duration_in_traffic:
                traffic_delay = duration_in_traffic - duration_seconds

            polyline = route_data.get("overview_polyline", {}).get("points")

            # Parse route steps
            route_steps = []
            for step in leg.get("steps", []):
                route_steps.append(
                    RouteStep(
                        start_location=Coordinate(
                            latitude=step["start_location"]["lat"],
                            longitude=step["start_location"]["lng"],
                        ),
                        end_location=Coordinate(
                            latitude=step["end_location"]["lat"],
                            longitude=step["end_location"]["lng"],
                        ),
                        instruction=step.get("html_instructions", ""),
                        distance_meters=step.get("distance", {}).get("value", 0),
                        duration_seconds=step.get("duration", {}).get("value", 0),
                    )
                )

            # Save to database
            db_route = Route(
                start_address=route_request.start.address,
                start_lat=start_geo["latitude"],
                start_lng=start_geo["longitude"],
                resolved_start_address=start_geo["formatted_address"],
                end_address=route_request.end.address,
                end_lat=end_geo["latitude"],
                end_lng=end_geo["longitude"],
                resolved_end_address=end_geo["formatted_address"],
                vehicle_type=route_request.vehicle_type,
                vehicle_id=route_request.vehicle_id,
                load_weight=route_request.load_weight,
                load_volume=route_request.load_volume,
                departure_datetime=route_request.departure_datetime,
                priority=route_request.priority,
                distance_meters=distance_meters,
                duration_seconds=duration_seconds,
                traffic_delay_seconds=traffic_delay,
                polyline=polyline,
                route_steps=[
                    {
                        "start": {
                            "lat": step.start_location.latitude,
                            "lng": step.start_location.longitude,
                        },
                        "end": {
                            "lat": step.end_location.latitude,
                            "lng": step.end_location.longitude,
                        },
                        "instruction": step.instruction,
                        "distance_meters": step.distance_meters,
                        "duration_seconds": step.duration_seconds,
                    }
                    for step in route_steps
                ],
            )

            self.db.add(db_route)
            self.db.commit()
            self.db.refresh(db_route)

            # Save traffic snapshot
            traffic_snapshot = TrafficSnapshot(
                route_id=db_route.id,
                current_duration_seconds=duration_seconds,
                traffic_condition="normal" if traffic_delay is None else "heavy",
                congestion_level=int((traffic_delay or 0) / 60) if traffic_delay else 0,
            )
            self.db.add(traffic_snapshot)
            self.db.commit()

            logger.info(
                f"Route calculated: id={db_route.id}, distance={distance_meters}m, "
                f"duration={duration_seconds}s"
            )

            return self._db_model_to_response(db_route, route_steps)

        except Exception as e:
            logger.error(f"Error estimating route: {e}")
            self.db.rollback()
            raise

    def get_route(self, route_id: int) -> Optional[RouteResponse]:
        """Retrieve a previously calculated route"""
        db_route = self.db.query(Route).filter(Route.id == route_id).first()
        if not db_route:
            return None

        # Reconstruct route steps from JSON
        route_steps = []
        if db_route.route_steps:
            for step_data in db_route.route_steps:
                route_steps.append(
                    RouteStep(
                        start_location=Coordinate(
                            latitude=step_data["start"]["lat"],
                            longitude=step_data["start"]["lng"],
                        ),
                        end_location=Coordinate(
                            latitude=step_data["end"]["lat"],
                            longitude=step_data["end"]["lng"],
                        ),
                        instruction=step_data.get("instruction", ""),
                        distance_meters=step_data.get("distance_meters", 0),
                        duration_seconds=step_data.get("duration_seconds", 0),
                    )
                )

        return self._db_model_to_response(db_route, route_steps)

    def get_route_history(self, vehicle_id: Optional[str] = None, limit: int = 10):
        """Retrieve route history"""
        query = self.db.query(Route)
        if vehicle_id:
            query = query.filter(Route.vehicle_id == vehicle_id)

        routes = query.order_by(Route.created_at.desc()).limit(limit).all()
        return [
            self._db_model_to_response(route, []) for route in routes
        ]

    def _db_model_to_response(
        self, db_route: Route, route_steps: List[RouteStep]
    ) -> RouteResponse:
        """Convert database model to response schema"""
        return RouteResponse(
            id=db_route.id,
            start=LocationRequest(address=db_route.start_address),
            end=LocationRequest(address=db_route.end_address),
            resolved_start_address=db_route.resolved_start_address or db_route.start_address,
            resolved_end_address=db_route.resolved_end_address or db_route.end_address,
            vehicle_type=db_route.vehicle_type,
            vehicle_id=db_route.vehicle_id,
            load_weight=db_route.load_weight,
            load_volume=db_route.load_volume,
            departure_datetime=db_route.departure_datetime,
            priority=db_route.priority,
            distance_meters=db_route.distance_meters,
            duration_seconds=db_route.duration_seconds,
            traffic_delay_seconds=db_route.traffic_delay_seconds,
            polyline=db_route.polyline,
            route_steps=route_steps,
            created_at=db_route.created_at,
            updated_at=db_route.updated_at,
        )
