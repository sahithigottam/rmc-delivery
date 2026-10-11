"""Database-backed plant catalogue and dispatch planning."""
import asyncio
import logging
import time
from typing import Optional

from cachetools import TTLCache
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.auth import Principal, get_current_principal, require_plant_admin, require_super_admin
from app.config import settings
from app.db import get_db
from app.db.models import Brand, Plant
from app.dependencies import get_prediction_service
from app.schemas import (
    BrandAnalysisRequest, BrandAnalysisResponse, PlantCreate, PlantOut,
    PlantPage, PlantPredictionResult, PlantUpdate,
)
from app.services.catalogue import CatalogueService, catalogue_error, plant_out, plant_schema
from app.services.llm_analyzer import LLMAnalyzer
from app.services.plant_locator import PlantLocator
from app.services.prediction import PredictionService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/plants", tags=["plants"])
_analysis_cache: TTLCache = TTLCache(maxsize=200, ttl=600)


def idempotency_key(
    key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=100),
) -> str:
    if not key.strip() or key != key.strip():
        raise catalogue_error(422, "INVALID_IDEMPOTENCY_KEY", "Use a non-blank idempotency key without surrounding whitespace")
    return key


@router.get("", response_model=PlantPage)
def list_plants(
    brand_id: Optional[str] = None, region_id: Optional[str] = None,
    country_code: Optional[str] = Query(None, pattern=r"^[A-Z]{2}$"),
    organization_id: Optional[str] = None,
    city_id: Optional[str] = None,
    state_id: Optional[str] = None,
    administrative_area: Optional[str] = None,
    active_only: bool = True,
    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    from app.db.models import Region

    query = db.query(Plant).join(Region, Plant.region_id == Region.id)
    if not principal.is_super_admin:
        if organization_id is not None and organization_id != principal.organization_id:
            raise HTTPException(status_code=403, detail="Cannot access another business's plants")
        organization_id = principal.organization_id
    if organization_id is not None:
        query = query.join(Brand, Brand.id == Plant.brand_id).filter(
            Plant.organization_id == organization_id,
            Brand.organization_id == organization_id,
            Region.organization_id == organization_id,
        )
    if active_only:
        query = query.filter(Plant.active.is_(True))
    if brand_id:
        query = query.filter(Plant.brand_id == brand_id)
    if region_id:
        query = query.filter(Plant.region_id == region_id)
    if country_code:
        query = query.filter(Region.country_code == country_code)
    if city_id:
        query = query.filter(Region.city_id == city_id)
    if state_id:
        from app.db.geography import City

        query = query.join(City, City.id == Region.city_id).filter(City.state_id == state_id)
    if administrative_area:
        query = query.filter(Region.administrative_area == administrative_area)
    return PlantPage(
        items=[plant_out(p) for p in query.order_by(Plant.id).offset(offset).limit(limit).all()],
        total=query.count(), limit=limit, offset=offset,
    )


@router.get("/{plant_id}", response_model=PlantOut)
def get_plant(
    plant_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    query = db.query(Plant).filter(Plant.id == plant_id)
    if not principal.is_super_admin:
        from app.db.models import Region

        query = query.join(Brand, Brand.id == Plant.brand_id).join(Region, Region.id == Plant.region_id).filter(
            Plant.organization_id == principal.organization_id,
            Brand.organization_id == principal.organization_id,
            Region.organization_id == principal.organization_id,
        )
    plant = query.first()
    if plant is None:
        raise HTTPException(status_code=404, detail="Plant not found")
    return plant_out(plant)


@router.post("", response_model=PlantOut, status_code=201)
def create_plant(
    body: PlantCreate, response: Response,
    key: str = Depends(idempotency_key), db: Session = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    result = CatalogueService(db, actor_user_id=principal.user_id).create("plant", body, key)
    response.headers["Location"] = f"{settings.api_v1_prefix}/plants/{result.id}"
    _analysis_cache.clear()
    return result


@router.patch("/{plant_id}", response_model=PlantOut)
def patch_plant(
    plant_id: str, body: PlantUpdate, db: Session = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    result = CatalogueService(db, actor_user_id=principal.user_id).patch("plant", plant_id, body)
    _analysis_cache.clear()
    return result


@router.post("/analyse", response_model=BrandAnalysisResponse)
async def analyse_brand(
    req: BrandAnalysisRequest,
    prediction_svc: PredictionService = Depends(get_prediction_service),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_plant_admin),
):
    address = req.job_site_data.get("display_name")
    if not isinstance(address, str) or not address.strip():
        raise catalogue_error(422, "INVALID_DESTINATION", "job_site_data.display_name must be a non-blank address")
    address = address.strip()
    brand = CatalogueService(db).get(Brand, req.brand_id)
    if brand.organization_id != principal.organization_id:
        raise HTTPException(status_code=403, detail="Cannot analyse another business's brand")
    loc = PlantLocator(
        db,
        organization_id=principal.organization_id,
    )
    candidates = [
        p for p in loc.plants
        if p["brand_id"] == req.brand_id
        and (not req.region_id or p["region_id"] == req.region_id)
        and (not req.country_code or p["country_code"] == req.country_code)
        and req.concrete_mix in p["supported_mix_codes"]
    ]
    if not candidates:
        raise catalogue_error(404, "NO_ELIGIBLE_PLANTS", "No active plants support the requested brand, region, country, and mix")
    countries = {p["country_code"] for p in candidates}
    if len(countries) != 1:
        raise catalogue_error(422, "COUNTRY_REQUIRED", "Select country_code or region_id for a brand operating in multiple countries")
    country = next(iter(countries))
    signature = tuple(
        (p["id"], p["version"], p["brand_version"], p["region_version"])
        for p in candidates
    )
    cache_key = (
        principal.organization_id, req.brand_id, req.region_id, address.lower(), req.concrete_mix,
        req.top_n, req.include_llm_analysis, country, signature, int(time.time()) // 600,
    )
    cached = _analysis_cache.get(cache_key)
    if cached is not None:
        return cached
    if len(candidates) > req.top_n:
        try:
            geo = await prediction_svc.geocode_job_site(address, country)
        except Exception as exc:
            raise catalogue_error(502, "DESTINATION_LOOKUP_FAILED", f"Could not resolve destination: {exc}") from exc
        ranked = loc.nearest_by_distance(
            geo["latitude"], geo["longitude"], brand_id=req.brand_id,
        )
        eligible = {p["id"] for p in candidates}
        candidates = [p for p in ranked if p["id"] in eligible]
    candidates = candidates[:req.top_n]

    async def predict_one(plant: dict) -> PlantPredictionResult:
        output = plant_schema(plant)
        try:
            result = await prediction_svc.predict_delivery(
                start_address=plant["address"], end_address=address,
                concrete_mix=req.concrete_mix, include_llm=False,
                country_code=country,
                local_timezone=plant["timezone"],
            )
            if result.get("error"):
                logger.warning("Prediction failed for plant %s", plant["id"])
                return PlantPredictionResult(plant=output, error=result["error"])
            pred, traffic = result["prediction"], result["traffic"]
            return PlantPredictionResult(
                plant=output, google_eta_minutes=traffic["google_eta_minutes"],
                adjusted_eta_minutes=pred["adjusted_eta_minutes"],
                remaining_life_minutes=pred["remaining_life_minutes"],
                buffer_depletion_rate=pred["buffer_depletion_rate"],
                delay_constant_used=pred["delay_constant_used"],
                risk_level=pred["risk_level"], success_probability=pred["success_probability"],
                recommendation=result["recommendation"],
                baseline_source=pred.get("baseline_source"),
                confidence_reason=pred.get("confidence_reason"),
                prediction_calibration_status=pred.get("calibration_status"),
            )
        except Exception as exc:
            logger.warning("Prediction failed for plant %s (%s)", plant["id"], type(exc).__name__)
            return PlantPredictionResult(plant=output, error=str(exc))

    results = await asyncio.gather(*(predict_one(p) for p in candidates))
    results.sort(key=lambda r: (
        r.remaining_life_minutes is None,
        -(r.remaining_life_minutes or 0), r.plant.id,
    ))
    valid = [r for r in results if r.error is None and r.remaining_life_minutes is not None]
    comparison = None
    if req.include_llm_analysis and valid:
        analyzer = LLMAnalyzer()
        try:
            comparison = await analyzer.compare_plants(
                plants_data=[{
                    "plant_name": r.plant.name, "plant_address": r.plant.address,
                    "google_eta": r.google_eta_minutes,
                    "adjusted_eta": r.adjusted_eta_minutes,
                    "remaining_life": r.remaining_life_minutes,
                    "risk_level": r.risk_level, "success_prob": r.success_probability,
                    "buffer_depletion": r.buffer_depletion_rate,
                } for r in valid],
                job_site=address, concrete_mix=req.concrete_mix,
            )
        except Exception as exc:
            logger.warning("LLM comparison failed (%s)", type(exc).__name__)
        finally:
            await analyzer.close()
    response = BrandAnalysisResponse(
        brand=brand.name, brand_id=brand.id, job_site_address=address,
        concrete_mix=req.concrete_mix, total_plants_analysed=len(results),
        results=results, best_plant_id=valid[0].plant.id if valid else None,
        llm_comparison=comparison,
    )
    if all(r.error is None for r in results):
        _analysis_cache[cache_key] = response
    return response
