"""Company ownership is enforced by route and trip service queries."""
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.db.models import Route, Trip, TripEvent
from app.services.route import RouteService
from app.services.trip import TripService
from app.schemas import PositionUpdate


@pytest.fixture
def tenant_services():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        rows = []
        for organization_id in ("org-one", "org-two"):
            route = Route(
                organization_id=organization_id,
                created_by_user_id=f"creator-{organization_id}",
                start_address="Plant", start_lat=0, start_lng=0,
                end_address="Site", end_lat=1, end_lng=1,
                vehicle_type="rmc_truck", distance_meters=1000,
                duration_seconds=600,
            )
            db.add(route)
            db.flush()
            trip = Trip(
                organization_id=organization_id,
                created_by_user_id=f"creator-{organization_id}",
                route_id=route.id, status="pending",
                start_address="Plant", end_address="Site",
                start_lat=0, start_lng=0, end_lat=1, end_lng=1,
                vehicle_type="rmc_truck",
            )
            db.add(trip)
            db.flush()
            db.add(TripEvent(
                trip_id=trip.id, event_type="trip_dispatched",
                actor_user_id=f"creator-{organization_id}",
            ))
            rows.append((route.id, trip.id))
        db.commit()
        yield db, rows
    engine.dispose()


def test_route_service_cannot_read_another_organizations_route(tenant_services):
    db, rows = tenant_services
    route_service = RouteService(
        db, Mock(), organization_id="org-one", actor_user_id="user-one",
    )
    assert route_service.get_route(rows[0][0]) is not None
    with pytest.raises(HTTPException) as forbidden:
        route_service.get_route(rows[1][0])
    assert forbidden.value.status_code == 403
    assert [r.id for r in route_service.get_route_history()] == [rows[0][0]]


def test_trip_service_filters_reads_and_events_by_organization(tenant_services):
    db, rows = tenant_services
    trip_service = TripService(
        db, Mock(), organization_id="org-one", actor_user_id="user-one",
    )
    assert trip_service.get_trip(rows[0][1]).id == rows[0][1]
    assert [t.id for t in trip_service.get_all_trips()] == [rows[0][1]]
    assert [
        e.actor_user_id for e in trip_service.get_trip_events(rows[0][1])
    ] == ["creator-org-one"]
    with pytest.raises(HTTPException) as forbidden:
        trip_service.get_trip(rows[1][1])
    assert forbidden.value.status_code == 403
    with pytest.raises(HTTPException) as forbidden:
        trip_service.get_trip_events(rows[1][1])
    assert forbidden.value.status_code == 403


def test_archiving_terminal_trip_preserves_its_events_and_actor(tenant_services):
    db, rows = tenant_services
    trip = db.get(Trip, rows[0][1])
    trip.status = "completed"
    db.commit()
    trip_service = TripService(
        db, Mock(), organization_id="org-one", actor_user_id="admin-one",
    )

    trip_service.delete_trip(trip.id)

    archived = db.get(Trip, trip.id)
    assert archived.archived_at is not None
    assert archived.archived_by_user_id == "admin-one"
    assert db.query(TripEvent).filter_by(trip_id=trip.id).count() == 2
    assert [event.event_type for event in db.query(TripEvent).filter_by(
        trip_id=trip.id,
    ).order_by(TripEvent.id)] == ["trip_dispatched", "trip_archived"]
    assert trip_service.get_all_trips() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("is_platform_admin", [False, True])
async def test_gps_update_cannot_cross_active_organization_boundary(
    tenant_services, is_platform_admin,
):
    db, rows = tenant_services
    other_trip = db.get(Trip, rows[1][1])
    other_trip.status = "in_progress"
    db.commit()
    service = TripService(
        db, Mock(), organization_id="org-one", actor_user_id="user-one",
        is_super_admin=is_platform_admin,
    )
    with pytest.raises(HTTPException) as forbidden:
        await service.update_position(other_trip.id, PositionUpdate(lat=0.5, lng=0.5))
    assert forbidden.value.status_code == 403
    db.refresh(other_trip)
    assert other_trip.current_lat is None
    assert db.query(TripEvent).filter_by(trip_id=other_trip.id).count() == 1
