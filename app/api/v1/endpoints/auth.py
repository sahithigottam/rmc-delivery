"""Verified identity and application capabilities for frontend navigation."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import Principal, get_current_principal

router = APIRouter(prefix="/auth", tags=["authentication"])


class CurrentUserResponse(BaseModel):
    user_id: str
    organization_id: str | None
    organization_role: str | None
    is_platform_admin: bool
    can_manage_catalogue: bool
    can_manage_businesses: bool
    can_manage_company_assignments: bool
    can_operate_trips: bool
    can_manage_job_sites: bool


@router.get("/me", response_model=CurrentUserResponse)
def current_user(
    principal: Principal = Depends(get_current_principal),
) -> CurrentUserResponse:
    return CurrentUserResponse(
        user_id=principal.user_id,
        organization_id=principal.organization_id,
        organization_role=principal.organization_role,
        is_platform_admin=principal.is_super_admin,
        can_manage_catalogue=principal.is_super_admin,
        can_manage_businesses=principal.is_super_admin,
        can_manage_company_assignments=principal.is_super_admin,
        can_operate_trips=principal.is_plant_admin,
        can_manage_job_sites=principal.is_plant_admin,
    )
