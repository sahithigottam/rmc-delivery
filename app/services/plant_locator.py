"""
PlantLocator — Find the nearest or best concrete batching plant.

Two modes — choose based on what you need:

  1. nearest_by_distance()  — FREE, instant, no API call.
     Uses the Haversine formula on hardcoded plant coordinates.
     Good for: showing a rough "closest plant" suggestion,
               pre-filtering candidates before calling Google.

  2. nearest_by_distance() is called FIRST to get the top N candidates,
     then PredictionService.best_plant() calls Google Directions only
     for those N plants — not all 20.

Why this matters:
  - All 20 plants → Google = 20 API calls ($0.10 per request)
  - Top 3 by distance → Google = 3 API calls ($0.015 per request)
  - Savings: 85% fewer Google calls, same accuracy

Data source: the SQLite plant catalogue imported once from config/plants.json.
"""
from __future__ import annotations

import logging
import math
from typing import List, Optional

from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.db.models import Brand, Plant, Region
from app.services.catalogue import plant_dict

logger = logging.getLogger(__name__)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Straight-line distance between two coordinates in kilometres.
    Uses Haversine formula — accurate to within ~0.5% for Auckland distances.
    No external library needed.
    """
    R = 6371.0  # Earth radius km
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lng / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class PlantLocator:
    """
    Finds the nearest concrete batching plants for a given job site.

    Reads the database catalogue without an in-memory singleton.
    All distance calculations run locally — zero API calls, zero cost.

    Usage:
        locator = PlantLocator()

        # Get all plants sorted by distance
        ranked = locator.nearest_by_distance(lat=-36.8485, lng=174.7633)

        # Get top 3 only (for passing to Google Directions)
        top3 = locator.nearest_by_distance(lat=-36.8485, lng=174.7633, top_n=3)

        # Get a single plant by ID
        plant = locator.get_by_id("holcim_avondale")

        # Get all addresses for a brand
        allied = locator.get_by_brand("Allied")
    """

    def __init__(
        self,
        db: Optional[Session] = None,
        organization_id: Optional[str] = None,
    ):
        self.db = db
        self.organization_id = organization_id

    def _read(self, active_only: bool = True) -> List[dict]:
        def query(db: Session) -> List[dict]:
            records = db.query(Plant)
            if self.organization_id is not None:
                records = records.join(Brand, Brand.id == Plant.brand_id).join(Region, Region.id == Plant.region_id).filter(
                    Plant.organization_id == self.organization_id,
                    Brand.organization_id == self.organization_id,
                    Region.organization_id == self.organization_id,
                )
            if active_only:
                records = records.filter(Plant.active.is_(True))
            return [plant_dict(p) for p in records.order_by(Plant.id).all()]

        if self.db is not None:
            return query(self.db)
        with SessionLocal() as db:
            return query(db)

    @property
    def plants(self) -> List[dict]:
        return self._read()

    def nearest_by_distance(
        self,
        lat: float,
        lng: float,
        top_n: Optional[int] = None,
        brand: Optional[str] = None,
        region: Optional[str] = None,
        brand_id: Optional[str] = None,
    ) -> List[dict]:
        """
        Return plants sorted by straight-line distance to the job site.
        FREE — no API calls, runs in microseconds.

        Args:
            lat, lng  : Job site coordinates
            top_n     : Return only top N closest (None = all)
            brand     : Filter by brand  e.g. "Holcim", "Allied", "Firth"
            region    : Filter by region e.g. "south", "north_shore", "west"

        Returns:
            List of plant dicts, each with an added "distance_km" field,
            sorted nearest first.

        Example:
            [
              {"id": "firth_manukau", "name": "Firth Manukau",
               "distance_km": 1.2, "lat": ..., "lng": ..., ...},
              ...
            ]
        """
        candidates = self.plants

        if brand:
            candidates = [p for p in candidates if p.get("brand", "").lower() == brand.lower()]
        if brand_id:
            candidates = [p for p in candidates if p["brand_id"] == brand_id]
        if region:
            candidates = [p for p in candidates if p.get("region", "") == region]

        scored = []
        for plant in candidates:
            dist = _haversine_km(lat, lng, plant["lat"], plant["lng"])
            scored.append({**plant, "distance_km": round(dist, 2)})

        scored.sort(key=lambda p: p["distance_km"])

        return scored[:top_n] if top_n else scored

    def get_by_id(self, plant_id: str) -> Optional[dict]:
        """Get a plant by its unique ID."""
        return next((p for p in self._read(active_only=False) if p["id"] == plant_id), None)

    def get_by_brand(self, brand: str) -> List[dict]:
        """Get all active plants for a specific brand."""
        return [p for p in self.plants if p.get("brand", "").lower() == brand.lower()]

    def all_addresses(self, top_n: Optional[int] = None) -> List[str]:
        """Return all plant addresses as strings (for passing to Google Directions)."""
        plants = self.plants[:top_n] if top_n else self.plants
        return [p["address"] for p in plants]

    def candidates_for_job(
        self,
        job_lat: float,
        job_lng: float,
        concrete_limit_minutes: int = 90,
        truck_speed_factor: float = 1.08,
        top_n: int = 5,
        concrete_mix: Optional[str] = None,
    ) -> List[dict]:
        """
        Return the most viable plant candidates for a job site.

        Filters out plants that are physically too far away to deliver
        within the concrete limit — no point calling Google for them.

        Logic:
          straight-line distance / avg road speed (40 km/h) × truck factor
          → rough time estimate. Discard if already > 80% of the limit.

        Args:
            job_lat, job_lng      : Job site coordinates
            concrete_limit_minutes: NZS 3109 window (90/60/120 min)
            truck_speed_factor    : 1.08× for RMC trucks (NZTA)
            top_n                 : Max candidates to return

        Returns:
            Top N plants most likely to make the delivery window,
            sorted by straight-line distance.
        """
        AVG_ROAD_SPEED_KMH = 40.0   # Conservative average for Auckland roads
        MAX_FRACTION = 0.80         # Discard if rough ETA > 80% of limit

        max_rough_minutes = concrete_limit_minutes * MAX_FRACTION
        max_km = (max_rough_minutes / 60.0) * AVG_ROAD_SPEED_KMH / truck_speed_factor

        ranked = self.nearest_by_distance(job_lat, job_lng)
        if concrete_mix:
            ranked = [p for p in ranked if concrete_mix in p["supported_mix_codes"]]
        viable = [p for p in ranked if p["distance_km"] <= max_km]

        if not viable:
            # Fallback: return top 3 even if distance is marginal
            viable = ranked[:3]
            logger.warning(
                f"No plants within {max_km:.0f} km of ({job_lat:.4f}, {job_lng:.4f}). "
                f"Returning {len(viable)} closest regardless."
            )

        result = viable[:top_n]
        logger.info(
            f"PlantLocator: {len(result)} candidates for job at "
            f"({job_lat:.4f}, {job_lng:.4f}) within {concrete_limit_minutes} min window"
        )
        return result
