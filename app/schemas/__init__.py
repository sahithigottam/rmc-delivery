"""Pydantic schemas for request/response validation"""
from datetime import datetime
from typing import Annotated, Any, Dict, List, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.utils.time import as_utc

UTCInput = Annotated[AwareDatetime, AfterValidator(as_utc)]
UTCOutput = Annotated[datetime, AfterValidator(as_utc)]


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
    departure_datetime: Optional[UTCInput] = Field(
        None, description="Departure time with Z or an explicit timezone offset.",
    )
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
    resolved_start_address: str  # Geocoded address from coordinates
    resolved_end_address: str    # Geocoded address from coordinates
    start_lat: float  # Start latitude
    start_lng: float  # Start longitude
    end_lat: float    # End latitude
    end_lng: float    # End longitude
    distance_meters: float
    duration_seconds: float
    traffic_delay_seconds: Optional[float] = None
    exceeds_delivery_limit: Optional[bool] = None  # True if route exceeds max_delivery_minutes
    delivery_limit_exceeded_by: Optional[int] = None  # Minutes exceeded by
    polyline: Optional[str] = None
    route_steps: Optional[List[RouteStep]] = None
    
    # Alternative routes info
    total_alternatives: int = Field(1, description="Total number of route alternatives available")
    selected_route_index: int = Field(0, description="Index of the selected route (0 = primary)")
    alternatives_summary: Optional[List[dict]] = Field(None, description="Summary of alternative routes")
    
    departure_datetime: Optional[UTCOutput] = None
    created_at: UTCOutput
    updated_at: UTCOutput

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
    created_at: UTCOutput
    updated_at: UTCOutput

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


# ============================================================================
# Trip Management Schemas
# ============================================================================

class TripStart(BaseModel):
    """Start a trip from a previously calculated route"""

    route_id: int = Field(..., description="ID of the calculated route to start a trip for")
    vehicle_id: Optional[str] = Field(None, description="Override vehicle ID for this trip")

    # RMC-specific fields
    batch_time: Optional[UTCInput] = Field(
        None, description="Batch time with Z or an explicit timezone offset (defaults to now).",
    )
    mix_code: Optional[str] = Field(None, description="Concrete mix code e.g. '30MPa/20/120'")
    concrete_grade: Optional[str] = Field(None, description="Concrete grade e.g. '30MPa'")
    volume_m3: Optional[float] = Field(None, ge=0.1, le=12.0, description="Load volume in m³ (typical NZ truck: 6m³)")
    requires_retarder: bool = Field(False, description="Whether retarder should be pre-added")
    plant_id: Optional[str] = Field(None, description="Dispatching plant ID")
    pour_duration_minutes: Optional[int] = Field(None, ge=1, description="Expected pour time on site")


class PositionUpdate(BaseModel):
    """GPS position report from the truck"""

    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    heading: Optional[float] = Field(None, ge=0, le=360, description="Heading in degrees")
    speed_kmh: Optional[float] = Field(None, ge=0, description="Current speed in km/h")
    captured_at: Optional[UTCInput] = Field(
        None,
        description="Original GPS capture time, ISO 8601 with timezone. "
                    "Omit to use server receipt time.",
    )

class TripEventResponse(BaseModel):
    """A single trip event"""

    id: int
    trip_id: int
    event_type: str
    data: Optional[dict] = None
    actor_user_id: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    created_at: UTCOutput

    class Config:
        from_attributes = True


