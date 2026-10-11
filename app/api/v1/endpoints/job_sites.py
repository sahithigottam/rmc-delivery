"""Shared company address book with explicit tenant checks and audited writes."""
import hashlib
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.endpoints.plants import idempotency_key
from app.auth import Principal, require_plant_admin
from app.config import settings
from app.db import get_db
from app.db.models import CatalogueEvent, CatalogueIdempotency, JobSite
from app.schemas.job_sites import JobSiteCreate, JobSiteOut, JobSitePage, JobSiteUpdate
from app.services.catalogue import catalogue_error

router = APIRouter(prefix="/job-sites", tags=["job sites"])


def site_out(site: JobSite) -> JobSiteOut:
    return JobSiteOut(
        **{key: getattr(site, key) for key in JobSiteOut.model_fields if key != "location"},
        location={"latitude": site.lat, "longitude": site.lng} if site.lat is not None else None,
    )


def get_owned(db: Session, site_id: str, principal: Principal) -> JobSite:
    site = db.get(JobSite, site_id)
    if site is None:
        raise catalogue_error(404, "JOB_SITE_NOT_FOUND", "Job site not found")
    if site.organization_id != principal.organization_id:
        raise catalogue_error(403, "JOB_SITE_FORBIDDEN", "Cannot access another company's job site")
    return site


def audit(db: Session, site: JobSite, principal: Principal, action: str, data: dict) -> None:
    db.add(CatalogueEvent(
        entity_type="job_site", entity_id=site.id, action=action, data=data,
        actor_user_id=principal.user_id, organization_id=principal.organization_id,
    ))


@router.get("", response_model=JobSitePage)
def list_sites(
    active_only: bool = True,
    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_plant_admin),
) -> JobSitePage:
    query = db.query(JobSite).filter(JobSite.organization_id == principal.organization_id)
    if active_only:
        query = query.filter(JobSite.active.is_(True))
    return JobSitePage(
        items=[site_out(site) for site in query.order_by(JobSite.name, JobSite.id).offset(offset).limit(limit)],
        total=query.count(), limit=limit, offset=offset,
    )


@router.get("/{site_id}", response_model=JobSiteOut)
def get_site(
    site_id: str, db: Session = Depends(get_db),
    principal: Principal = Depends(require_plant_admin),
) -> JobSiteOut:
    return site_out(get_owned(db, site_id, principal))


@router.post("", response_model=JobSiteOut, status_code=201)
def create_site(
    body: JobSiteCreate, response: Response,
    key: str = Depends(idempotency_key), db: Session = Depends(get_db),
    principal: Principal = Depends(require_plant_admin),
) -> JobSiteOut:
    digest = hashlib.sha256(json.dumps({
        "organization_id": principal.organization_id,
        "body": body.model_dump(mode="json"),
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def replay(prior: CatalogueIdempotency) -> JobSiteOut:
        if prior.entity_type != "job_site" or prior.request_hash != digest:
            raise catalogue_error(409, "IDEMPOTENCY_CONFLICT", "Key was used for a different request")
        return JobSiteOut.model_validate(prior.response_data)

    prior = db.get(CatalogueIdempotency, key)
    if prior is not None:
        result = replay(prior)
    else:
        values = body.model_dump(exclude={"location"})
        site = JobSite(
            id=f"site_{uuid4().hex}", organization_id=principal.organization_id,
            created_by_user_id=principal.user_id, updated_by_user_id=principal.user_id,
            lat=body.location.latitude if body.location else None,
            lng=body.location.longitude if body.location else None, **values,
        )
        try:
            db.add(site)
            db.flush()
            result = site_out(site)
            audit(db, site, principal, "created", {"after": result.model_dump(mode="json")})
            db.add(CatalogueIdempotency(
                key=key, entity_type="job_site", request_hash=digest,
                response_data=result.model_dump(mode="json"),
            ))
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            prior = db.get(CatalogueIdempotency, key)
            if prior is None:
                raise catalogue_error(409, "JOB_SITE_CONFLICT", "Conflicting job-site create") from exc
            result = replay(prior)
    response.headers["Location"] = f"{settings.api_v1_prefix}/job-sites/{result.id}"
    return result


@router.patch("/{site_id}", response_model=JobSiteOut)
def patch_site(
    site_id: str, body: JobSiteUpdate, db: Session = Depends(get_db),
    principal: Principal = Depends(require_plant_admin),
) -> JobSiteOut:
    site = get_owned(db, site_id, principal)
    before = site_out(site).model_dump(mode="json")
    values = body.model_dump(exclude_unset=True, exclude={"version", "location"})
    if "location" in body.model_fields_set:
        values.update(
            lat=body.location.latitude if body.location else None,
            lng=body.location.longitude if body.location else None,
        )
    values.update(version=body.version + 1, updated_by_user_id=principal.user_id)
    try:
        changed = db.execute(update(JobSite).where(
            JobSite.id == site_id, JobSite.organization_id == principal.organization_id,
            JobSite.version == body.version,
        ).values(**values), execution_options={"synchronize_session": False})
        if changed.rowcount != 1:
            db.rollback()
            current = get_owned(db, site_id, principal)
            raise catalogue_error(409, "VERSION_CONFLICT", "Job site changed", current_version=current.version)
        db.expire_all()
        site = get_owned(db, site_id, principal)
        result = site_out(site)
        audit(db, site, principal, "updated", {"before": before, "after": result.model_dump(mode="json")})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise catalogue_error(409, "JOB_SITE_CONFLICT", "Conflicting job-site update") from exc
    return result
