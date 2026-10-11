"""
PredictionService — Orchestrates the full pre-trip prediction pipeline.

This is the only class the API endpoint talks to.
It owns no logic — it just wires the four specialist components together:

  1. GoogleMapsService  → live ETA + coordinates from addresses
  2. WeatherService     → real-time weather at job site
  3. DeliveryPredictor  → NZ baseline or uncalibrated Google/weather scoring
  4. LLMAnalyzer        → plain English dispatcher narrative

Usage (FastAPI endpoint):
    service = PredictionService(google_maps)
    result  = await service.predict_delivery(
        start_address="Holcim Avondale, 54 Patiki Rd",
        end_address="45 Queen Street, Auckland CBD",
        concrete_mix="GP",
        include_llm=True,
    )
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session

from app.rmc.predictor import DeliveryPredictor, DeliveryPrediction
from app.services.google_maps import GoogleMapsService
from app.services.llm_analyzer import LLMAnalyzer
from app.services.plant_locator import PlantLocator
from app.services.weather import WeatherService

logger = logging.getLogger(__name__)


class PredictionService:
    """
    End-to-end delivery prediction pipeline.

    Instantiate once per request (or as a singleton — stateless after init).
    The GoogleMapsService instance is injected via FastAPI dependency.
    WeatherService and LLMAnalyzer are lightweight and created internally.
    """

    def __init__(
        self,
        google_maps: GoogleMapsService,
        db: Optional[Session] = None,
        organization_id: Optional[str] = None,
    ):
        self._gmaps     = google_maps
        self._weather   = WeatherService()
        self._predictor = DeliveryPredictor()    # uses NZTA baselines
        self._llm       = LLMAnalyzer()
        self._locator   = PlantLocator(db, organization_id=organization_id)

    async def geocode_job_site(self, address: str, country_code: str) -> dict:
        return await self._gmaps.geocode_address(address, country_code=country_code)

    async def predict_delivery(
        self,
        start_address: str,
        end_address: str,
        concrete_mix: str = "GP",
        include_llm: bool = True,
        country_code: Optional[str] = None,
        local_timezone: Optional[str] = None,
    ) -> dict:
        """
        Full pre-trip prediction pipeline.

        Args:
            start_address : Plant or origin  e.g. "Holcim Avondale, 54 Patiki Rd"
            end_address   : Job site address e.g. "45 Queen Street, Auckland CBD"
            concrete_mix  : "GP" (90 min) | "HE" (60 min) | "RE" (120 min)
            include_llm   : Set False to skip Ollama call (faster, no narrative)
            country_code  : Optional ISO country restriction for both addresses

        Returns:
            Full prediction report dict. Shape is always identical regardless
            of whether LLM succeeded or fell back to template.
        """
        now           = datetime.now(timezone.utc)

        # ── Step 1: Google Directions ─────────────────────────────────
        # Single API call: geocodes addresses + returns live-traffic ETA + polyline
        logger.debug("Prediction requested")
        try:
            # Geocode both addresses first
            start_geo = await self._gmaps.geocode_address(start_address, country_code=country_code)
            end_geo   = await self._gmaps.geocode_address(end_address, country_code=country_code)
            resolved_country = country_code or end_geo.get("country_code")
            if resolved_country not in ("IN", "NZ"):
                raise ValueError("Select country_code IN or NZ; destination country could not be resolved or is unsupported")
            for geo in (start_geo, end_geo):
                if geo.get("country_code") and geo["country_code"] != resolved_country:
                    raise ValueError("Start and destination must belong to the selected country")
            zone = local_timezone or {"IN": "Asia/Kolkata", "NZ": "Pacific/Auckland"}[resolved_country]
            local_now = now.astimezone(ZoneInfo(zone))

            directions = await self._gmaps.get_directions(
                start_lat=start_geo["latitude"],
                start_lng=start_geo["longitude"],
                end_lat=end_geo["latitude"],
                end_lng=end_geo["longitude"],
                departure_time=int(now.timestamp()),
                traffic_model="pessimistic",    # worst-case for RMC safety
                alternatives=False,
            )
        except Exception as e:
            logger.error("Prediction dependency failed (%s)", type(e).__name__)
            return {"error": f"Google Directions API failed: {e}"}

        if not directions or directions.get("status") != "OK":
            error = (
                f"Google Directions returned no results "
                f"(status: {directions.get('status') if directions else 'no response'}). "
                f"Check addresses."
            )
            if directions and directions.get("error_message"):
                error += f" {directions['error_message']}"
            logger.error("Prediction Directions response unsuccessful")
            return {"error": error}

        route = directions["routes"][0]
        leg   = route["legs"][0]

        distance_m          = leg["distance"]["value"]
        duration_s          = leg["duration"]["value"]
        duration_traffic_s  = leg.get("duration_in_traffic", {}).get("value", duration_s)
        traffic_delay_s     = max(0, duration_traffic_s - duration_s)
        google_eta_min      = duration_traffic_s / 60.0

        start_lat = leg["start_location"]["lat"]
        start_lng = leg["start_location"]["lng"]
        end_lat   = leg["end_location"]["lat"]
        end_lng   = leg["end_location"]["lng"]

        resolved_start = leg.get("start_address", start_address)
        resolved_end   = leg.get("end_address",   end_address)
        polyline       = route.get("overview_polyline", {}).get("points")

        logger.info(
            f"Google: {distance_m/1000:.1f} km | "
            f"ETA: {google_eta_min:.0f} min | "
            f"Traffic delay: {traffic_delay_s/60:.0f} min"
        )

        # ── Step 2: Weather at job site ───────────────────────────────
        weather = await self._weather.get_weather(lat=end_lat, lng=end_lng, hours_ahead=3)

        # ── Step 3: Statistical prediction ───────────────────────────
        pred: DeliveryPrediction = self._predictor.predict(
            google_eta_minutes=google_eta_min,
            google_traffic_delay_s=traffic_delay_s,
            start_lat=start_lat, start_lng=start_lng,
            end_lat=end_lat,     end_lng=end_lng,
            departure_hour=local_now.hour,
            departure_day=local_now.weekday(),
            weather=weather,
            concrete_mix=concrete_mix,
            country_code=resolved_country,
        )

        # ── Step 4: LLM narrative ─────────────────────────────────────
        llm_result = None
        if include_llm:
            llm_result = await self._llm.analyze(
                pred,
                route_desc=f"{resolved_start} → {resolved_end}",
            )

        # ── Assemble response ─────────────────────────────────────────
        return {
            "input": {
                "start_address": resolved_start,
                "end_address":   resolved_end,
                "concrete_mix":  concrete_mix.upper(),
                "country_code": resolved_country,
                "timezone": zone,
                "departure_local": local_now.isoformat(),
            },
            "traffic": {
                "distance_km":            round(distance_m / 1000, 1),
                "google_eta_minutes":     round(google_eta_min, 1),
                "traffic_delay_minutes":  round(traffic_delay_s / 60, 1),
                "polyline":               polyline,
            },
            "prediction": {
                "success_probability":    pred.success_probability,
                "calibration_status": pred.calibration_status,
                "baseline_source": pred.baseline_source,
                "confidence_reason": pred.confidence_reason,
                "risk_level":             pred.risk_level.upper(),
                "confidence":             pred.confidence.upper(),
                "adjusted_eta_minutes":   round(pred.adjusted_eta_minutes, 1),
                "concrete_limit_minutes": pred.setting_time_minutes,
                "time_buffer_minutes":    round(pred.time_buffer_minutes, 1),
                # ── Buffer Depletion ─────────────────────────────────
                # remaining_life = window − (loading_time + travel)
                # RISK_LEVEL: HIGH when remaining_life_minutes < 15
                "remaining_life_minutes": round(pred.remaining_life_minutes, 1),
                "buffer_depletion_rate":  round(pred.buffer_depletion_rate, 3),
                "delay_constant_used":    pred.delay_constant_used,
                "duration_percentiles": {
                    "p50": pred.p50_duration_minutes,
                    "p75": pred.p75_duration_minutes,
                    "p90": pred.p90_duration_minutes,
                    "p95": pred.p95_duration_minutes,
                },
            },
            "weather": {
                "condition":    pred.weather_condition,
                "speed_impact": pred.weather_impact,
                "current":      weather.get("current", {}),
                "available": weather.get("available", True),
                "timezone": weather.get("timezone", "UTC"),
            },
            "risk_factors":   pred.risk_factors,
            "recommendation": pred.recommendation,
            "llm_analysis":   llm_result,
        }

    async def best_plant(
        self,
        job_site_address: str,
        concrete_mix: str = "GP",
        top_n: int = 5,
        country_code: Optional[str] = None,
    ) -> dict:
        """
        Find the best dispatching plant for a job site.

        Two-stage approach — free local filter first, Google only for finalists:
          Stage 1: PlantLocator.candidates_for_job() — Haversine filter, FREE, instant.
                   Eliminates plants that are physically too far to make the window.
          Stage 2: Google Directions — called only for the top N candidates.
                   Gives real traffic-adjusted ETAs for the finalists.

        This reduces Google API calls from 20 → top_n (default 5).
        Cost reduction: ~75% fewer API calls vs querying all plants.

        Args:
            job_site_address : Destination address (geocoded internally)
            concrete_mix     : "GP" (90 min) | "HE" (60 min) | "RE" (120 min)
            top_n            : Max plants to send to Google (default 5)

        Returns:
            {
              "best_plant": { id, name, brand, address, eta_minutes,
                              success_probability, risk_level, distance_km },
              "all_plants": [ same shape, NZ probability / India remaining-life ranking ]
            }
        """
        import asyncio
        from app.rmc.predictor import MIX_LIMITS

        # ── Stage 1: Free local pre-filter ────────────────────────────
        # Geocode job site once to get coordinates for Haversine
        try:
            job_geo = await self._gmaps.geocode_address(job_site_address, country_code=country_code)
            country = country_code or job_geo.get("country_code")
            if country not in ("IN", "NZ"):
                raise ValueError("Select country_code IN or NZ; destination country is unavailable or unsupported")
        except Exception as e:
            return {"error": f"Could not geocode job site: {e}"}

        concrete_limit = MIX_LIMITS.get(concrete_mix.upper(), 90)
        locator = self._locator
        if country == "NZ":
            candidates = locator.candidates_for_job(
                job_lat=job_geo["latitude"], job_lng=job_geo["longitude"],
                concrete_limit_minutes=concrete_limit, top_n=len(locator.plants),
                concrete_mix=concrete_mix,
            )
        else:
            candidates = locator.nearest_by_distance(job_geo["latitude"], job_geo["longitude"])
        candidates = [
            plant for plant in candidates if plant["country_code"] == country
            and concrete_mix in plant["supported_mix_codes"]
        ][:top_n]

        if not candidates:
            return {"error": "No viable plants found within delivery window distance"}

        logger.info(
            f"best_plant: {len(candidates)} candidates after local filter "
            f"(saved {20 - len(candidates)} Google API calls)"
        )

        # ── Stage 2: Google Directions for finalists only ─────────────
        async def _score_plant(plant: dict) -> Optional[dict]:
            result = await self.predict_delivery(
                start_address=plant["address"],
                end_address=job_site_address,
                concrete_mix=concrete_mix,
                include_llm=False,   # no LLM for comparison — speed matters here
                country_code=plant["country_code"],
                local_timezone=plant["timezone"],
            )
            if "error" in result:
                logger.warning(f"best_plant: skipping {plant['name']} — {result['error']}")
                return None
            return {
                "id":                   plant["id"],
                "name":                 plant["name"],
                "brand":                plant["brand"],
                "address":              result["input"]["start_address"],
                "distance_km":          plant["distance_km"],
                "eta_minutes":          result["traffic"]["google_eta_minutes"],
                "adjusted_eta_minutes": result["prediction"]["adjusted_eta_minutes"],
                "success_probability":  result["prediction"]["success_probability"],
                "risk_level":           result["prediction"]["risk_level"],
                "time_buffer_minutes":  result["prediction"]["time_buffer_minutes"],
                "remaining_life_minutes": result["prediction"]["remaining_life_minutes"],
                "calibration_status": result["prediction"]["calibration_status"],
                "baseline_source": result["prediction"]["baseline_source"],
                "confidence_reason": result["prediction"]["confidence_reason"],
            }

        results = await asyncio.gather(*[_score_plant(p) for p in candidates])
        valid = [r for r in results if r is not None]
        if not valid:
            return {"error": "No plants returned valid Google Directions results"}

        if country == "NZ":
            valid.sort(key=lambda r: r["success_probability"], reverse=True)
        else:
            valid.sort(key=lambda r: r["remaining_life_minutes"], reverse=True)
        return {
            "job_site":   job_site_address,
            "concrete_mix": concrete_mix.upper(),
            "best_plant": valid[0],
            "all_plants": valid,
        }

    async def close(self):
        """Cleanup. Called on app shutdown."""
        await self._weather.close()
        await self._llm.close()
