# RMC Delivery Route Optimizer - API Documentation

## Overview
REST API for calculating optimized delivery routes for New Zealand RMC (Ready-Mix Concrete) trucks using real-time traffic data from Google Maps API.

## Base URL
```
http://localhost:8000/api/v1
```

## Authentication
Currently no authentication required. Implement JWT in production.

## Feature 1: Route Calculation

### POST `/routes/estimate`
Estimate the shortest/fastest route between two street addresses with real-time traffic data.

#### Request Body (Minimal)
```json
{
  "start": {
    "address": "Queen Street, Auckland, New Zealand"
  },
  "end": {
    "address": "Hamilton City Centre, New Zealand"
  }
}
```

#### Request Body (Full)
```json
{
  "start": {
    "address": "Queen Street, Auckland, New Zealand"
  },
  "end": {
    "address": "Hamilton City Centre, New Zealand"
  },
  "vehicle_type": "rmc_truck",
  "vehicle_id": "RMC-001",
  "load_weight": 8000,
  "load_volume": 10,
  "departure_datetime": "2026-03-12T14:30:00",
  "priority": "normal"
}
```

#### Query Parameters
- None

#### Response (200 OK)
```json
{
  "id": 1,
  "start": {
    "address": "Queen Street, Auckland, New Zealand"
  },
  "end": {
    "address": "Hamilton City Centre, New Zealand"
  },
  "resolved_start_address": "Queen Street, Auckland 1010, New Zealand",
  "resolved_end_address": "Hamilton, 3204, New Zealand",
  "vehicle_type": "heavy_truck",
  "vehicle_id": "RMC-001",
  "load_weight": 8000,
  "load_volume": 10,
  "departure_datetime": "2026-03-12T14:30:00",
  "priority": "normal",
  "distance_meters": 101000,
  "duration_seconds": 3600,
  "traffic_delay_seconds": 300,
  "polyline": "encoded_polyline_string",
  "route_steps": [
    {
      "start_location": {
        "latitude": -37.8136,
        "longitude": 174.7662
      },
      "end_location": {
        "latitude": -37.8140,
        "longitude": 174.7670
      },
      "instruction": "Head north on Queen Street",
      "distance_meters": 1000,
      "duration_seconds": 60
    }
  ],
  "created_at": "2026-03-11T10:00:00",
  "updated_at": "2026-03-11T10:00:00"
}
```

#### Error Responses

**400 Bad Request**
```json
{
  "detail": "Could not geocode address: Invalid street name"
}
```

**500 Internal Server Error**
```json
{
  "detail": "Failed to calculate route. Please try again later."
}
```

---

### GET `/routes/{route_id}`
Retrieve a previously calculated route.

#### Parameters
- `route_id` (path, required): The ID of the route to retrieve

#### Response (200 OK)
Same as POST `/routes/estimate` response

#### Error Responses
**404 Not Found**
```json
{
  "detail": "Route 999 not found"
}
```

---

### GET `/routes`
Retrieve route history with optional filters.

#### Query Parameters
- `vehicle_id` (optional): Filter by specific vehicle
- `limit` (optional, default: 10, max: 100): Maximum number of routes to return

#### Response (200 OK)
```json
[
  {
    "id": 1,
    "start": {...},
    "end": {...},
    ...
  },
  {
    "id": 2,
    "start": {...},
    "end": {...},
    ...
  }
]
```

---

## Health Check

### GET `/health`
Check API health status.

#### Response (200 OK)
```json
{
  "status": "healthy",
  "service": "RMC Delivery Route Optimizer",
  "version": "1.0.0"
}
```

---

## Data Models

### Coordinate
```
{
  "latitude": float (-90 to 90),
  "longitude": float (-180 to 180)
}
```

### LocationRequest
```
{
  "address": string (required, min 3 characters)
    Example: "Queen Street, Auckland" or "Hamilton City Centre"
}
```

### RouteRequest
```
{
  "start": LocationRequest (required),
  "end": LocationRequest (required),
  "vehicle_type": string (default: "rmc_truck"),
  "vehicle_id": string (optional),
  "load_weight": float (optional, kg),
  "load_volume": float (optional, m³),
  "departure_datetime": ISO 8601 datetime (optional),
  "priority": "normal" | "urgent" | "economy" (default: "normal")
}
```

### RouteStep
```
{
  "start_location": Coordinate,
  "end_location": Coordinate,
  "instruction": string,
  "distance_meters": float,
  "duration_seconds": float
}
```

### RouteResponse
```
{
  "id": integer,
  "start": LocationRequest,
  "end": LocationRequest,
  "resolved_start_address": string,
  "resolved_end_address": string,
  "vehicle_type": string,
  "vehicle_id": string (optional),
  "load_weight": float (optional),
  "load_volume": float (optional),
  "departure_datetime": ISO 8601 datetime (optional),
  "priority": string,
  "distance_meters": float,
  "duration_seconds": float,
  "traffic_delay_seconds": float (optional),
  "polyline": string (optional),
  "route_steps": array of RouteStep,
  "created_at": ISO 8601 datetime,
  "updated_at": ISO 8601 datetime
}
```

---

## Status Codes

| Code | Meaning |
|------|---------|
| 200 | OK - Request successful |
| 400 | Bad Request - Invalid input parameters |
| 404 | Not Found - Resource not found |
| 500 | Internal Server Error - Server error |

---

## Pagination

Use `limit` parameter to paginate results. Maximum limit is 100.

---

## Rate Limiting

Configured to allow 100 requests per 60 seconds per API key.

---

## Interactive API Documentation

Visit `/api/v1/docs` for Swagger UI or `/api/v1/redoc` for ReDoc (when API is running).

