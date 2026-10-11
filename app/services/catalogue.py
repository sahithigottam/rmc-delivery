"""Transactional catalogue writes and public resource representations."""
import hashlib
import json
import logging
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Business, Brand, CatalogueEvent, CatalogueIdempotency, OrganizationPlant, Plant, Region, brand_name_key
from app.schemas import BusinessOut, BrandOut, PlantOut, RegionOut

logger = logging.getLogger(__name__)


def catalogue_error(status: int, code: str, message: str, **details) -> HTTPException:
    logger.warning("Catalogue %s: %s", code, message)
    return HTTPException(status_code=status, detail={
        "code": code, "message": message, "details": details,
    })


def plant_dict(plant: Plant) -> dict:
    return {
        "id": plant.id, "name": plant.name,
        "organization_id": plant.organization_id,
        "city_id": plant.region.city_id,
        "state_id": plant.region.state_id,
        "administrative_area": plant.region.administrative_area,
        "brand_id": plant.brand_id, "brand": plant.brand.name,
        "region_id": plant.region_id, "region": plant.region_id,
        "address": plant.address, "lat": plant.lat, "lng": plant.lng,
        "active": plant.active, "supported_mix_codes": plant.supported_mix_codes,
        "country_code": plant.region.country_code,
        "timezone": plant.region.timezone,
        "calibration_status": plant.region.calibration_status,
        "version": plant.version,
        "brand_version": plant.brand.version, "region_version": plant.region.version,
        "created_at": plant.created_at, "updated_at": plant.updated_at,
    }


def plant_out(plant: Plant) -> PlantOut:
    data = plant_dict(plant)
    return plant_schema(data)


def plant_schema(data: dict) -> PlantOut:
    fields = {
        key: data[key] for key in PlantOut.model_fields if key != "location" and key in data
    }
    return PlantOut(
        **fields, location={"latitude": data["lat"], "longitude": data["lng"]},
    )


