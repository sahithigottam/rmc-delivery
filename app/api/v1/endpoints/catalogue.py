"""Structured brand and region resources."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.api.v1.endpoints.plants import idempotency_key
from app.auth import Principal, get_current_principal, require_super_admin
from app.config import settings
from app.db import get_db
from app.db.models import Business, Brand, CatalogueEvent, OrganizationPlant, Plant, Region
from app.schemas import (
    BrandCreate, BrandOut, BrandPage, BrandUpdate,
    RegionCreate, RegionOut, RegionPage, RegionUpdate,
    BusinessCreate, BusinessOut, BusinessPage, BusinessUpdate,
)
from app.services.catalogue import CatalogueService
from app.services.catalogue import plant_out
from app.services.geography import delete_unused_geography

router = APIRouter(tags=["catalogue"])


class OrganizationPlantCreate(BaseModel):
    plant_id: str = Field(min_length=1, max_length=100)


@router.get("/organizations/{organization_id}/plants")
def organization_plants(
    organization_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if not principal.is_super_admin and organization_id != principal.organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")
    owned = (
        db.query(Plant).join(Brand, Brand.id == Plant.brand_id).join(Region, Region.id == Plant.region_id)
        .filter(Plant.organization_id == organization_id, Brand.organization_id == organization_id,
                Region.organization_id == organization_id)
        .order_by(Plant.id)
        .all()
    )
    return [{
        "organization_id": plant.organization_id,
        "plant": plant_out(plant),
    } for plant in owned]


@router.post("/organizations/{organization_id}/plants", status_code=201)
def assign_plant_to_organization(
    organization_id: str,
    body: OrganizationPlantCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    plant = db.get(Plant, body.plant_id)
    if plant is None:
        raise HTTPException(status_code=404, detail="Plant not found")
    if db.get(Business, organization_id) is None:
        raise HTTPException(status_code=422, detail="Register the business first")
    if plant.brand.organization_id != organization_id:
        raise HTTPException(status_code=409, detail="The plant's brand must belong to this business")
    if plant.region.organization_id != organization_id:
        raise HTTPException(status_code=409, detail="The plant's region must belong to this business")
    if plant.region.city_id is None:
        raise HTTPException(status_code=422, detail="Link the legacy plant's region to a city first")
    if plant.organization_id is not None:
        raise HTTPException(status_code=409, detail="Plant already has an exclusive business owner")
    conflicting = db.query(OrganizationPlant).filter(
        OrganizationPlant.plant_id == plant.id,
        OrganizationPlant.organization_id != organization_id,
    ).first()
    if conflicting is not None:
        raise HTTPException(status_code=409, detail="Legacy assignments conflict; review them before adopting this plant")
    assignment = db.query(OrganizationPlant).filter_by(
        organization_id=organization_id, plant_id=body.plant_id,
    ).first()
    changed = db.execute(update(Plant).where(
        Plant.id == plant.id, Plant.organization_id.is_(None),
    ).values(organization_id=organization_id, version=Plant.version + 1))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Plant ownership changed; reload before retrying")
    if assignment is None:
        assignment = OrganizationPlant(
            organization_id=organization_id, plant_id=body.plant_id,
            created_by_user_id=principal.user_id,
        )
        db.add(assignment)
    db.add(CatalogueEvent(
        entity_type="plant",
        entity_id=body.plant_id,
        action="ownership_assigned",
        data={"organization_id": organization_id},
        organization_id=organization_id,
        actor_user_id=principal.user_id,
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Plant ownership assignment conflicted") from exc
    db.refresh(assignment)
    return {
        "organization_id": assignment.organization_id,
        "plant": plant_out(assignment.plant),
        "created_by_user_id": assignment.created_by_user_id,
        "created_at": assignment.created_at,
    }


@router.delete("/organizations/{organization_id}/plants/{plant_id}", status_code=204)
def unassign_plant_from_organization(
    organization_id: str,
    plant_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    plant = db.get(Plant, plant_id)
    if plant is not None and plant.organization_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Owned plants cannot be unassigned or transferred; deactivate the plant instead",
        )
    assignment = db.query(OrganizationPlant).filter_by(
        organization_id=organization_id, plant_id=plant_id,
    ).first()
    if assignment is None:
        raise HTTPException(status_code=404, detail="Plant assignment not found")
    db.add(CatalogueEvent(
        entity_type="plant",
        entity_id=plant_id,
        action="unassigned_from_organization",
        data={"organization_id": organization_id},
        organization_id=organization_id,
        actor_user_id=principal.user_id,
    ))
    db.delete(assignment)
    db.commit()


@router.get("/brands", response_model=BrandPage)
def brands(
    organization_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    query = db.query(Brand)
    if not principal.is_super_admin:
        if organization_id is not None and organization_id != principal.organization_id:
            raise HTTPException(status_code=403, detail="Cannot access another business's brands")
        organization_id = principal.organization_id
    if organization_id is not None:
        query = query.filter(Brand.organization_id == organization_id)
    return BrandPage(
        items=[BrandOut.model_validate(r) for r in query.order_by(Brand.id).offset(offset).limit(limit)],
        total=query.count(), limit=limit, offset=offset,
    )


@router.get("/brands/{brand_id}", response_model=BrandOut)
def brand(
    brand_id: str, db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    resource = CatalogueService(db).get(Brand, brand_id)
    if not principal.is_super_admin and resource.organization_id != principal.organization_id:
        raise HTTPException(status_code=403, detail="Cannot access another business's brand")
    return resource


@router.post("/brands", response_model=BrandOut, status_code=201)
def create_brand(
    body: BrandCreate, response: Response,
    key: str = Depends(idempotency_key), db: Session = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    result = CatalogueService(db, actor_user_id=principal.user_id).create("brand", body, key)
    response.headers["Location"] = f"{settings.api_v1_prefix}/brands/{result.id}"
    return result


@router.patch("/brands/{brand_id}", response_model=BrandOut)
def patch_brand(
    brand_id: str, body: BrandUpdate, db: Session = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    return CatalogueService(db, actor_user_id=principal.user_id).patch("brand", brand_id, body)


@router.get("/regions", response_model=RegionPage)
def regions(
    organization_id: Optional[str] = None,
    country_code: Optional[str] = Query(None, pattern=r"^[A-Z]{2}$"),
    city_id: Optional[str] = None,
    state_id: Optional[str] = None,
    administrative_area: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    query = db.query(Region)
    if not principal.is_super_admin:
        if organization_id is not None and organization_id != principal.organization_id:
            raise HTTPException(status_code=403, detail="Cannot access another business's regions")
        organization_id = principal.organization_id
    if organization_id is not None:
        query = query.filter(Region.organization_id == organization_id)
    if country_code:
        query = query.filter(Region.country_code == country_code)
    if city_id:
        query = query.filter(Region.city_id == city_id)
    if state_id:
        from app.db.geography import City

        query = query.join(City, City.id == Region.city_id).filter(City.state_id == state_id)
    if administrative_area:
        query = query.filter(Region.administrative_area == administrative_area)
    return RegionPage(
        items=[RegionOut.model_validate(r) for r in query.order_by(Region.id).offset(offset).limit(limit)],
        total=query.count(), limit=limit, offset=offset,
    )


@router.get("/regions/{region_id}", response_model=RegionOut)
def region(
    region_id: str, db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    resource = CatalogueService(db).get(Region, region_id)
    if not principal.is_super_admin and resource.organization_id != principal.organization_id:
        raise HTTPException(status_code=403, detail="Cannot access another business's region")
    return resource


@router.post("/regions", response_model=RegionOut, status_code=201)
def create_region(
    body: RegionCreate, response: Response,
    key: str = Depends(idempotency_key), db: Session = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    result = CatalogueService(db, actor_user_id=principal.user_id).create("region", body, key)
    response.headers["Location"] = f"{settings.api_v1_prefix}/regions/{result.id}"
    return result


@router.patch("/regions/{region_id}", response_model=RegionOut)
def patch_region(
    region_id: str, body: RegionUpdate, db: Session = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    return CatalogueService(db, actor_user_id=principal.user_id).patch("region", region_id, body)


@router.delete("/regions/{region_id}", status_code=204)
def delete_region(
    region_id: str, db: Session = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
) -> Response:
    delete_unused_geography(db, "region", region_id, principal.user_id)
    return Response(status_code=204)


@router.get("/businesses", response_model=BusinessPage)
def businesses(
    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    query = db.query(Business)
    if not principal.is_super_admin:
        query = query.filter(Business.id == principal.organization_id)
    return BusinessPage(
        items=[BusinessOut.model_validate(r) for r in query.order_by(Business.id).offset(offset).limit(limit)],
        total=query.count(), limit=limit, offset=offset,
    )


@router.get("/businesses/{business_id}", response_model=BusinessOut)
def business(
    business_id: str, db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    if not principal.is_super_admin and business_id != principal.organization_id:
        raise HTTPException(status_code=403, detail="Cannot access another business")
    return CatalogueService(db).get(Business, business_id)


@router.post("/businesses", response_model=BusinessOut, status_code=201)
def create_business(
    body: BusinessCreate, response: Response,
    key: str = Depends(idempotency_key), db: Session = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    result = CatalogueService(db, actor_user_id=principal.user_id).create("business", body, key)
    response.headers["Location"] = f"{settings.api_v1_prefix}/businesses/{result.id}"
    return result


@router.patch("/businesses/{business_id}", response_model=BusinessOut)
def patch_business(
    business_id: str, body: BusinessUpdate, db: Session = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
):
    return CatalogueService(db, actor_user_id=principal.user_id).patch("business", business_id, body)
