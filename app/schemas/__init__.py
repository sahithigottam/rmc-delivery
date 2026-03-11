"""Pydantic schemas for request/response validation"""
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
    priority: str = Field("normal", pattern="^(normal|urgent|economy)$")


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
    resolved_start_address: str  # Geocoded address from coordinates
    resolved_end_address: str    # Geocoded address from coordinates
    distance_meters: float
    duration_seconds: float
    traffic_delay_seconds: Optional[float] = None
    polyline: Optional[str] = None
    route_steps: Optional[List[RouteStep]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VehicleBase(BaseModel):
    """Base Vehicle schema"""

    vehicle_code: str
    vehicle_type: str
    max_height_cm: Optional[int] = None
    max_width_cm: Optional[int] = None
    max_weight_kg: Optional[float] = None
    max_volume_m3: Optional[float] = None
    registration_number: Optional[str] = None


class VehicleCreate(VehicleBase):
    """Schema for creating a vehicle"""

    pass


class VehicleResponse(VehicleBase):
    """Vehicle response schema"""

    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ErrorResponse(BaseModel):
    """Standard error response"""

    detail: str
    error_code: Optional[str] = None


__all__ = [
    "Coordinate",
    "LocationRequest",
    "RouteRequestBase",
    "RouteCreate",
    "RouteStep",
    "RouteResponse",
    "VehicleBase",
    "VehicleCreate",
    "VehicleResponse",
    "ErrorResponse",
]
