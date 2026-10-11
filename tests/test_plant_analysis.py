"""International geocoding and brand-analysis regression tests (no live APIs)."""
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints import plants
from app.auth import Principal, get_current_principal
from app.db import Base, get_db
from app.db.models import Brand, Business, Plant, Region
from app.dependencies import get_prediction_service
from app.services.google_maps import GoogleMapsService
from app.services.prediction import PredictionService


INDIA_PLANTS = [
    {
        "id": f"india_{index}",
        "name": name,
        "brand": "India",
        "address": f"{name}, Telangana, India",
        "lat": 17.98 + index * 0.01,
        "lng": 79.53,
        "region": "warangal",
        "active": True,
    }
    for index, name in enumerate(
        ["NIT Warangal", "Hanamkonda Chowrastha", "KU X Roads"]
    )
]


@pytest.fixture(autouse=True)
def isolate_catalogue_and_cache():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Business(id="test-org", name="Test business"))
        db.flush()
        db.add(Brand(id="brand_india", name="India", organization_id="test-org"))
        db.add(Region(
            id="in_telangana_warangal", name="Warangal", country_code="IN",
            organization_id="test-org",
            administrative_area="Telangana", timezone="Asia/Kolkata",
            calibration_status="uncalibrated",
        ))
        db.flush()
        for p in INDIA_PLANTS:
            db.add(Plant(
                id=p["id"], name=p["name"], brand_id="brand_india",
                organization_id="test-org",
                region_id="in_telangana_warangal", address=p["address"],
                lat=p["lat"], lng=p["lng"], active=True,
                supported_mix_codes=["GP", "HE", "RE"],
            ))
        db.commit()
    plants._analysis_cache.clear()
    yield engine
    plants._analysis_cache.clear()
    engine.dispose()


@pytest_asyncio.fixture
async def gmaps():
    service = GoogleMapsService(api_key="test-key")
    await service.client.aclose()
    yield service
    await service.client.aclose()


def analysis_request(**overrides):
    return {
        "brand_id": "brand_india",
        "job_site_data": {
            "display_name": "Kazipet Junction, Hanamkonda, Telangana, 506003, India",
        },
        "concrete_mix": "GP",
        "include_llm_analysis": False,
        **overrides,
    }


def analysis_app(service, engine):
    app = FastAPI()
    app.include_router(plants.router, prefix="/api/v1")
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="test-super-admin", organization_id="test-org",
        organization_role="org:admin", is_super_admin=True,
    )
    app.dependency_overrides[get_prediction_service] = lambda: service
    def database():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = database
    return app


def google_response(request):
    if request.url.path.endswith("/geocode/json"):
        address = request.url.params["address"]
        index = next(
            (i for i, plant in enumerate(INDIA_PLANTS) if plant["address"] == address),
            3,
        )
        return httpx.Response(200, json={
            "status": "OK",
            "results": [{
                "geometry": {"location": {"lat": 17.98 + index * 0.01, "lng": 79.53}},
                "formatted_address": address,
            }],
        })
    start_lat = float(request.url.params["origin"].split(",")[0])
    eta = 10 + round((start_lat - 17.98) * 100) * 5
    return httpx.Response(200, json={
        "status": "OK",
        "routes": [{
            "legs": [{
                "distance": {"value": 5000},
                "duration": {"value": eta * 60},
                "duration_in_traffic": {"value": (eta + 2) * 60},
                "start_location": {"lat": start_lat, "lng": 79.53},
                "end_location": {"lat": 18.01, "lng": 79.53},
            }],
        }],
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("country_code", [None, "IN", "NZ"])
async def test_geocoding_country_is_optional_and_forwarded(gmaps, country_code):
    requests = []

    def handle(request):
        requests.append(request)
        return google_response(request)

    gmaps.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    await gmaps.geocode_address("Kazipet, India", country_code=country_code)
    params = requests[0].url.params
    if country_code:
        assert params["components"] == f"country:{country_code}"
    else:
        assert "components" not in params


@pytest.mark.asyncio
async def test_geocode_cache_distinguishes_countries(gmaps):
    requests = []

    def handle(request):
        requests.append(request)
        return google_response(request)

    gmaps.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    for country in ["IN", "NZ", None, "IN"]:
        await gmaps.geocode_address("Same address", country_code=country)
    assert len(requests) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("country_code", [None, "IN"])
async def test_india_analysis_returns_complete_ranked_predictions(
    gmaps, monkeypatch, country_code, isolate_catalogue_and_cache,
):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.params.get("components") != "country:NZ"
        return google_response(request)

    gmaps.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    weather = AsyncMock()
    weather.get_weather.return_value = {
        "current": {"temperature_c": 28, "condition": "clear"},
        "delivery_impact": {"speed_multiplier": 1.0},
    }
    monkeypatch.setattr("app.services.prediction.WeatherService", lambda: weather)
    monkeypatch.setattr("app.services.prediction.LLMAnalyzer", AsyncMock)
    service = PredictionService(gmaps)
    payload = analysis_request()
    if country_code:
        payload["country_code"] = country_code
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=analysis_app(service, isolate_catalogue_and_cache)), base_url="http://test",
    ) as client:
        response = await client.post("/api/v1/plants/analyse", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["total_plants_analysed"] == 3
    assert data["best_plant_id"] == "india_0"
    assert data["llm_comparison"] is None
    assert [r["plant"]["id"] for r in data["results"]] == [
        "india_0", "india_1", "india_2",
    ]
    for result, expected_eta in zip(data["results"], [12, 17, 22]):
        assert result["error"] is None
        assert result["google_eta_minutes"] == expected_eta
        assert result["adjusted_eta_minutes"] > 0
        assert result["remaining_life_minutes"] == pytest.approx(
            80 - 5 - result["adjusted_eta_minutes"], abs=0.1,
        )
        assert result["buffer_depletion_rate"] is not None
        assert result["delay_constant_used"] > 0
        assert result["risk_level"]
        assert 0 <= result["success_probability"] <= 1
        assert result["recommendation"]
    geocodes = [r for r in requests if r.url.path.endswith("/geocode/json")]
    assert all(
        r.url.params.get("components") == (
            "country:IN"
        )
        for r in geocodes
    )


def successful_prediction(life=60):
    return {
        "traffic": {"google_eta_minutes": 20},
        "prediction": {
            "adjusted_eta_minutes": 25,
            "remaining_life_minutes": life,
            "buffer_depletion_rate": 0.3,
            "delay_constant_used": 1.25,
            "risk_level": "LOW",
            "success_probability": 0.95,
        },
        "recommendation": "Dispatch now",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    {"error": "Google geocoding failed (ZERO_RESULTS)"},
    {"error": "Google Directions failed (REQUEST_DENIED): enable billing"},
    {},
    ValueError("Geocoding unavailable"),
])
async def test_failures_are_explicit_ranked_last_and_not_cached(failure, isolate_catalogue_and_cache):
    service = AsyncMock()
    service.predict_delivery.side_effect = [
        failure, successful_prediction(40), successful_prediction(60),
        successful_prediction(70), successful_prediction(60), successful_prediction(50),
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=analysis_app(service, isolate_catalogue_and_cache)), base_url="http://test",
    ) as client:
        first = await client.post("/api/v1/plants/analyse", json=analysis_request())
        second = await client.post("/api/v1/plants/analyse", json=analysis_request())
    data = first.json()
    assert first.status_code == second.status_code == 200
    assert data["best_plant_id"] == "india_2"
    assert data["results"][-1]["plant"]["id"] == "india_0"
    assert data["results"][-1]["error"]
    assert data["results"][-1]["remaining_life_minutes"] is None
    assert second.json()["best_plant_id"] == "india_0"
    assert service.predict_delivery.await_count == 6


