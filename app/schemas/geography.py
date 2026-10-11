"""Typed API schemas for the Country -> State -> City catalogue."""
from typing import List, Optional

from pydantic import ConfigDict, Field, field_validator

from app.schemas import CatalogueInput, CatalogueName, OrganizationID, RegionCreate


class CountryCodeInput(CatalogueInput):
    code: str = Field(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")

    @field_validator("code")
    @classmethod
    def validate_iso_country_code(cls, value: str) -> str:
        return RegionCreate.validate_country(value)


class CountryCreate(CountryCodeInput):
    name: CatalogueName
    organization_id: OrganizationID


class CountryOut(CountryCodeInput):
    model_config = ConfigDict(from_attributes=True)
    name: CatalogueName
    organization_id: str


class StateCreate(CatalogueInput):
    organization_id: OrganizationID
    country_code: str = Field(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    name: CatalogueName

    @field_validator("country_code")
    @classmethod
    def validate_country_code(cls, value: str) -> str:
        return RegionCreate.validate_country(value)


class StateOut(CatalogueInput):
    model_config = ConfigDict(from_attributes=True)
    id: str
    country_code: str
    name: CatalogueName
    organization_id: Optional[str] = None


class CityCreate(CatalogueInput):
    state_id: str = Field(min_length=1, max_length=100)
    name: CatalogueName
    timezone: str = Field(min_length=1, max_length=100)
    country_code: Optional[str] = Field(
        default=None, min_length=2, max_length=2, pattern=r"^[A-Z]{2}$",
        description="Optional country assertion; when present it must match the state's country.",
    )

    @field_validator("timezone")
    @classmethod
    def validate_iana_timezone(cls, value: str) -> str:
        return RegionCreate.validate_timezone(value)

    @field_validator("country_code")
    @classmethod
    def validate_country_code(cls, value: Optional[str]) -> Optional[str]:
        return RegionCreate.validate_country(value) if value is not None else None


class CityOut(CatalogueInput):
    model_config = ConfigDict(from_attributes=True)
    id: str
    state_id: str
    name: CatalogueName
    timezone: str
    organization_id: Optional[str] = None


class CountryPage(CatalogueInput):
    items: List[CountryOut]
    total: int
    limit: int
    offset: int


class StatePage(CatalogueInput):
    items: List[StateOut]
    total: int
    limit: int
    offset: int


class CityPage(CatalogueInput):
    items: List[CityOut]
    total: int
    limit: int
    offset: int
