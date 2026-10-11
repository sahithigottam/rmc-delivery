"""SQLAlchemy ORM models"""
from datetime import datetime
import unicodedata
import hashlib

from sqlalchemy import Boolean, CheckConstraint, Column, Enum, Float, ForeignKey, Integer, String, Text, JSON, UniqueConstraint
from sqlalchemy.orm import relationship, validates
from sqlalchemy.sql import func

from app.db.database import Base
from app.db.types import UTCDateTime


def normalize_brand_name(name: str) -> str:
    """Canonical key shared by catalogue writes and the legacy seed importer."""
    return " ".join(unicodedata.normalize("NFKC", name).split()).casefold()


def brand_name_key(name: str, organization_id: str | None) -> str:
    """Namespace business names while retaining the legacy unique-key index."""
    normalized = normalize_brand_name(name)
    if organization_id is None:
        return normalized
    return f"{hashlib.sha256(organization_id.encode()).hexdigest()}:{normalized}"


class CatalogueRecord:
    version = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(UTCDateTime(), nullable=False, server_default=func.now())
    updated_at = Column(
        UTCDateTime(), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Business(CatalogueRecord, Base):
    """Locally registered business identified by its Clerk organization ID."""

    __tablename__ = "businesses"
    id = Column(String(100), primary_key=True)
    name = Column(String(200), nullable=False)


class JobSite(CatalogueRecord, Base):
    """Company address-book entry, separate from a batching plant."""

    __tablename__ = "job_sites"
    id = Column(String(100), primary_key=True)
    organization_id = Column(String(100), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    address = Column(String(500), nullable=False)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    country_code = Column(String(2), nullable=True)
    notes = Column(Text, nullable=True)
    active = Column(Boolean, nullable=False, default=True, server_default="1")
    created_by_user_id = Column(String(100), nullable=False)
    updated_by_user_id = Column(String(100), nullable=False)
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="job_site_name_not_empty"),
        CheckConstraint("length(trim(address)) > 0", name="job_site_address_not_empty"),
        CheckConstraint(
            "(lat IS NULL AND lng IS NULL) OR "
            "(lat IS NOT NULL AND lng IS NOT NULL AND lat BETWEEN -90 AND 90 AND lng BETWEEN -180 AND 180)",
            name="job_site_coordinates",
        ),
    )


