"""Request correlation, log volume, privacy and dependency diagnostics."""
import asyncio
import io
import json
import logging
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

from app.config import settings
from app.observability import (
    JsonLogFormatter, RequestLoggingMiddleware, configure_logging, request_id_context,
)
from app.services.google_maps import GoogleMapsService


@pytest.fixture
def log_output():
    output = io.StringIO()
    root = logging.getLogger()
    original_level = root.level
    handler = logging.StreamHandler(output)
    handler.setFormatter(JsonLogFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    yield output
    root.removeHandler(handler)
    root.setLevel(original_level)


def app_with_logging():
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=["*"], expose_headers=["X-Request-ID"])
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/trips/{trip_id}")
    async def get_trip(trip_id: str):
        logging.getLogger("test.request").info("trip requested")
        return {"id": trip_id}

    @app.get("/denied")
    async def denied():
        raise HTTPException(403, "Forbidden")

    @app.get("/broken")
    async def broken():
        raise ValueError("private address and token=secret")

    @app.exception_handler(Exception)
    async def error(request, exc):
        return JSONResponse({"detail": "Internal server error"}, status_code=500,
                            headers={"X-Request-ID": request.state.request_id})

    @app.get("/stream")
    async def stream():
        async def events():
            yield "data: test\n\n"
        return StreamingResponse(events(), media_type="text/event-stream")

    return app


def test_success_correlates_logs_without_access_noise(log_output):
    client = TestClient(app_with_logging())
    response = client.get("/trips/private-id?token=secret", headers={
        "X-Request-ID": "untrusted-id", "Authorization": "Bearer private-token",
        "Origin": "https://example.test",
    })
    records = [json.loads(line) for line in log_output.getvalue().splitlines()]
    assert response.status_code == 200
    assert len(response.headers["X-Request-ID"]) == 32
    assert response.headers["X-Request-ID"] != "untrusted-id"
    assert response.headers["access-control-expose-headers"] == "X-Request-ID"
    assert records[0]["request_id"] == response.headers["X-Request-ID"]
    assert not any("http_request" in r["message"] for r in records)
    assert request_id_context.get() is None


def test_errors_use_route_templates_and_keep_private_input_out(log_output):
    client = TestClient(app_with_logging(), raise_server_exceptions=False)
    denied = client.get("/denied?secret=private")
    broken = client.get("/broken")
    missing = client.get("/private-personal-address")
    assert denied.status_code == 403 and broken.status_code == 500 and missing.status_code == 404
    records = [json.loads(line) for line in log_output.getvalue().splitlines()]
    error = next(r for r in records if r["message"].startswith("http_request_failed"))
    assert error["request_id"] == broken.headers["X-Request-ID"]
    assert error["error_type"] == "ValueError" and error["stack"]
    output = log_output.getvalue()
    assert "private" not in output and "token=secret" not in output
    assert "route=<unmatched>" in output


def test_slow_request_is_logged(monkeypatch, log_output):
    ticks = iter([0, 3])
    monkeypatch.setattr("app.observability.perf_counter", lambda: next(ticks))
    response = TestClient(app_with_logging()).get("/trips/1")
    assert response.status_code == 200
    assert "duration_ms=3000" in log_output.getvalue()
    records = [json.loads(line) for line in log_output.getvalue().splitlines()]
    summary = next(r for r in records if r.get("event") == "http_request")
    assert summary["route"] == "/trips/{trip_id}"
    assert summary["duration_ms"] == 3000 and summary["status_code"] == 200


def test_stream_is_not_logged_as_slow_for_connection_lifetime(monkeypatch, log_output):
    ticks = iter([0, 0.1])
    monkeypatch.setattr("app.observability.perf_counter", lambda: next(ticks))
    response = TestClient(app_with_logging()).get("/stream")
    assert response.text == "data: test\n\n"
    assert response.headers["X-Request-ID"]
    assert "http_request" not in log_output.getvalue()


@pytest.mark.asyncio
async def test_concurrent_requests_keep_separate_context():
    seen = []

    async def inner(scope, receive, send):
        before = request_id_context.get()
        await asyncio.sleep(0)
        seen.append((before, request_id_context.get()))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = RequestLoggingMiddleware(inner)
    receive = AsyncMock()
    send = AsyncMock()
    await asyncio.gather(*[
        middleware({"type": "http", "method": "GET"}, receive, send) for _ in range(2)
    ])
    assert all(before == after for before, after in seen)
    assert seen[0][0] != seen[1][0]
    assert request_id_context.get() is None


def test_formatter_redacts_credentials_and_exception_text():
    record = logging.LogRecord("test", logging.ERROR, __file__, 1,
                               "url=https://maps.test?key=secret Bearer secret token=secret",
                               (), None)
    result = JsonLogFormatter().format(record)
    assert "secret" not in result and "maps.test" not in result
    assert json.loads(result)["level"] == "ERROR"


def test_logging_setup_stdout_only_idempotent_and_production_floor():
    root = logging.getLogger()
    original_handlers, original_level = root.handlers[:], root.level
    names = ["uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "httpcore", "sqlalchemy.engine"]
    originals = {name: (logging.getLogger(name).handlers[:], logging.getLogger(name).level,
                        logging.getLogger(name).disabled, logging.getLogger(name).propagate)
                 for name in names}
    try:
        configure_logging("DEBUG", production=True)
        configure_logging("DEBUG", production=True)
        owned = [h for h in root.handlers if getattr(h, "_rmc_stdout", False)]
        assert len(owned) == 1
        assert not isinstance(owned[0], logging.FileHandler)
        assert root.level == logging.INFO
        assert logging.getLogger("uvicorn.access").disabled
    finally:
        for handler in root.handlers:
            if handler not in original_handlers:
                handler.close()
        root.handlers = original_handlers
        root.setLevel(original_level)
        for name, (handlers, level, disabled, propagate) in originals.items():
            log = logging.getLogger(name)
            log.handlers, log.level, log.disabled, log.propagate = handlers, level, disabled, propagate


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["OK", "REQUEST_DENIED"])
async def test_google_dependency_logs_only_unhealthy_or_slow(status, log_output, monkeypatch):
    service = GoogleMapsService(api_key="private-key")
    response = httpx.Response(200, json={"status": status},
                              request=httpx.Request("GET", "https://maps.test"))
    service.client.get = AsyncMock(return_value=response)
    monkeypatch.setattr(settings, "slow_request_ms", 100000)
    try:
        result = await service.get_directions(1, 2, 3, 4)
        assert result["status"] == status
        output = log_output.getvalue()
        assert ("google_maps_request" in output) == (status != "OK")
        assert "private-key" not in output and "1,2" not in output
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_google_http_exception_does_not_log_secret_url(log_output):
    service = GoogleMapsService(api_key="private-key")
    request = httpx.Request("GET", "https://maps.test?key=private-key&address=private-address")
    service.client.get = AsyncMock(side_effect=httpx.ConnectError(str(request.url), request=request))
    try:
        with pytest.raises(httpx.ConnectError):
            await service.get_directions(1, 2, 3, 4)
        output = log_output.getvalue()
        assert "ConnectError" in output and "operation=directions/json" in output
        assert "private-key" not in output and "private-address" not in output
    finally:
        await service.close()
