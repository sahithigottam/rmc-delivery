"""SQLAlchemy ORM models"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, JSON
from sqlalchemy.sql import func

from app.db.database import Base


class Route(Base):
    """Route request and calculation storage"""

    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, index=True)
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
    departure_datetime = Column(DateTime, nullable=True)
    priority = Column(String(20), default="normal")

    # Route results
    distance_meters = Column(Float, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    traffic_delay_seconds = Column(Float, nullable=True)
    polyline = Column(Text, nullable=True)
    route_steps = Column(JSON, nullable=True)

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
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

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self):
        return f"<Vehicle(vehicle_code={self.vehicle_code}, type={self.vehicle_type})>"


class TrafficSnapshot(Base):
    """Store traffic conditions at time of route calculation"""

    __tablename__ = "traffic_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    route_id = Column(Integer, nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    current_duration_seconds = Column(Float, nullable=False)
    traffic_condition = Column(String(50), default="normal")
    congestion_level = Column(Integer, nullable=True)

    def __repr__(self):
        return f"<TrafficSnapshot(route_id={self.route_id}, condition={self.traffic_condition})>"
