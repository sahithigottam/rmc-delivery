"""Completion radius and durable review-flag regression tests."""
import math
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import Route, Trip, TripEvent
from app.schemas import PositionUpdate, TripCompleteRequest
from app.services.trip import TripService
from app.api.v1.endpoints.trips import router
from app.dependencies import get_trip_service


@pytest.fixture
def trip_service(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        route = Route(
            start_address="Plant", start_lat=0, start_lng=0,
            end_address="Site", end_lat=0, end_lng=0, vehicle_type="rmc_truck",
        )
        db.add(route)
        db.flush()
        trip = Trip(
            route_id=route.id, status="in_progress",
            start_address="Plant", start_lat=0, start_lng=0,
            end_address="Site", end_lat=0, end_lng=0,
            current_lat=0, current_lng=0,
        )
        db.add(trip)
        db.commit()
        service = TripService(db, Mock())
        push = AsyncMock()
        monkeypatch.setattr("app.services.trip._push_event", push)
        yield service, trip, push
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("distance,review", [
    (0, False), (99.99, False), (100, False), (100.01, True), (150, True),
])
async def test_manual_completion_radius_boundary(trip_service, monkeypatch, distance, review):
    service, trip, push = trip_service
    monkeypatch.setattr(service, "_haversine", lambda *args: distance / 1000)
    response = await service.complete_trip(
        trip.id, TripCompleteRequest(success=True, notes="Poured"),
    )
    assert response.status == "completed"
    assert response.outcome == "succeeded"
    assert response.completion_review_required is review
    assert response.completion_distance_meters == pytest.approx(distance)
    assert bool(response.completion_review_reason) is review
    event = service.db.query(TripEvent).filter_by(event_type="trip_completed").one()
    assert event.data["completion_radius_meters"] == 100
    assert event.data["completion_review_required"] is review
    assert event.data["notes"] == "Poured"
    assert push.await_args.args[2]["completion_review_required"] is review

    service.db.expire_all()
    reloaded = TripService(service.db, Mock())._to_response(service._get_trip(trip.id))
    assert reloaded.completion_review_required is review
    assert reloaded.completion_distance_meters == pytest.approx(distance)


@pytest.mark.asyncio
@pytest.mark.parametrize("lat,lng", [(None, 0), (0, None), (None, None)])
async def test_missing_location_requires_review(trip_service, lat, lng):
    service, trip, _ = trip_service
    trip.current_lat, trip.current_lng = lat, lng
    response = await service.complete_trip(trip.id)
    assert response.status == "completed"
    assert response.completion_review_required is True
    assert response.completion_distance_meters is None
    assert "unavailable" in response.completion_review_reason


@pytest.mark.asyncio
@pytest.mark.parametrize("distance,completed", [
    (99.99, True), (100, True), (100.01, False), (150, False), (200, False),
])
async def test_auto_completion_uses_100_metre_radius(
    trip_service, monkeypatch, distance, completed,
):
    service, trip, _ = trip_service
    monkeypatch.setattr(service, "_haversine", lambda *args: distance / 1000)
    response = await service.update_position(trip.id, PositionUpdate(lat=0, lng=0))
    assert response.status == ("completed" if completed else "in_progress")
    assert response.completion_review_required is (False if completed else None)
    assert response.outcome == ("succeeded" if completed else None)


@pytest.mark.asyncio
async def test_real_coordinate_distance_and_review_persist_beyond_recent_events(trip_service):
    service, trip, _ = trip_service
    trip.current_lat = math.degrees(150 / 6_371_000)
    response = await service.complete_trip(trip.id)
    assert response.completion_distance_meters == pytest.approx(150)
    assert response.completion_review_required is True
    for _ in range(25):
        service._log_event(trip.id, "traffic_check", {})
    service.db.commit()
    service.db.expire_all()
    reloaded = service._to_response(service._get_trip(trip.id))
    assert reloaded.completion_review_required is True
    assert reloaded.completion_distance_meters == pytest.approx(150)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "cancelled"])
async def test_terminal_trip_cannot_be_completed_again(trip_service, status):
    service, trip, push = trip_service
    trip.status = status
    trip.outcome = "failed"
    service.db.commit()
    with pytest.raises(ValueError, match=f"Trip already {status}"):
        await service.complete_trip(trip.id, TripCompleteRequest(success=True))
    assert trip.outcome == "failed"
    assert service.db.query(TripEvent).count() == 0
    push.assert_not_awaited()