@pytest.mark.asyncio
async def test_all_failed_plants_have_errors_and_no_best(isolate_catalogue_and_cache):
    service = AsyncMock()
    service.predict_delivery.return_value = {"error": "ZERO_RESULTS"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=analysis_app(service, isolate_catalogue_and_cache)), base_url="http://test",
    ) as client:
        response = await client.post("/api/v1/plants/analyse", json=analysis_request())
    data = response.json()
    assert data["best_plant_id"] is None
    assert all(r["error"] == "ZERO_RESULTS" for r in data["results"])
    assert not plants._analysis_cache


@pytest.mark.asyncio
async def test_analysis_cache_distinguishes_options(monkeypatch, isolate_catalogue_and_cache):
    service = AsyncMock()
    service.predict_delivery.return_value = successful_prediction()
    service.geocode_job_site.return_value = {"latitude": 17.98, "longitude": 79.53}
    analyzer = AsyncMock()
    analyzer.compare_plants.return_value = {"recommendation": "NIT Warangal"}
    monkeypatch.setattr(plants, "LLMAnalyzer", lambda: analyzer)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=analysis_app(service, isolate_catalogue_and_cache)), base_url="http://test",
    ) as client:
        for options, count in [
            ({"top_n": 1}, 1),
            ({"top_n": 2}, 2),
            ({"top_n": 2, "region_id": "in_telangana_warangal"}, 2),
            ({"top_n": 2, "include_llm_analysis": True}, 2),
            ({"top_n": 1}, 1),
        ]:
            response = await client.post(
                "/api/v1/plants/analyse", json=analysis_request(**options),
            )
            assert response.json()["total_plants_analysed"] == count
            if options.get("include_llm_analysis"):
                assert response.json()["llm_comparison"] == analyzer.compare_plants.return_value
    assert service.predict_delivery.await_count == 7
    analyzer.compare_plants.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalid_country_code_rejected(isolate_catalogue_and_cache):
    service = AsyncMock()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=analysis_app(service, isolate_catalogue_and_cache)), base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/plants/analyse", json=analysis_request(country_code="India"),
        )
    assert response.status_code == 422
    service.predict_delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_directions_failure_is_retried_and_preserves_diagnostic(gmaps, monkeypatch):
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path.endswith("/directions/json") and len([
            r for r in calls if r.url.path.endswith("/directions/json")
        ]) == 1:
            return httpx.Response(200, json={
                "status": "REQUEST_DENIED",
                "error_message": "Enable Directions API",
            })
        return google_response(request)

    gmaps.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    weather = AsyncMock()
    weather.get_weather.return_value = {}
    monkeypatch.setattr("app.services.prediction.WeatherService", lambda: weather)
    monkeypatch.setattr("app.services.prediction.LLMAnalyzer", AsyncMock)
    service = PredictionService(gmaps)
    first = await service.predict_delivery("Plant, India", "Job, India", include_llm=False)
    assert "REQUEST_DENIED" in first["error"]
    assert "Enable Directions API" in first["error"]
    second = await service.predict_delivery("Plant, India", "Job, India", include_llm=False)
    assert second["prediction"]["remaining_life_minutes"] is not None


@pytest.mark.asyncio
async def test_geocoding_failure_preserves_status(gmaps):
    gmaps.client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []}),
    ))
    with pytest.raises(ValueError, match="ZERO_RESULTS"):
        await gmaps.geocode_address("Kazipet, India", country_code="IN")
