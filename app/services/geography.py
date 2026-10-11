"""Audited deletion of geographic records without cascading into user data."""
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.geography import BusinessCountry, City, State
from app.db.models import CatalogueEvent, JobSite, Plant, Region
from app.schemas import RegionOut
from app.schemas.geography import CityOut, CountryOut, StateOut
from app.services.catalogue import catalogue_error


def delete_unused_geography(
    db: Session, kind: str, resource_id: str, actor_user_id: str,
    organization_id: str | None = None,
) -> None:
    model, schema, references = {
        "country": (BusinessCountry, CountryOut, [
            (State, State.country_code, "states"),
            (Region, Region.country_code, "regions"),
            (JobSite, JobSite.country_code, "job sites"),
        ]),
        "state": (State, StateOut, [(City, City.state_id, "cities")]),
        "city": (City, CityOut, [(Region, Region.city_id, "regions")]),
        "region": (Region, RegionOut, [(Plant, Plant.region_id, "plants")]),
    }[kind]
    resource = db.get(model, (organization_id, resource_id) if kind == "country" else resource_id)
    if resource is None:
        raise catalogue_error(404, "GEOGRAPHY_NOT_FOUND", "Geographic record not found")
    for child, column, label in references:
        query = db.query(child).filter(column == resource_id)
        if kind == "country":
            query = query.filter(child.organization_id == organization_id)
        if query.first() is not None:
            raise catalogue_error(
                409, "GEOGRAPHY_IN_USE", f"Cannot delete {kind}: it is referenced by {label}",
                referenced_by=label,
            )
    before = schema.model_validate(resource).model_dump(mode="json")
    try:
        db.delete(resource)
        db.add(CatalogueEvent(
            entity_type=kind, entity_id=resource_id, action="deleted",
            data={"before": before}, actor_user_id=actor_user_id,
            organization_id=resource.organization_id,
        ))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise catalogue_error(
            409, "GEOGRAPHY_IN_USE", "Geographic record is referenced; reload before retrying",
        ) from exc