class TripResponse(BaseModel):
    """Full trip state"""

    id: int
    route_id: int
    status: str
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None
    heading: Optional[float] = None
    current_position_at: Optional[UTCOutput] = None

    start_address: str
    end_address: str
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float
    vehicle_type: str
    vehicle_id: Optional[str] = None
    priority: str
    avoid_options: Optional[List[str]] = None

    current_polyline: Optional[str] = None
    original_distance_meters: Optional[float] = None
    original_duration_seconds: Optional[float] = None
    remaining_distance_meters: Optional[float] = None
    remaining_duration_seconds: Optional[float] = None
    current_traffic_delay: Optional[float] = None

    reroute_count: int = 0
    last_reroute_at: Optional[UTCOutput] = None
    last_traffic_check_at: Optional[UTCOutput] = None
    estimated_arrival: Optional[UTCOutput] = None

    # RMC-specific fields
    batch_time: Optional[UTCOutput] = None
    load_expiry_time: Optional[UTCOutput] = None
    load_status: Optional[str] = None
    mix_code: Optional[str] = None
    concrete_grade: Optional[str] = None
    volume_m3: Optional[float] = None
    retarder_added: bool = False
    retarder_extension_minutes: int = 0
    load_max_life_minutes: int = Field(
        90, description="Grade-adjusted base life before any retarder extension.",
    )
    load_minutes_remaining: Optional[float] = None  # calculated, not persisted
    plant_id: Optional[str] = None
    pour_duration_minutes: Optional[int] = None

    # Dispatch / scheduling
    scheduled_at: Optional[UTCOutput] = None
    concrete_mix: Optional[str] = None          # GP | HE | RE
    outcome: Optional[str] = None               # succeeded | failed
    completion_distance_meters: Optional[float] = None
    completion_review_required: Optional[bool] = None
    completion_review_reason: Optional[str] = None

    started_at: Optional[UTCOutput] = None
    completed_at: Optional[UTCOutput] = None
    created_at: UTCOutput
    updated_at: UTCOutput

    # Recent events (last 20)
    recent_events: Optional[List[TripEventResponse]] = None

    class Config:
        from_attributes = True


class TripRerouteInfo(BaseModel):
    """Info about a reroute suggestion pushed via SSE"""

    trip_id: int
    reroute_number: int
    reason: str
    old_duration_seconds: float
    new_duration_seconds: float
    new_distance_meters: float
    traffic_delay_seconds: Optional[float] = None
    new_polyline: Optional[str] = None
    new_steps: Optional[List[RouteStep]] = None
    applied: bool = False


# ── Catalogue schemas ─────────────────────────────────────────────────────

CatalogueID = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$")]
OrganizationID = Annotated[str, Field(min_length=5, max_length=100, pattern=r"^org_[A-Za-z0-9]+$")]
CatalogueName = Annotated[str, Field(min_length=1, max_length=200)]
MixCode = Literal["GP", "HE", "RE"]


class CatalogueInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class BusinessCreate(CatalogueInput):
    id: OrganizationID
    name: CatalogueName


class BusinessUpdate(CatalogueInput):
    name: CatalogueName
    version: int = Field(..., ge=1)


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    version: int
    created_at: UTCOutput
    updated_at: UTCOutput


class BusinessPage(BaseModel):
    items: List[BusinessOut]
    total: int
    limit: int
    offset: int


class BrandCreate(CatalogueInput):
    name: CatalogueName
    organization_id: OrganizationID


class BrandUpdate(CatalogueInput):
    version: int = Field(..., ge=1)
    name: Optional[CatalogueName] = None
    organization_id: Optional[OrganizationID] = None

    @model_validator(mode="after")
    def validate_changes(self) -> "BrandUpdate":
        changes = self.model_fields_set - {"version"}
        if not changes or any(getattr(self, field) is None for field in changes):
            raise ValueError("PATCH requires non-null changes")
        return self


class BrandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    organization_id: Optional[str] = None
    version: int
    created_at: UTCOutput
    updated_at: UTCOutput


