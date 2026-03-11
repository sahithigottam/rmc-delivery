"""Tests for route endpoints"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check():
    """Test health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_root_endpoint():
    """Test root endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "title" in data
    assert "version" in data


@pytest.mark.asyncio
async def test_estimate_route_missing_fields():
    """Test route estimation with missing required fields"""
    response = client.post(
        "/api/v1/routes/estimate",
        json={
            "vehicle_type": "heavy_truck",
        },
    )
    assert response.status_code == 422  # Validation error


def test_rate_limiting():
    """Test API rate limiting"""
    # This is a placeholder - implement based on rate limiting middleware
    pass


def test_get_route_not_found():
    """Test retrieving non-existent route"""
    response = client.get("/api/v1/routes/99999")
    assert response.status_code == 404


def test_get_route_history_empty():
    """Test route history when no routes exist"""
    response = client.get("/api/v1/routes")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
