"""Pydantic schemas for Routing Microservice"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class Coordinate(BaseModel):
    """Geographic coordinate"""
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class LocationRequest(BaseModel):
    """Location as street address (will be geocoded to coordinates)"""
    address: str = Field(..., min_length=3, description="Street address or location name")


class RouteRequestBase(BaseModel):
    """Base Route request schema"""
    start: LocationRequest
    end: LocationRequest
    vehicle_type: str = Field(default="rmc_truck", description="Default: rmc_truck")
    vehicle_id: Optional[str] = None
    load_weight: Optional[float] = Field(None, ge=0)
    load_volume: Optional[float] = Field(None, ge=0)
    departure_datetime: Optional[datetime] = None
    priority: str = Field("normal", pattern="^(normal|urgent|economy|low|high)$")
    max_delivery_minutes: Optional[int] = Field(None, ge=1, description="Maximum acceptable delivery time in minutes")
    
    # Dynamic routing options
    request_alternatives: bool = Field(False, description="Request alternative routes")
    avoid: Optional[List[str]] = Field(None, description="Features to avoid: tolls, highways, ferries")
    waypoints: Optional[List[Coordinate]] = Field(None, description="Intermediate waypoints for rerouting")
    route_index: int = Field(0, ge=0, description="Which alternative route to use (0 = primary)")


class RouteCreate(RouteRequestBase):
    """Schema for creating a new route"""
    pass


class RouteStep(BaseModel):
    """Single step in a route"""
    start_location: Coordinate
    end_location: Coordinate
    instruction: str
    distance_meters: float
    duration_seconds: float


class RouteResponse(RouteRequestBase):
    """Route response with calculated results"""
    id: int
    resolved_start_address: str
    resolved_end_address: str
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float
    distance_meters: float
    duration_seconds: float
    traffic_delay_seconds: Optional[float] = None
    exceeds_delivery_limit: Optional[bool] = None
    delivery_limit_exceeded_by: Optional[int] = None
    polyline: Optional[str] = None
    route_steps: Optional[List[RouteStep]] = None
    
    # Alternative routes info
    total_alternatives: int = Field(1, description="Total number of route alternatives available")
    selected_route_index: int = Field(0, description="Index of the selected route (0 = primary)")
    alternatives_summary: Optional[List[dict]] = Field(None, description="Summary of alternative routes")
    
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RerouteRequest(BaseModel):
    """Request for mid-trip reroute using current lat/lng (skips geocoding start)"""
    current_lat: float = Field(..., ge=-90, le=90, description="Truck's current latitude")
    current_lng: float = Field(..., ge=-180, le=180, description="Truck's current longitude")
    end: LocationRequest
    vehicle_type: str = Field(default="rmc_truck")
    priority: str = Field("normal", pattern="^(normal|urgent|economy|low|high)$")
    avoid: Optional[List[str]] = Field(None, description="Features to avoid: tolls, highways, ferries")


class RerouteResponse(BaseModel):
    """Lightweight response for reroute checks (no DB save)"""
    distance_meters: float
    duration_seconds: float
    traffic_delay_seconds: Optional[float] = None
    polyline: Optional[str] = None
    route_steps: Optional[List[RouteStep]] = None
    reroute_recommended: bool = Field(False, description="True if new route differs significantly")
    reason: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standard error response"""
    detail: str
    error_code: Optional[str] = None