class CatalogueService:
    def __init__(self, db: Session, actor_user_id: str | None = None):
        self.db = db
        self.actor_user_id = actor_user_id

    def get(self, model, resource_id: str):
        resource = self.db.get(model, resource_id)
        if resource is None:
            raise catalogue_error(404, "CATALOGUE_NOT_FOUND", "Resource not found", id=resource_id)
        return resource

    def _references(self, values: dict) -> None:
        for field, model in [("brand_id", Brand), ("region_id", Region)]:
            if field in values and self.db.get(model, values[field]) is None:
                raise catalogue_error(422, "INVALID_REFERENCE", f"{field} does not exist", field=field)

    def _business(self, organization_id: str) -> None:
        if self.db.get(Business, organization_id) is None:
            raise catalogue_error(422, "INVALID_BUSINESS", "Register the Clerk organization as a business first")

    def _plant_owner(self, values: dict, resource: Plant | None = None) -> None:
        brand = self.get(Brand, values.get("brand_id", resource.brand_id if resource else None))
        if brand.organization_id is None:
            raise catalogue_error(422, "UNOWNED_BRAND", "Assign the legacy brand to a business before adding plants")
        self._business(brand.organization_id)
        if resource is not None and resource.organization_id not in (None, brand.organization_id):
            raise catalogue_error(409, "OWNERSHIP_CONFLICT", "A plant cannot move to another business's brand")
        if resource is not None and resource.organization_id is None:
            conflict = self.db.query(OrganizationPlant).filter(
                OrganizationPlant.plant_id == resource.id,
                OrganizationPlant.organization_id != brand.organization_id,
            ).first()
            if conflict is not None:
                raise catalogue_error(409, "OWNERSHIP_CONFLICT", "Review conflicting legacy plant assignments before assigning ownership")
        values["organization_id"] = brand.organization_id
        region = self.get(Region, values.get("region_id", resource.region_id if resource else None))
        if region.organization_id != brand.organization_id:
            raise catalogue_error(422, "LOCATION_OWNER_MISMATCH", "Plant region and brand must belong to the same business")
        if region.city_id is None:
            raise catalogue_error(422, "CITY_REQUIRED", "Link the region to a structured city before adding or editing its plants")

    def _region_location(self, values: dict) -> None:
        from app.db.geography import City

        city = self.db.get(City, values["city_id"])
        if city is None:
            raise catalogue_error(422, "INVALID_REFERENCE", "city_id does not exist", field="city_id")
        if city.organization_id is None or city.state.organization_id != city.organization_id:
            raise catalogue_error(422, "UNOWNED_GEOGRAPHY", "City and state must belong to the same business")
        values["organization_id"] = city.organization_id
        authoritative = {
            "country_code": city.state.country_code,
            "administrative_area": city.state.name,
            "timezone": city.timezone,
        }
        for field, value in authoritative.items():
            if values.get(field) is not None and values[field] != value:
                raise catalogue_error(422, "LOCATION_MISMATCH", f"{field} disagrees with the selected city")
            values[field] = value

    @staticmethod
    def _values(body: BaseModel, partial: bool = False) -> dict:
        values = body.model_dump(exclude_unset=partial)
        values.pop("version", None)
        if "location" in values:
            location = values.pop("location")
            values.update(lat=location["latitude"], lng=location["longitude"])
        return values

    def create(self, kind: str, body: BaseModel, key: str) -> BaseModel:
        model, schema, prefix = {
            "plant": (Plant, plant_out, "plant"),
            "brand": (Brand, BrandOut.model_validate, "brand"),
            "region": (Region, RegionOut.model_validate, "region"),
            "business": (Business, BusinessOut.model_validate, "business"),
        }[kind]
        digest = hashlib.sha256(json.dumps(
            body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        prior = self.db.get(CatalogueIdempotency, key)
        if prior is not None:
            if prior.entity_type != kind or prior.request_hash != digest:
                raise catalogue_error(409, "IDEMPOTENCY_CONFLICT", "Key was used for a different request")
            output = {"plant": PlantOut, "brand": BrandOut, "region": RegionOut, "business": BusinessOut}[kind]
            return output.model_validate(prior.response_data)
        values = self._values(body)
        if kind == "plant":
            self._references(values)
            self._plant_owner(values)
        elif kind == "brand":
            self._business(values["organization_id"])
            values["name_key"] = brand_name_key(values["name"], values["organization_id"])
        elif kind == "region":
            self._region_location(values)
            values["calibration_status"] = "uncalibrated"
        resource_id = values.pop("id") if kind == "business" else f"{prefix}_{uuid4().hex}"
        resource = model(id=resource_id, **values)
        try:
            self.db.add(resource)
            self.db.flush()
            response = schema(resource)
            self.db.add(CatalogueEvent(
                entity_type=kind, entity_id=resource.id, action="created",
                data={"after": response.model_dump(mode="json")},
                actor_user_id=self.actor_user_id,
                organization_id=resource.id if kind == "business" else getattr(resource, "organization_id", None),
            ))
            self.db.add(CatalogueIdempotency(
                key=key, entity_type=kind, request_hash=digest,
                response_data=response.model_dump(mode="json"),
            ))
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            prior = self.db.get(CatalogueIdempotency, key)
            if prior is not None and prior.entity_type == kind and prior.request_hash == digest:
                output = {"plant": PlantOut, "brand": BrandOut, "region": RegionOut, "business": BusinessOut}[kind]
                return output.model_validate(prior.response_data)
            raise catalogue_error(409, "CATALOGUE_CONFLICT", "Duplicate name, idempotency key, or conflicting resource") from exc
        logger.info("Catalogue %s created: %s", kind, resource.id)
        return response

    def patch(self, kind: str, resource_id: str, body: BaseModel) -> BaseModel:
        model, schema = {
            "plant": (Plant, plant_out),
            "brand": (Brand, BrandOut.model_validate),
            "region": (Region, RegionOut.model_validate),
            "business": (Business, BusinessOut.model_validate),
        }[kind]
        resource = self.get(model, resource_id)
        before = schema(resource).model_dump(mode="json")
        values = self._values(body, partial=True)
        if kind == "plant":
            self._references(values)
            if "brand_id" in values or "region_id" in values:
                self._plant_owner(values, resource)
        elif kind == "brand":
            owner = values.get("organization_id", resource.organization_id)
            if owner is not None:
                self._business(owner)
            if resource.organization_id is not None and owner != resource.organization_id:
                raise catalogue_error(409, "OWNERSHIP_CONFLICT", "Brand ownership cannot be transferred between businesses")
            if resource.organization_id is None and owner is not None:
                conflict = self.db.query(OrganizationPlant).join(
                    Plant, Plant.id == OrganizationPlant.plant_id,
                ).filter(
                    Plant.brand_id == resource.id,
                    OrganizationPlant.organization_id != owner,
                ).first()
                if conflict is not None:
                    raise catalogue_error(409, "OWNERSHIP_CONFLICT", "This legacy brand has plants assigned to another business; review them first")
            values["name_key"] = brand_name_key(values.get("name", resource.name), owner)
        elif kind == "region":
            self._region_location(values)
            if resource.organization_id not in (None, values["organization_id"]):
                raise catalogue_error(409, "OWNERSHIP_CONFLICT", "Region cannot move to another business")
            if self.db.query(Plant).filter(
                Plant.region_id == resource.id,
                Plant.organization_id.is_not(None),
                Plant.organization_id != values["organization_id"],
            ).first() is not None:
                raise catalogue_error(409, "OWNERSHIP_CONFLICT", "Region is used by another business's plants")
            # Metadata changes must not claim the old area's calibration still applies.
            values["calibration_status"] = "uncalibrated"
        expected = body.version
        try:
            changed = self.db.execute(
                update(model).where(model.id == resource_id, model.version == expected)
                .values(**values, version=expected + 1),
                execution_options={"synchronize_session": False},
            )
            if changed.rowcount != 1:
                self.db.rollback()
                current = self.get(model, resource_id)
                raise catalogue_error(409, "VERSION_CONFLICT", "Resource has changed", current_version=current.version)
            self.db.expire_all()
            response = schema(self.get(model, resource_id))
            self.db.add(CatalogueEvent(
                entity_type=kind, entity_id=resource_id, action="updated",
                data={"before": before, "after": response.model_dump(mode="json")},
                actor_user_id=self.actor_user_id,
                organization_id=resource.id if kind == "business" else getattr(resource, "organization_id", None),
            ))
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise catalogue_error(409, "CATALOGUE_CONFLICT", "Conflicting resource") from exc
        logger.info("Catalogue %s updated: %s version %s", kind, resource_id, expected + 1)
        return response