class RegionCreate(CatalogueInput):
    name: CatalogueName
    city_id: CatalogueID
    country_code: Optional[str] = Field(None, pattern=r"^[A-Z]{2}$")
    administrative_area: Optional[CatalogueName] = None
    timezone: Optional[str] = Field(None, min_length=1, max_length=100)

    @field_validator("country_code")
    @classmethod
    def validate_country(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        codes = (
            "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ "
            "CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR "
            "GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP "
            "KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ "
            "NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW "
            "SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ "
            "UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW"
        ).split()
        if value not in codes:
            raise ValueError("country_code must be an assigned ISO 3166-1 alpha-2 code")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value


class RegionUpdate(RegionCreate):
    version: int = Field(..., ge=1)


class RegionOut(RegionCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: Optional[str] = None
    city_id: Optional[str] = None
    state_id: Optional[str] = None
    country_code: str
    administrative_area: CatalogueName
    timezone: str
    calibration_status: Literal["uncalibrated", "nz_baseline"]
    version: int
    created_at: UTCOutput
    updated_at: UTCOutput


class PlantLocation(CatalogueInput):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class PlantCreate(CatalogueInput):
    name: CatalogueName
    brand_id: CatalogueID
    region_id: CatalogueID
    address: str = Field(..., min_length=3, max_length=500)
    location: PlantLocation
    active: bool = True
    supported_mix_codes: List[MixCode] = Field(..., min_length=1, max_length=3)

    @field_validator("supported_mix_codes")
    @classmethod
    def unique_mixes(cls, value: List[MixCode]) -> List[MixCode]:
        if len(set(value)) != len(value):
            raise ValueError("supported_mix_codes must not contain duplicates")
        return value


class PlantUpdate(CatalogueInput):
    version: int = Field(..., ge=1)
    name: Optional[CatalogueName] = None
    brand_id: Optional[CatalogueID] = None
    region_id: Optional[CatalogueID] = None
    address: Optional[str] = Field(None, min_length=3, max_length=500)
    location: Optional[PlantLocation] = None
    active: Optional[bool] = None
    supported_mix_codes: Optional[List[MixCode]] = Field(None, min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_changes(self) -> "PlantUpdate":
        changes = self.model_fields_set - {"version"}
        if not changes:
            raise ValueError("PATCH must include at least one changed field")
        if any(getattr(self, field) is None for field in changes):
            raise ValueError("Plant fields cannot be cleared with null")
        if self.supported_mix_codes is not None and len(set(self.supported_mix_codes)) != len(self.supported_mix_codes):
            raise ValueError("supported_mix_codes must not contain duplicates")
        return self


class PlantOut(BaseModel):
    id: str
    name: str
    organization_id: Optional[str] = None
    city_id: Optional[str] = None
    state_id: Optional[str] = None
    administrative_area: Optional[str] = None
    brand_id: str
    region_id: str
    address: str
    location: PlantLocation
    active: bool
    supported_mix_codes: List[MixCode]
    country_code: str
    timezone: str
    calibration_status: Literal["uncalibrated", "nz_baseline"]
    version: int
    created_at: UTCOutput
    updated_at: UTCOutput


class PlantPage(BaseModel):
    items: List[PlantOut]
    total: int
    limit: int
    offset: int


class BrandPage(BaseModel):
    items: List[BrandOut]
    total: int
    limit: int
    offset: int


class RegionPage(BaseModel):
    items: List[RegionOut]
    total: int
    limit: int
    offset: int


class BrandAnalysisRequest(CatalogueInput):
    """Request brand analysis: pick a brand + destination, get ranked predictions."""
    brand_id: CatalogueID
    region_id: Optional[CatalogueID] = None
    job_site_data: Dict[str, Any] = Field(
        ...,
        description="Full address data object for the job site from OpenStreetMap (must include 'display_name').",
    )
    concrete_mix: MixCode = "GP"
    country_code: Optional[str] = Field(
        default=None,
        pattern=r"^[A-Z]{2}$",
        description="Optional ISO 3166-1 alpha-2 country code for geocoding, e.g. IN or NZ.",
    )
    top_n: int = Field(default=5, ge=1, le=20, description="Max plants to analyse")
    include_llm_analysis: bool = Field(default=True, description="Include LLM comparison of all routes")


class PlantPredictionResult(BaseModel):
    """Prediction result for a single plant within a brand analysis."""
    plant: PlantOut
    google_eta_minutes: Optional[float] = None
    adjusted_eta_minutes: Optional[float] = None
    remaining_life_minutes: Optional[float] = None
    buffer_depletion_rate: Optional[float] = None
    delay_constant_used: Optional[float] = None
    risk_level: Optional[str] = None          # low | medium | high | critical
    success_probability: Optional[float] = None
    baseline_source: Optional[str] = None
    confidence_reason: Optional[str] = None
    prediction_calibration_status: Optional[str] = None
    recommendation: Optional[str] = None
    llm_analysis: Optional[dict] = None
    error: Optional[str] = None              # if this plant failed to resolve


class BrandAnalysisResponse(BaseModel):
    """Response for brand analysis — list of plant predictions, ranked by remaining life."""
    brand: str
    brand_id: str
    job_site_address: str
    concrete_mix: str
    total_plants_analysed: int
    results: List[PlantPredictionResult]
    best_plant_id: Optional[str] = None      # plant with highest remaining life
    llm_comparison: Optional[dict] = None    # single LLM comparison of all plants


# ── Dispatch schemas ──────────────────────────────────────────────────────

class DispatchRequest(BaseModel):
    """Create a scheduled (pending) trip from a chosen plant + job site."""
    plant_id: str = Field(..., description="Owned plant ID from the business catalogue")
    job_site_address: str = Field(..., description="Delivery destination address")
    concrete_mix: MixCode = "GP"
    scheduled_at: UTCInput = Field(
        ..., description="Planned departure time with Z or an explicit timezone offset.",
    )
    vehicle_id: Optional[str] = None
    volume_m3: Optional[float] = Field(None, ge=0.5, le=20.0)
    pour_duration_minutes: Optional[int] = Field(None, ge=1, le=240)
    # Snapshot from /plants/analyse (saved for accuracy tracking)
    prediction_snapshot: Optional[dict] = Field(
        None, description="Prediction result dict from /plants/analyse to store with trip"
    )


class DispatchResponse(BaseModel):
    """Response when a trip is scheduled (status=pending)."""
    trip_id: int
    route_id: int
    status: str                          # "pending"
    plant_id: str
    plant_name: str
    plant_address: str
    job_site_address: str
    concrete_mix: str
    scheduled_at: UTCOutput
    distance_meters: Optional[float] = None
    estimated_duration_minutes: Optional[float] = None
    created_at: UTCOutput


class TripBeginRequest(BaseModel):
    """Activate a pending trip (truck is loading now)."""
    batch_time: Optional[UTCInput] = Field(
        None, description="Batch time with Z or an explicit timezone offset. Defaults to now."
    )
    mix_code: Optional[str] = Field(None, description="Full mix code e.g. '30MPa/20/100'")
    concrete_grade: Optional[str] = Field(None, description="e.g. '30MPa'. Defaults to mix family default.")
    volume_m3: Optional[float] = Field(None, ge=0.5, le=20.0)
    requires_retarder: bool = False
    pour_duration_minutes: Optional[int] = None


class TripCompleteRequest(BaseModel):
    """Optional body for POST /trips/{id}/complete to record outcome."""
    success: Optional[bool] = Field(
        None,
        description="True = concrete was poured successfully. "
                    "Defaults to True if load is still within time window."
    )
    notes: Optional[str] = Field(
        None, max_length=500,
        description="Operator notes; a non-blank reason is required when reporting success for an expired load.",
    )


__all__ = [
    "Coordinate",
    "LocationRequest",
    "RouteRequestBase",
    "RouteCreate",
    "RouteStep",
    "RouteResponse",
    "RerouteRequest",
    "RerouteResponse",
    "VehicleBase",
    "VehicleCreate",
    "VehicleResponse",
    "ErrorResponse",
    "TripStart",
    "PositionUpdate",
    "TripEventResponse",
    "TripResponse",
    "TripRerouteInfo",
    # Plants / dispatch
    "PlantOut",
    "PlantCreate",
    "PlantUpdate",
    "BrandAnalysisRequest",
    "PlantPredictionResult",
    "BrandAnalysisResponse",
    "DispatchRequest",
    "DispatchResponse",
    "TripBeginRequest",
    "TripCompleteRequest",
]