def test_historical_completion_review_is_unknown(trip_service):
    service, trip, _ = trip_service
    trip.status = "completed"
    service._log_event(trip.id, "trip_completed", {"auto_completed": False})
    service.db.commit()
    response = service._to_response(trip)
    assert response.completion_review_required is None
    assert response.completion_distance_meters is None


@pytest.mark.asyncio
async def test_delayed_position_preserves_original_time_and_normalizes_utc(trip_service):
    service, trip, push = trip_service
    captured_at = datetime.now(timezone.utc) - timedelta(hours=1)
    local_time = captured_at.astimezone(timezone(timedelta(hours=5, minutes=30)))
    response = await service.update_position(
        trip.id, PositionUpdate(lat=0.01, lng=0, captured_at=local_time),
    )
    assert response.current_position_at == captured_at
    assert response.current_position_at.utcoffset() == timedelta(0)
    event = service.db.query(TripEvent).filter_by(event_type="position_update").one()
    assert datetime.fromisoformat(event.data["captured_at"]) == captured_at
    assert event.data["captured_at"].endswith("+00:00")
    assert datetime.fromisoformat(event.data["received_at"]) > captured_at
    assert push.await_args.args[2]["captured_at"] == event.data["captured_at"]
    service.db.expire_all()
    fresh_service = TripService(service.db, Mock())
    assert fresh_service._to_response(fresh_service._get_trip(trip.id)).current_position_at == captured_at


@pytest.mark.asyncio
@pytest.mark.parametrize("seconds_older", [1, 0])
async def test_stale_or_duplicate_report_cannot_move_or_complete(trip_service, seconds_older):
    service, trip, push = trip_service
    captured_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    await service.update_position(
        trip.id, PositionUpdate(lat=0.01, lng=0, heading=90, captured_at=captured_at),
    )
    original_distance = trip.remaining_distance_meters
    push.reset_mock()
    service.db.expire_all()
    service = TripService(service.db, Mock())
    with pytest.raises(ValueError, match="stale or duplicated"):
        await service.update_position(
            trip.id, PositionUpdate(
                lat=0, lng=0, heading=180,
                captured_at=captured_at - timedelta(seconds=seconds_older),
            ),
        )
    service.db.refresh(trip)
    assert trip.current_lat == 0.01
    assert trip.heading == 90
    assert trip.status == "in_progress"
    assert trip.remaining_distance_meters == original_distance
    assert service.db.query(TripEvent).filter_by(event_type="position_rejected").count() == 1
    assert service.db.query(TripEvent).filter_by(event_type="trip_completed").count() == 0
    assert service._to_response(trip).current_position_at == captured_at
    push.assert_not_awaited()


@pytest.mark.asyncio
async def test_newer_delayed_report_is_accepted(trip_service):
    service, trip, _ = trip_service
    captured_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    await service.update_position(
        trip.id, PositionUpdate(lat=0.02, lng=0, captured_at=captured_at),
    )
    response = await service.update_position(
        trip.id, PositionUpdate(
            lat=0.01, lng=0, captured_at=captured_at + timedelta(minutes=1),
        ),
    )
    assert response.current_lat == 0.01
    assert response.current_position_at == captured_at + timedelta(minutes=1)


@pytest.mark.asyncio
async def test_missing_capture_time_uses_receipt_time(trip_service):
    service, trip, _ = trip_service
    before = datetime.now(timezone.utc)
    response = await service.update_position(trip.id, PositionUpdate(lat=0.01, lng=0))
    after = datetime.now(timezone.utc)
    assert before <= response.current_position_at <= after
    event = service.db.query(TripEvent).filter_by(event_type="position_update").one()
    assert event.data["captured_at"] == event.data["received_at"]


@pytest.mark.asyncio
async def test_old_report_cannot_overwrite_legacy_position_event(trip_service):
    service, trip, _ = trip_service
    captured_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    trip.current_lat = 0.01
    event = TripEvent(
        trip_id=trip.id, event_type="position_update",
        data={"lat": 0.01, "lng": 0},
        created_at=captured_at,
    )
    service.db.add(event)
    service.db.commit()
    with pytest.raises(ValueError, match="stale or duplicated"):
        await service.update_position(
            trip.id, PositionUpdate(
                lat=0, lng=0, captured_at=captured_at - timedelta(seconds=1),
            ),
        )
    assert service._to_response(trip).current_position_at == captured_at


