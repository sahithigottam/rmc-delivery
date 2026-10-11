"""Authenticated reads and platform-owner writes for geographic reference data."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Principal, get_current_principal, require_super_admin
from app.db.database import get_db
from app.db.geography import BusinessCountry, City, Country, State
from app.db.models import Business, CatalogueEvent
from app.services.catalogue import catalogue_error
from app.services.geography import delete_unused_geography
from app.schemas.geography import (
    CityCreate, CityOut, CityPage, CountryCreate, CountryOut, CountryPage,
    StateCreate, StateOut, StatePage,
)

router = APIRouter(tags=["geography"])


def scope(principal: Principal, organization_id: Optional[str]) -> Optional[str]:
    if not principal.is_super_admin:
        if organization_id is not None and organization_id != principal.organization_id:
            raise catalogue_error(403, "GEOGRAPHY_FORBIDDEN", "Cannot access another business's geography")
        return principal.organization_id
    return organization_id


def check_owner(resource, principal: Principal) -> None:
    if not principal.is_super_admin and resource.organization_id != principal.organization_id:
        raise catalogue_error(403, "GEOGRAPHY_FORBIDDEN", "Cannot access another business's geography")


@router.delete("/countries/{country_code}", status_code=204)
def delete_country(
    country_code: str, organization_id: str, db: Session = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
) -> Response:
    delete_unused_geography(db, "country", country_code, principal.user_id, organization_id)
    return Response(status_code=204)


@router.delete("/states/{state_id}", status_code=204)
def delete_state(
    state_id: str, db: Session = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
) -> Response:
    delete_unused_geography(db, "state", state_id, principal.user_id)
    return Response(status_code=204)


@router.delete("/cities/{city_id}", status_code=204)
def delete_city(
    city_id: str, db: Session = Depends(get_db),
    principal: Principal = Depends(require_super_admin),
) -> Response:
    delete_unused_geography(db, "city", city_id, principal.user_id)
    return Response(status_code=204)


def _duplicate() -> HTTPException:
    return catalogue_error(409, "GEOGRAPHY_CONFLICT", "A geography record with this key already exists")


def _audit(db: Session, kind: str, entity_id: str, data: dict, principal: Principal) -> None:
    db.add(CatalogueEvent(
        entity_type=kind, entity_id=entity_id, action="created",
        data={"after": data}, actor_user_id=principal.user_id,
        organization_id=data.get("organization_id"),
    ))


@router.get("/countries", response_model=CountryPage)
def list_countries(
    organization_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _principal: Principal = Depends(get_current_principal),
) -> CountryPage:
    query = db.query(BusinessCountry)
    owner = scope(_principal, organization_id)
    if owner is not None:
        query = query.filter(BusinessCountry.organization_id == owner)
    return CountryPage(
        items=[CountryOut.model_validate(row) for row in
               query.order_by(BusinessCountry.organization_id, BusinessCountry.code).offset(offset).limit(limit).all()],
        total=query.count(), limit=limit, offset=offset,
    )


@router.get("/countries/{country_code}", response_model=CountryOut)
def get_country(
    country_code: str,
    organization_id: Optional[str] = None,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(get_current_principal),
) -> CountryOut:
    owner = scope(_principal, organization_id)
    if owner is None:
        raise catalogue_error(422, "BUSINESS_REQUIRED", "Select organization_id for a country detail")
    country = db.get(BusinessCountry, (owner, country_code))
    if country is None:
        raise HTTPException(status_code=404, detail=f"Country '{country_code}' not found")
    return CountryOut.model_validate(country)


@router.post("/countries", response_model=CountryOut, status_code=201)
def create_country(
    body: CountryCreate,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_super_admin),
) -> CountryOut:
    if db.get(Business, body.organization_id) is None:
        raise catalogue_error(422, "INVALID_BUSINESS", "Register the business first")
    if db.get(BusinessCountry, (body.organization_id, body.code)) is not None:
        raise _duplicate()
    if db.get(Country, body.code) is None:
        db.add(Country(code=body.code, name=body.name))
        db.flush()
    country = BusinessCountry(code=body.code, name=body.name, organization_id=body.organization_id)
    db.add(country)
    try:
        db.flush()
        _audit(db, "country", country.code, body.model_dump(mode="json"), _principal)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _duplicate() from exc
    db.refresh(country)
    return CountryOut.model_validate(country)


@router.get("/states", response_model=StatePage)
def list_states(
    organization_id: Optional[str] = None,
    country_code: Optional[str] = Query(None, min_length=2, max_length=2, pattern=r"^[A-Z]{2}$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _principal: Principal = Depends(get_current_principal),
) -> StatePage:
    query = db.query(State)
    owner = scope(_principal, organization_id)
    if owner is not None:
        query = query.filter(State.organization_id == owner)
    if country_code is not None:
        query = query.filter(State.country_code == country_code)
    return StatePage(
        items=[StateOut.model_validate(row) for row in
               query.order_by(State.country_code, State.name, State.id)
               .offset(offset).limit(limit).all()],
        total=query.count(), limit=limit, offset=offset,
    )


@router.get("/states/{state_id}", response_model=StateOut)
def get_state(
    state_id: str,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(get_current_principal),
) -> StateOut:
    state = db.get(State, state_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"State '{state_id}' not found")
    check_owner(state, _principal)
    return StateOut.model_validate(state)


@router.post("/states", response_model=StateOut, status_code=201)
def create_state(
    body: StateCreate,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_super_admin),
) -> StateOut:
    if db.get(BusinessCountry, (body.organization_id, body.country_code)) is None:
        raise HTTPException(
            status_code=404, detail=f"Country '{body.country_code}' not found",
        )
    if db.query(State.id).filter(
        State.country_code == body.country_code,
        State.organization_id == body.organization_id,
        func.lower(State.name) == body.name.casefold(),
    ).first() is not None:
        raise _duplicate()
    state = State(country_code=body.country_code, name=body.name, organization_id=body.organization_id)
    db.add(state)
    try:
        db.flush()
        _audit(db, "state", state.id, body.model_dump(mode="json"), _principal)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _duplicate() from exc
    db.refresh(state)
    return StateOut.model_validate(state)


@router.get("/cities", response_model=CityPage)
def list_cities(
    organization_id: Optional[str] = None,
    country_code: Optional[str] = Query(None, min_length=2, max_length=2, pattern=r"^[A-Z]{2}$"),
    state_id: Optional[str] = Query(None, min_length=1, max_length=100),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _principal: Principal = Depends(get_current_principal),
) -> CityPage:
    query = db.query(City)
    owner = scope(_principal, organization_id)
    if owner is not None:
        query = query.filter(City.organization_id == owner)
    if state_id is not None:
        query = query.filter(City.state_id == state_id)
    if country_code is not None:
        query = query.join(State, City.state_id == State.id).filter(
            State.country_code == country_code,
        )
    return CityPage(
        items=[CityOut.model_validate(row) for row in
               query.order_by(City.state_id, City.name, City.id)
               .offset(offset).limit(limit).all()],
        total=query.count(), limit=limit, offset=offset,
    )


@router.get("/cities/{city_id}", response_model=CityOut)
def get_city(
    city_id: str,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(get_current_principal),
) -> CityOut:
    city = db.get(City, city_id)
    if city is None:
        raise HTTPException(status_code=404, detail=f"City '{city_id}' not found")
    check_owner(city, _principal)
    return CityOut.model_validate(city)


@router.post("/cities", response_model=CityOut, status_code=201)
def create_city(
    body: CityCreate,
    db: Session = Depends(get_db),
    _principal: Principal = Depends(require_super_admin),
) -> CityOut:
    state = db.get(State, body.state_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"State '{body.state_id}' not found")
    if state.organization_id is None:
        raise catalogue_error(422, "UNOWNED_GEOGRAPHY", "Assign the legacy state to a business first")
    if body.country_code is not None and body.country_code != state.country_code:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Country '{body.country_code}' does not match state "
                f"'{body.state_id}' country '{state.country_code}'"
            ),
        )
    if db.query(City.id).filter(
        City.state_id == body.state_id,
        func.lower(City.name) == body.name.casefold(),
    ).first() is not None:
        raise _duplicate()
    city = City(state_id=state.id, name=body.name, timezone=body.timezone, organization_id=state.organization_id)
    db.add(city)
    try:
        db.flush()
        _audit(db, "city", city.id, {**body.model_dump(mode="json"), "organization_id": city.organization_id}, _principal)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _duplicate() from exc
    db.refresh(city)
    return CityOut.model_validate(city)
