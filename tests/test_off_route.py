"""Off-route confirmation, cost guards, persistence and SSE."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import Route, Trip, TripEvent
from app.schemas import PositionUpdate
from app.services.trip import TripService
from app.utils.polyline import distance_to_route_metres


def encode(points):
    result = ""
    previous = [0, 0]
    for point in points:
        for index, coordinate in enumerate(point):
            current = round(coordinate * 100000)
            delta = current - previous[index]
            previous[index] = current
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 32:
                result += chr((value & 31 | 32) + 63)
                value >>= 5
            result += chr(value + 63)
    return result


@pytest.fixture
def store(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        route = Route(
            start_address="Plant", start_lat=0, start_lng=0,
            end_address="Site", end_lat=0, end_lng=0.1, vehicle_type="rmc_truck",
        )
        db.add(route)
        db.flush()
        trip = Trip(
            route_id=route.id, status="in_progress", organization_id="org_A",
            start_address="Plant", start_lat=0, start_lng=0,
            end_address="Site", end_lat=0, end_lng=0.1,
            current_lat=0, current_lng=0, original_duration_seconds=600,
            remaining_duration_seconds=600, current_polyline=encode([(0, 0), (0, 0.1)]),
        )
        db.add(trip)
        db.commit()
        maps = AsyncMock()
        maps.get_directions.return_value = {
            "status": "OK", "routes": [{
                "overview_polyline": {"points": encode([(0.002, 0.02), (0, 0.1)])},
                "legs": [{"distance": {"value": 8000}, "duration": {"value": 300},
                          "duration_in_traffic": {"value": 300}, "steps": []}],
            }],
        }
        push = AsyncMock()
        monkeypatch.setattr("app.services.trip._push_event", push)
        service = TripService(db, maps, organization_id="org_A")
        monkeypatch.setattr(service, "_evaluate_load_status", AsyncMock())
        yield service, trip, maps, push
    engine.dispose()


async def fix(service, trip, lat, seconds_ago=0):
    return await service.update_position(trip.id, PositionUpdate(
        lat=lat, lng=0.02,
        captured_at=datetime.now(timezone.utc) - timedelta(seconds=seconds_ago),
    ))


def test_distance_threshold_and_nearest_segment():
    route = encode([(0, 0), (0, 0.1), (0.1, 0.1)])
    assert distance_to_route_metres(0, 0.05, route) == pytest.approx(0)
    for metres in (99.9, 100, 100.1):
        latitude = metres / 6371000 * 180 / 3.141592653589793
        assert distance_to_route_metres(latitude, 0.05, route) == pytest.approx(metres)
    assert distance_to_route_metres(0.05, 0.1, route) == pytest.approx(0)


@pytest.mark.parametrize("route", ["", "?", "~~~~~~~", "abc"])
def test_invalid_polyline_explicit(route):
    with pytest.raises(ValueError):
        distance_to_route_metres(0, 0, route)


@pytest.mark.asyncio
async def test_two_fresh_fixes_reroute_even_without_delay(store):
    service, trip, maps, push = store
    trip.last_reroute_at = datetime.now(timezone.utc)
    service.db.commit()
    await fix(service, trip, 0.002, 2)
    maps.get_directions.assert_not_awaited()
    response = await fix(service, trip, 0.002, 1)
    assert response.reroute_count == 1
    assert trip.current_polyline == maps.get_directions.return_value["routes"][0]["overview_polyline"]["points"]
    arguments = maps.get_directions.await_args.kwargs
    assert arguments["coarse_start"] is False
    assert arguments["start_lat"] == 0.002 and arguments["start_lng"] == 0.02
    reroute = next(call.args[2] for call in push.await_args_list if call.args[1] == "reroute")
    assert reroute["applied"] is True and reroute["reason"] == "Driver is off the planned route"
    assert reroute["new_duration_seconds"] == 300
    assert service.db.query(TripEvent).filter_by(event_type="reroute_applied").count() == 1


@pytest.mark.asyncio
async def test_jitter_on_route_fix_resets_confirmation(store):
    service, trip, maps, _ = store
    await fix(service, trip, 0.002, 4)
    await fix(service, trip, 0.0005, 3)
    await fix(service, trip, 0.002, 2)
    maps.get_directions.assert_not_awaited()
    await fix(service, trip, 0.002, 1)
    maps.get_directions.assert_awaited_once()


@pytest.mark.asyncio
async def test_old_fix_does_not_confirm_or_consume_google_calls(store):
    service, trip, maps, _ = store
    await fix(service, trip, 0.002, 60)
    await fix(service, trip, 0.002, 1)
    maps.get_directions.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_fix_rejected(store):
    service, trip, maps, _ = store
    position = PositionUpdate(lat=0.002, lng=0.02)
    position.captured_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await service.update_position(trip.id, position)
    with pytest.raises(ValueError, match="stale or duplicated"):
        await service.update_position(trip.id, position)
    maps.get_directions.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["paused", "in_progress"])
async def test_paused_or_missing_geometry_no_calls(store, status):
    service, trip, maps, _ = store
    trip.status = status
    if status == "in_progress":
        trip.current_polyline = None
    service.db.commit()
    await fix(service, trip, 0.002, 2)
    await fix(service, trip, 0.002, 1)
    maps.get_directions.assert_not_awaited()


@pytest.mark.asyncio
async def test_failure_is_audited_and_attempt_cooldown_survives_service_recreation(store):
    service, trip, maps, _ = store
    maps.get_directions.side_effect = ValueError("Maps unavailable")
    await fix(service, trip, 0.002, 4)
    await fix(service, trip, 0.002, 3)
    assert trip.reroute_count == 0
    assert service.db.query(TripEvent).filter_by(event_type="traffic_check").one().data["status"] == "error"
    new_service = TripService(service.db, maps, organization_id="org_A")
    await fix(new_service, trip, 0.002, 2)
    maps.get_directions.assert_awaited_once()
    attempt = service.db.query(TripEvent).filter_by(event_type="off_route_check").one()
    attempt.created_at = datetime.now(timezone.utc) - timedelta(seconds=31)
    service.db.commit()
    await fix(new_service, trip, 0.002, 1)
    assert maps.get_directions.await_count == 2


@pytest.mark.asyncio
async def test_concurrent_monitor_does_not_apply_second_reroute(store):
    service, trip, maps, _ = store
    await fix(service, trip, 0.002, 2)
    await fix(service, trip, 0.002, 1)
    await asyncio.gather(service.check_and_reroute(trip.id),
                         service.check_and_reroute(trip.id, off_route=True))
    maps.get_directions.assert_awaited_once()


@pytest.mark.asyncio
async def test_traffic_ratio_uses_expected_remaining_not_original_full_duration(store):
    service, trip, maps, _ = store
    trip.estimated_arrival = datetime.now(timezone.utc) + timedelta(seconds=200)
    service.db.commit()
    result = await service.check_and_reroute(trip.id)
    assert result is not None
    assert 195 <= result.old_duration_seconds <= 200
    assert result.reason.startswith("Route is")


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["near_destination", "reroute_cooldown"])
async def test_eta_refresh_not_blocked_by_traffic_reroute_guards(store, guard):
    service, trip, maps, push = store
    if guard == "near_destination":
        trip.end_lng = 0.006
    else:
        trip.last_reroute_at = datetime.now(timezone.utc)
    trip.estimated_arrival = datetime.now(timezone.utc) - timedelta(hours=1)
    maps.get_directions.return_value["routes"][0]["legs"][0]["duration_in_traffic"]["value"] = 900
    service.db.commit()
    before = datetime.now(timezone.utc)
    result = await service.check_and_reroute(trip.id)
    maps.get_directions.assert_awaited_once()
    assert result is None
    service.db.refresh(trip)
    from app.utils.time import as_utc
    assert as_utc(trip.estimated_arrival) >= before + timedelta(seconds=900)
    assert trip.remaining_duration_seconds == 900
    assert trip.last_traffic_check_at is not None
    assert trip.reroute_count == 0
    event = next(call.args[2] for call in push.await_args_list if call.args[1] == "traffic_ok")
    assert as_utc(datetime.fromisoformat(event["eta"])) == as_utc(trip.estimated_arrival)


@pytest.mark.asyncio
async def test_stationary_eta_refresh_preserves_eight_minute_api_cost_guard(store):
    service, trip, maps, _ = store
    trip.end_lng = 0.006
    service.db.commit()
    await service.check_and_reroute(trip.id)
    await service.check_and_reroute(trip.id)
    maps.get_directions.assert_awaited_once()
    trip.last_traffic_check_at = datetime.now(timezone.utc) - timedelta(seconds=481)
    trip.estimated_arrival = datetime.now(timezone.utc) - timedelta(minutes=1)
    service.db.commit()
    await service.check_and_reroute(trip.id)
    assert maps.get_directions.await_count == 2
    from app.utils.time import as_utc
    assert as_utc(trip.estimated_arrival) > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_wrong_company_cannot_trigger_maps(store):
    service, trip, maps, _ = store
    service.organization_id = "org_B"
    with pytest.raises(HTTPException) as error:
        await fix(service, trip, 0.002)
    assert error.value.status_code == 403
    maps.get_directions.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_response", [
    {"status": "REQUEST_DENIED", "error_message": "Maps unavailable"},
    {"status": "OK", "routes": [{"overview_polyline": {}, "legs": [
        {"duration": {"value": 300}, "distance": {"value": 8000}},
    ]}]},
])
async def test_failed_response_preserves_route_and_records_failure(store, bad_response):
    service, trip, maps, push = store
    original = trip.current_polyline
    maps.get_directions.return_value = bad_response
    await fix(service, trip, 0.002, 2)
    await fix(service, trip, 0.002, 1)
    service.db.expire_all()
    assert trip.current_polyline == original
    assert trip.reroute_count == 0
    assert service.db.query(TripEvent).filter_by(event_type="traffic_check").one().data["status"] in ("error", "api_error")
    assert not any(call.args[1] == "reroute" for call in push.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["pause", "archive"])
async def test_result_discarded_if_trip_changes_during_request(store, change):
    service, trip, maps, _ = store
    response = maps.get_directions.return_value

    async def pause(**kwargs):
        if change == "pause":
            trip.status = "paused"
        else:
            trip.archived_at = datetime.now(timezone.utc)
        service.db.commit()
        return response

    maps.get_directions.side_effect = pause
    original = trip.current_polyline
    await fix(service, trip, 0.002, 2)
    await fix(service, trip, 0.002, 1)
    assert trip.current_polyline == original
    assert service.db.query(TripEvent).filter_by(event_type="traffic_check").one().data["status"] == "discarded"


@pytest.mark.asyncio
async def test_result_discarded_if_gps_expires_during_request(store, monkeypatch):
    service, trip, maps, push = store
    response = maps.get_directions.return_value
    original = trip.current_polyline

    class LaterDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(seconds=31)

    async def delayed_response(**kwargs):
        monkeypatch.setattr("app.services.trip.datetime", LaterDatetime)
        return response

    maps.get_directions.side_effect = delayed_response
    await fix(service, trip, 0.002, 2)
    await fix(service, trip, 0.002, 1)
    assert trip.current_polyline == original
    assert trip.reroute_count == 0
    assert service.db.query(TripEvent).filter_by(event_type="traffic_check").one().data["status"] == "discarded"
    assert not any(call.args[1] == "reroute" for call in push.await_args_list)