@pytest.mark.asyncio
async def test_position_timestamp_validation_at_api_boundary(trip_service):
    service, trip, _ = trip_service
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_trip_service] = lambda: service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        path = f"/api/v1/trips/{trip.id}/position"
        for captured_at in ["not-a-time", "2026-01-01T12:00:00"]:
            response = await client.post(path, json={
                "lat": 0.01, "lng": 0, "captured_at": captured_at,
            })
            assert response.status_code == 422
        response = await client.post(path, json={
            "lat": 0, "lng": 0,
            "captured_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        })
        assert response.status_code == 400
        assert "future" in response.json()["detail"]
        assert trip.status == "in_progress"
        assert service._latest_position_time(trip.id) is None
        captured_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        valid = await client.post(path, json={
            "lat": 0.01, "lng": 0, "captured_at": captured_at,
        })
        assert valid.status_code == 200
        assert valid.json()["current_position_at"].endswith("Z")
        stale = await client.post(path, json={
            "lat": 0, "lng": 0, "captured_at": captured_at,
        })
        assert stale.status_code == 400
        assert "stale" in stale.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
@pytest.mark.parametrize("auto", [False, True])
async def test_completion_uses_actual_timer_not_projected_or_stale_status(trip_service, expired, auto):
    service, trip, _ = trip_service
    trip.batch_time = datetime.now(timezone.utc) - timedelta(minutes=100 if expired else 5)
    trip.load_max_life_minutes = 90
    trip.load_expiry_time = trip.batch_time + timedelta(minutes=90)
    trip.load_status = "fresh" if expired else "expired"
    service.db.commit()
    if auto:
        response = await service.update_position(trip.id, PositionUpdate(lat=0, lng=0))
    else:
        response = await service.complete_trip(trip.id)
    assert response.outcome == ("failed" if expired else "succeeded")
    assert response.load_status == ("expired" if expired else "fresh")
    event = service.db.query(TripEvent).filter_by(event_type="trip_completed").one()
    assert event.data["actual_load_status"] == response.load_status
    assert event.data["load_timer"]["effective_max_minutes"] == 90
    assert event.data["expiry_override"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("notes", [None, "", "   "])
async def test_expired_success_without_reason_rejected_without_mutation(trip_service, notes):
    service, trip, push = trip_service
    trip.batch_time = datetime.now(timezone.utc) - timedelta(minutes=100)
    trip.load_expiry_time = trip.batch_time + timedelta(minutes=90)
    trip.load_status = "fresh"
    service.db.commit()
    with pytest.raises(ValueError, match="reason is required"):
        await service.complete_trip(trip.id, TripCompleteRequest(success=True, notes=notes))
    assert trip.status == "in_progress"
    assert trip.outcome is None
    assert trip.load_status == "fresh"
    assert service.db.query(TripEvent).count() == 0
    push.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("off_site", [False, True])
async def test_expired_success_with_reason_is_durably_flagged(trip_service, off_site):
    service, trip, push = trip_service
    trip.batch_time = datetime.now(timezone.utc) - timedelta(minutes=100)
    trip.load_expiry_time = trip.batch_time + timedelta(minutes=90)
    if off_site:
        trip.current_lat = 0.01
    service.db.commit()
    response = await service.complete_trip(
        trip.id, TripCompleteRequest(success=True, notes="Operator reports a completed pour"),
    )
    assert response.status == "completed"
    assert response.outcome == "succeeded"
    assert response.load_status == "expired"
    assert response.completion_review_required is True
    assert "expired" in response.completion_review_reason
    assert ("100 metres" in response.completion_review_reason) is off_site
    event = service.db.query(TripEvent).filter_by(event_type="trip_completed").one()
    assert event.data["expiry_override"] is True
    assert event.data["reported_success"] is True
    assert event.data["notes"] == "Operator reports a completed pour"
    assert push.await_args.args[2]["completion_review_required"] is True
    service.db.expire_all()
    assert service._to_response(trip).completion_review_required is True


@pytest.mark.asyncio
async def test_pending_completion_is_rejected(trip_service):
    service, trip, push = trip_service
    trip.status = "pending"
    service.db.commit()
    with pytest.raises(ValueError, match="in-progress or paused"):
        await service.complete_trip(trip.id)
    assert trip.status == "pending"
    assert trip.outcome is None
    push.assert_not_awaited()
