"""SQLAlchemy ORM models for Routing Microservice"""
from datetime import datetime
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, JSON
from sqlalchemy.sql import func
from database import Base


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
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self):
        return f"<Route(id={self.id}, vehicle_type={self.vehicle_type})>"


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
