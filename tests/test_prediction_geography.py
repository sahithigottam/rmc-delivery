"""Country-specific baselines and UTC/local-time boundaries."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from app.rmc.predictor import DeliveryPredictor
from app.services.llm_analyzer import LLMAnalyzer
from app.services.prediction import PredictionService
from app.services.weather import WeatherService


def predict(country="IN", hour=16, day=4, weather=None, eta=30):
    return DeliveryPredictor().predict(
        google_eta_minutes=eta, google_traffic_delay_s=0,
        start_lat=17, start_lng=79, end_lat=18, end_lng=79,
        departure_hour=hour, departure_day=day, country_code=country,
        weather=weather,
    )


def test_india_does_not_inherit_auckland_time_or_history_factors():
    peak = predict()
    quiet = predict(hour=2, day=6)
    assert peak.adjusted_eta_minutes == quiet.adjusted_eta_minutes == 30
    assert peak.remaining_life_minutes == 55
    assert peak.success_probability is None
    assert peak.p50_duration_minutes is None and peak.p95_duration_minutes is None
    assert peak.route_success_rate is None and peak.route_trips == 0
    assert peak.calibration_status == "uncalibrated"
    assert peak.delay_constant_used == 1
    assert "Auckland" not in peak.recommendation and "%" not in peak.recommendation
    assert not any("peak" in r["name"].lower() for r in peak.risk_factors)


def test_india_retains_explicit_weather_heuristics():
    result = predict(weather={
        "current": {"temperature_c": 36, "condition": "Heavy rain"},
        "delivery_impact": {"speed_multiplier": 1.2},
    })
    assert result.adjusted_eta_minutes == 33
    assert result.setting_time_minutes == 60
    assert result.remaining_life_minutes == 22
    assert result.risk_level == "moderate"
    assert "NZS" not in str(result.risk_factors)


def test_first_future_weather_hour_is_not_skipped():
    result = predict(weather={
        "current": {"temperature_c": 20, "condition": "Clear"},
        "delivery_impact": {"speed_multiplier": 1.0},
        "forecast_hours": [{"time": "2026-01-03T00:00:00+00:00",
                            "condition": "Heavy rain", "speed_multiplier": 1.35}],
    })
    assert any(r["name"] == "Weather deteriorating" for r in result.risk_factors)


def test_nz_retains_existing_peak_baseline():
    result = predict(country="NZ")
    expected = round(30 * 1.10 * (1 + (0.23 + (1.15 * 1.10 - 1)) * 0.5), 1)
    assert result.adjusted_eta_minutes == expected
    assert result.success_probability is not None
    assert result.p50_duration_minutes is not None
    assert result.calibration_status == "nz_baseline"
    assert any(r["name"] == "Friday afternoon peak" for r in result.risk_factors)


@pytest.mark.parametrize("country", ["US", "", "india"])
def test_unsupported_predictor_country_fails_explicitly(country):
    with pytest.raises(ValueError, match="country"):
        predict(country=country)


@pytest.mark.asyncio
@pytest.mark.parametrize("country,instant,expected_hour,expected_day", [
    ("IN", "2026-01-02T20:00:00+00:00", 1, 5),
    ("NZ", "2026-01-02T20:00:00+00:00", 9, 5),
    ("NZ", "2026-07-03T20:00:00+00:00", 8, 5),
])
async def test_service_uses_local_departure_time_and_dst(
    monkeypatch, country, instant, expected_hour, expected_day,
):
    fixed = datetime.fromisoformat(instant)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz)

    monkeypatch.setattr("app.services.prediction.datetime", FixedDatetime)
    monkeypatch.setattr("app.services.prediction.PlantLocator", lambda *args, **kwargs: None)
    weather = AsyncMock()
    weather.get_weather.return_value = {}
    monkeypatch.setattr("app.services.prediction.WeatherService", lambda: weather)
    monkeypatch.setattr("app.services.prediction.LLMAnalyzer", AsyncMock)
    maps = AsyncMock()
    maps.geocode_address.return_value = {"latitude": 1, "longitude": 2, "country_code": country}
    maps.get_directions.return_value = {"status": "OK", "routes": [{"legs": [{
        "distance": {"value": 1000}, "duration": {"value": 1800},
        "start_location": {"lat": 1, "lng": 2}, "end_location": {"lat": 1, "lng": 2},
    }]}]}
    service = PredictionService(maps)
    original_predict = service._predictor.predict
    captured = {}

    def capture(**kwargs):
        captured.update(kwargs)
        return original_predict(**kwargs)

    monkeypatch.setattr(service._predictor, "predict", capture)
    result = await service.predict_delivery("Start", "End", include_llm=False)
    assert "error" not in result
    assert captured["departure_hour"] == expected_hour
    assert captured["departure_day"] == expected_day
    assert captured["country_code"] == country
    assert result["input"]["timezone"] == {"IN": "Asia/Kolkata", "NZ": "Pacific/Auckland"}[country]
    if country == "IN":
        assert result["prediction"]["duration_percentiles"] == dict.fromkeys(["p50", "p75", "p90", "p95"])


@pytest.mark.asyncio
async def test_weather_current_hour_is_utc_and_forecast_crosses_midnight(monkeypatch):
    fixed = datetime(2026, 1, 2, 23, 30, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz)

    monkeypatch.setattr("app.services.weather.datetime", FixedDatetime)
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"hourly": {
            "time": ["2026-01-02T22:00", "2026-01-02T23:00", "2026-01-03T00:00", "2026-01-03T01:00"],
            "temperature_2m": [10, 31, 20, 20], "precipitation": [0, 6, 0, 0],
            "windspeed_10m": [0] * 4, "windgusts_10m": [0] * 4, "weathercode": [0] * 4,
        }})

    service = WeatherService()
    await service._client.aclose()
    service._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    try:
        result = await service.get_weather(17, 79, hours_ahead=2)
        assert requests[0].url.params["timezone"] == "UTC"
        assert requests[0].url.params["forecast_days"] == "2"
        assert result["current"]["temperature_c"] == 31
        assert result["current"]["rain_mm"] == 6
        assert result["available"] is True
        assert result["forecast_hours"][0]["time"] == "2026-01-03T00:00:00+00:00"
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_missing_current_weather_is_explicitly_unavailable():
    service = WeatherService()
    await service._client.aclose()
    service._client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"hourly": {"time": []}})
    ))
    try:
        result = await service.get_weather(17, 79)
        assert result["available"] is False
        assert result["current"]["condition"] == "Unknown (API unavailable)"
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_uncalibrated_narratives_do_not_invent_probability_or_call_llm(monkeypatch):
    analyzer = LLMAnalyzer()
    check = AsyncMock()
    monkeypatch.setattr(analyzer, "_ensure_checked", check)
    try:
        result = await analyzer.analyze(predict())
        assert result["source"] == "template"
        assert "Uncalibrated" in result["risk_summary"]
        comparison = await analyzer.compare_plants([{
            "plant_name": "India test", "remaining_life": 55,
            "risk_level": "low", "success_prob": None,
        }], "Site", "GP")
        assert comparison["source"] == "template"
        assert "unavailable" in comparison["reason"]
        assert "%" not in comparison["reason"]
        check.assert_not_awaited()
    finally:
        await analyzer.close()


@pytest.mark.asyncio
async def test_india_best_plant_ranks_remaining_life_without_nz_distance_filter():
    service = PredictionService.__new__(PredictionService)
    service._gmaps = AsyncMock()
    service._gmaps.geocode_address.return_value = {
        "latitude": 17, "longitude": 79, "country_code": "IN",
    }
    service._locator = AsyncMock()
    plants = [
        {"id": "a", "name": "A", "brand": "India", "address": "A",
         "distance_km": 2, "country_code": "IN", "timezone": "Asia/Kolkata",
         "supported_mix_codes": ["GP"]},
        {"id": "b", "name": "B", "brand": "India", "address": "B",
         "distance_km": 3, "country_code": "IN", "timezone": "Asia/Kolkata",
         "supported_mix_codes": ["GP"]},
    ]
    from unittest.mock import Mock
    service._locator.nearest_by_distance = Mock(return_value=plants)

    async def prediction(**kwargs):
        remaining = 40 if kwargs["start_address"] == "A" else 50
        return {
            "input": {"start_address": kwargs["start_address"]},
            "traffic": {"google_eta_minutes": 30},
            "prediction": {
                "adjusted_eta_minutes": 30, "success_probability": None,
                "risk_level": "LOW", "time_buffer_minutes": 60,
                "remaining_life_minutes": remaining, "calibration_status": "uncalibrated",
                "baseline_source": "Google ETA plus weather heuristics",
                "confidence_reason": "No validated India traffic profile",
            },
        }

    service.predict_delivery = AsyncMock(side_effect=prediction)
    result = await service.best_plant("Site")
    assert result["best_plant"]["id"] == "b"
    assert result["best_plant"]["success_probability"] is None
    service._locator.candidates_for_job.assert_not_called()
    assert all(call.kwargs["country_code"] == "IN"
               for call in service.predict_delivery.await_args_list)