class Brand(CatalogueRecord, Base):
    """Business-owned supplier with a case-insensitive name unique per owner."""

    __tablename__ = "brands"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="brand_name_not_empty"),
        CheckConstraint("length(trim(name_key)) > 0", name="brand_key_not_empty"),
    )

    id = Column(String(100), primary_key=True)
    organization_id = Column(String(100), ForeignKey("businesses.id"), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    name_key = Column(String(400), nullable=False, unique=True)

    @validates("name")
    def set_name_key(self, key, value):
        self.name_key = brand_name_key(value, self.organization_id)
        return value.strip()

    @validates("organization_id")
    def set_owner(self, key, value):
        if self.name is not None:
            self.name_key = brand_name_key(self.name, value)
        return value


class Region(CatalogueRecord, Base):
    """Country-aware region; baseline calibration is a label, not validation."""

    __tablename__ = "regions"
    __table_args__ = (
        CheckConstraint(
            "length(country_code) = 2 AND country_code = upper(country_code) "
            "AND substr(country_code, 1, 1) BETWEEN 'A' AND 'Z' "
            "AND substr(country_code, 2, 1) BETWEEN 'A' AND 'Z'",
            name="region_country_code",
        ),
        CheckConstraint(
            "calibration_status IN ('uncalibrated', 'nz_baseline')",
            name="region_calibration_status",
        ),
    )

    id = Column(String(100), primary_key=True)
    organization_id = Column(String(100), ForeignKey("businesses.id"), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    city_id = Column(String(100), ForeignKey("cities.id"), nullable=True, index=True)
    country_code = Column(String(2), nullable=False)
    administrative_area = Column(String(200), nullable=False)
    timezone = Column(String(100), nullable=False)
    calibration_status = Column(
        String(30), nullable=False, default="uncalibrated", server_default="uncalibrated"
    )
    city = relationship("City", lazy="joined")

    @property
    def state_id(self):
        return self.city.state_id if self.city is not None else None


class Plant(CatalogueRecord, Base):
    """Persistent dispatch plant, including inactive legacy entries."""

    __tablename__ = "plants"
    __table_args__ = (
        CheckConstraint("lat >= -90 AND lat <= 90", name="plant_latitude"),
        CheckConstraint("lng >= -180 AND lng <= 180", name="plant_longitude"),
    )

    id = Column(String(100), primary_key=True)
    organization_id = Column(String(100), ForeignKey("businesses.id"), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    brand_id = Column(String(100), ForeignKey("brands.id"), nullable=False, index=True)
    region_id = Column(String(100), ForeignKey("regions.id"), nullable=False, index=True)
    address = Column(String(500), nullable=False)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    active = Column(Boolean, nullable=False, default=True, server_default="1")
    supported_mix_codes = Column(
        JSON, nullable=False, default=lambda: ["GP", "HE", "RE"],
        server_default='["GP", "HE", "RE"]',
    )

    brand = relationship("Brand", lazy="joined")
    region = relationship("Region", lazy="joined")


class CatalogueEvent(Base):
    """Append-only audit payload for catalogue mutations."""

    __tablename__ = "catalogue_events"

    id = Column(Integer, primary_key=True)
    entity_type = Column(String(30), nullable=False)
    entity_id = Column(String(100), nullable=False, index=True)
    action = Column(String(30), nullable=False)
    data = Column(JSON, nullable=False, default=dict)
    actor_user_id = Column(String(100), nullable=True)
    organization_id = Column(String(100), nullable=True, index=True)
    created_at = Column(UTCDateTime(), nullable=False, server_default=func.now())


class CatalogueIdempotency(Base):
    """Persist create responses in the same transaction as their resources."""

    __tablename__ = "catalogue_idempotency"

    key = Column(String(200), primary_key=True)
    entity_type = Column(String(30), nullable=False)
    request_hash = Column(String(128), nullable=False)
    response_data = Column(JSON, nullable=False)
    created_at = Column(UTCDateTime(), nullable=False, server_default=func.now())


class CatalogueMigration(Base):
    """Versioned ledger preventing seed re-import after catalogue changes."""

    __tablename__ = "catalogue_migrations"

    version = Column(Integer, primary_key=True)
    applied_at = Column(UTCDateTime(), nullable=False, server_default=func.now())


class OrganizationPlant(Base):
    """Legacy assignment records retained for reviewed ownership migration."""

    __tablename__ = "organization_plants"
    __table_args__ = (
        UniqueConstraint("organization_id", "plant_id", name="uq_organization_plant"),
    )

    id = Column(Integer, primary_key=True)
    organization_id = Column(String(100), nullable=False, index=True)
    plant_id = Column(String(100), ForeignKey("plants.id"), nullable=False, index=True)
    created_by_user_id = Column(String(100), nullable=True)
    created_at = Column(UTCDateTime(), nullable=False, server_default=func.now())

    plant = relationship("Plant")


class Route(Base):
    """Route request and calculation storage"""

    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(String(100), nullable=True, index=True)
    created_by_user_id = Column(String(100), nullable=True)
    start_address = Column(String(500), nullable=False)  # Original input address
    start_lat = Column(Float, nullable=False)  # Geocoded latitude
    start_lng = Column(Float, nullable=False)  # Geocoded longitude
    resolved_start_address = Column(String(500), nullable=True)  # Geocoded formatted address
    
    end_address = Column(String(500), nullable=False)  # Original input address
    end_lat = Column(Float, nullable=False)  # Geocoded latitude
    end_lng = Column(Float, nullable=False)  # Geocoded longitude
    resolved_end_address = Column(String(500), nullable=True)  # Geocoded formatted address
    vehicle_type = Column(String(50), nullable=False)
    vehicle_id = Column(String(100), nullable=True)
    load_weight = Column(Float, nullable=True)
    load_volume = Column(Float, nullable=True)
    departure_datetime = Column(UTCDateTime(), nullable=True)
    priority = Column(String(20), default="normal")
    max_delivery_minutes = Column(Integer, nullable=True)  # Maximum delivery time constraint

    # Route results
    distance_meters = Column(Float, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    traffic_delay_seconds = Column(Float, nullable=True)
    exceeds_delivery_limit = Column(Integer, nullable=True)  # 1 if exceeds, 0 if not, NULL if no limit
    delivery_limit_exceeded_by = Column(Integer, nullable=True)  # Minutes exceeded by
    polyline = Column(Text, nullable=True)
    route_steps = Column(JSON, nullable=True)
    
    # Dynamic routing fields
    avoid_options = Column(JSON, nullable=True)  # List of avoided features: tolls, highways, ferries
    selected_route_index = Column(Integer, default=0)  # Which alternative route was selected
    total_alternatives = Column(Integer, default=1)  # Number of route alternatives available
    alternatives_summary = Column(JSON, nullable=True)  # Summary info of all alternatives

    # Metadata
    created_at = Column(UTCDateTime(), server_default=func.now())
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self):
        return f"<Route(id={self.id}, vehicle_type={self.vehicle_type})>"


class Vehicle(Base):
    """Vehicle specifications and constraints"""

    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_code = Column(String(100), unique=True, index=True)
    vehicle_type = Column(String(50), nullable=False)
    max_height_cm = Column(Integer, nullable=True)
    max_width_cm = Column(Integer, nullable=True)
    max_weight_kg = Column(Float, nullable=True)
    max_volume_m3 = Column(Float, nullable=True)
    registration_number = Column(String(50), nullable=True)

    created_at = Column(UTCDateTime(), server_default=func.now())
    updated_at = Column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self):
        return f"<Vehicle(vehicle_code={self.vehicle_code}, type={self.vehicle_type})>"


class TrafficSnapshot(Base):
    """Store traffic conditions at time of route calculation"""

    __tablename__ = "traffic_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    route_id = Column(Integer, nullable=False, index=True)
    timestamp = Column(UTCDateTime(), server_default=func.now())
    current_duration_seconds = Column(Float, nullable=False)
    traffic_condition = Column(String(50), default="normal")
    congestion_level = Column(Integer, nullable=True)

    def __repr__(self):
        return f"<TrafficSnapshot(route_id={self.route_id}, condition={self.traffic_condition})>"


# ============================================================================
# Trip Management — active delivery tracking + rerouting
# ============================================================================

class Trip(Base):
    """Active delivery trip — tracks a truck from start to destination"""

    __tablename__ = "trips"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(String(100), nullable=True, index=True)
    created_by_user_id = Column(String(100), nullable=True)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False, index=True)

    # Trip state
    status = Column(
        String(20), nullable=False, default="pending",
        index=True,
        # pending | in_progress | paused | completed | cancelled
    )

    # Truck current position (updated by GPS / position reports)
    current_lat = Column(Float, nullable=True)
    current_lng = Column(Float, nullable=True)
    heading = Column(Float, nullable=True)  # degrees 0-360

    # Trip metadata from the original route
    start_address = Column(String(500), nullable=False)
    end_address = Column(String(500), nullable=False)
    start_lat = Column(Float, nullable=False)
    start_lng = Column(Float, nullable=False)
    end_lat = Column(Float, nullable=False)
    end_lng = Column(Float, nullable=False)
    vehicle_type = Column(String(50), default="rmc_truck")
    vehicle_id = Column(String(100), nullable=True)
    priority = Column(String(20), default="normal")
    avoid_options = Column(JSON, nullable=True)

    # Current route state
    current_polyline = Column(Text, nullable=True)  # may differ from original after reroute
    original_distance_meters = Column(Float, nullable=True)
    original_duration_seconds = Column(Float, nullable=True)
    remaining_distance_meters = Column(Float, nullable=True)
    remaining_duration_seconds = Column(Float, nullable=True)
    current_traffic_delay = Column(Float, nullable=True)  # latest traffic delay in seconds

    # Reroute tracking
    reroute_count = Column(Integer, default=0)
    last_reroute_at = Column(UTCDateTime(), nullable=True)
    last_traffic_check_at = Column(UTCDateTime(), nullable=True)

    # ETA
    estimated_arrival = Column(UTCDateTime(), nullable=True)

    # ── RMC-specific fields ──────────────────────────────────────────
    # Concrete load lifecycle — the 90-minute countdown
    batch_time = Column(UTCDateTime(), nullable=True)       # when concrete was batched
    load_expiry_time = Column(UTCDateTime(), nullable=True) # calculated expiry
    load_status = Column(String(20), default="fresh")                 # fresh|warning|critical|expired
    mix_code = Column(String(50), nullable=True)                      # e.g. "30MPa/20/120"
    concrete_grade = Column(String(20), nullable=True)                # e.g. "30MPa"
    volume_m3 = Column(Float, nullable=True)                          # load volume
    retarder_added = Column(Boolean, default=False)                   # chemical retarder applied?
    retarder_extension_minutes = Column(Integer, default=0)           # extension granted
    load_max_life_minutes = Column(Integer, default=90)               # grade-adjusted base life, before retarder
    plant_id = Column(String(50), nullable=True)                      # dispatching plant
    pour_duration_minutes = Column(Integer, nullable=True)            # expected pour time on site

    # ── Dispatch / scheduling fields ─────────────────────────────────
    scheduled_at = Column(UTCDateTime(), nullable=True)     # planned departure time
    concrete_mix = Column(String(10), nullable=True)                  # mix family: GP | HE | RE
    outcome = Column(String(20), nullable=True)                       # succeeded | failed (set on complete)
    prediction_json = Column(Text, nullable=True)                     # JSON snapshot from prediction engine

    # Timestamps
    started_at = Column(UTCDateTime(), nullable=True)
    completed_at = Column(UTCDateTime(), nullable=True)
    archived_at = Column(UTCDateTime(), nullable=True)
    archived_by_user_id = Column(String(100), nullable=True)
    created_at = Column(UTCDateTime(), server_default=func.now())
    updated_at = Column(UTCDateTime(), server_default=func.now(), onupdate=func.now())

    # Relationships
    events = relationship("TripEvent", back_populates="trip", order_by="TripEvent.created_at")

    def __repr__(self):
        return f"<Trip(id={self.id}, status={self.status}, vehicle={self.vehicle_id})>"


class TripEvent(Base):
    """
    Immutable event log for a trip — full audit trail.
    Every state change, traffic check, reroute, position update is logged.
    """

    __tablename__ = "trip_events"

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=False, index=True)
    actor_user_id = Column(String(100), nullable=True)

    # Event type
    event_type = Column(
        String(30), nullable=False, index=True,
        # trip_started | trip_paused | trip_resumed | trip_completed | trip_cancelled
        # position_update | traffic_check | reroute_suggested | reroute_applied
        # eta_updated | delay_detected | delay_cleared
    )

    # Event data (flexible JSON payload)
    data = Column(JSON, nullable=True)
    # Examples:
    #   position_update:    {"lat": -36.8, "lng": 174.7, "heading": 180}
    #   traffic_check:      {"delay_seconds": 300, "condition": "heavy"}
    #   reroute_suggested:  {"reason": "...", "new_distance": 12000, "new_duration": 900, "polyline": "..."}
    #   reroute_applied:    {"reroute_number": 2, "old_duration": 1200, "new_duration": 900}
    #   delay_detected:     {"delay_minutes": 8, "severity": "moderate"}

    # Position at time of event
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)

    # Timestamp
    created_at = Column(UTCDateTime(), server_default=func.now())

    # Relationship
    trip = relationship("Trip", back_populates="events")

    def __repr__(self):
        return f"<TripEvent(trip_id={self.trip_id}, type={self.event_type})>"
