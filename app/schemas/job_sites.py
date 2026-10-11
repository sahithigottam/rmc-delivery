"""Company-scoped saved destination contracts."""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas import CatalogueInput, CatalogueName, PlantLocation, RegionCreate, UTCOutput


class JobSiteCreate(CatalogueInput):
    name: CatalogueName
    address: str = Field(min_length=3, max_length=500)
    location: Optional[PlantLocation] = None
    country_code: Optional[str] = Field(None, pattern=r"^[A-Z]{2}$")
    notes: Optional[str] = Field(None, max_length=5000)

    @field_validator("country_code")
    @classmethod
    def validate_country(cls, value: Optional[str]) -> Optional[str]:
        return RegionCreate.validate_country(value)


class JobSiteUpdate(JobSiteCreate):
    version: int = Field(ge=1)
    name: Optional[CatalogueName] = None
    address: Optional[str] = Field(None, min_length=3, max_length=500)
    active: Optional[bool] = None

    @model_validator(mode="after")
    def validate_changes(self) -> "JobSiteUpdate":
        changes = self.model_fields_set - {"version"}
        if not changes:
            raise ValueError("PATCH requires at least one changed field")
        if any(getattr(self, key) is None for key in changes & {"name", "address", "active"}):
            raise ValueError("name, address, and active cannot be cleared")
        return self


class JobSiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    organization_id: str
    name: str
    address: str
    location: Optional[PlantLocation]
    country_code: Optional[str]
    notes: Optional[str]
    active: bool
    version: int
    created_by_user_id: str
    updated_by_user_id: str
    created_at: UTCOutput
    updated_at: UTCOutput


class JobSitePage(BaseModel):
    items: list[JobSiteOut]
    total: int
    limit: int
    offset: int
