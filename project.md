# NZ RMC Truck Route Optimizer

## Project Title
`NZ RMC Truck Route Optimizer`

## Overview
A Python FastAPI-based backend service for New Zealand RMC (Ready-Mix Concrete) trucks, integrating Google Traffic API to compute shortest and fastest delivery routes based on real-time traffic conditions, vehicle constraints, and delivery requirements.

## Goals
- Solve optimized routing for NZ concrete delivery trucks.
- Leverage Google Traffic API for real-time routing and ETA.
- Support multiple stops, payload-specific routing constraints, and return path.
- Expose REST endpoints for frontend / mobile dispatch integration.
- Keep compliance with NZ traffic and heavy vehicle routing.

## Tech Stack
- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic
- HTTPX (for external API calls)
- PostgreSQL 
- SQLAlchemy 
- Google Maps Distance Matrix API + Directions API (traffic model)
- Docker (containerization)
- GitHub Actions (CI)

## Core Features

### 1. Route Calculation
- **Endpoint**: `POST /api/routes/estimate`
- **Inputs**: start, destination(s), vehicle type, load parameters, departure datetime, priority
- **Output**: optimized route, distance, duration, traffic delay, polygon, steps

### 2. Traffic-Aware Routing
- Query Google Traffic-based route (driving, avoid tolls/highways optional)
- Provide "fastest" and "shortest" result variants

### 3. Multi-Stop Sequence Optimization
- Support `n` stops (up to business limit)
- Compute best order (TSP-like) with traffic ETA for each leg

### 4. Vehicle Constraints
- Truck height/width restrictions, weight-limits for bridges/roads
- NZ-specific restricted roads for heavy vehicles

### 5. Safety & Compliance
- Avoid urban low-bridge routes
- Provide warnings for no-go segments

### 6. Dispatch Metadata
- Save route plan records, driver info, vehicle id, job code
- **Endpoints**: `GET /api/routes/{id}` and `GET /api/routes/history`

### 7. Monitoring and Logs
- Record API latencies and traffic query changes
- Alert when Google quota near limit

### 8. Config & Administration
- Manage settings (max stops, route preference, fallback strategy)
- API keys secure in env

## Data Model

```
- Vehicle (id, type, height, width, max_weight, registration)
- RouteRequest (id, start, destinations, vehicle_id, load, priority, created_at)
- RouteSegment (route_id, leg_num, start_coord, end_coord, distance, duration, traffic_delay)
- TrafficSnapshot (timestamp, route_id, current_duration, condition)
- DeliveryTask (id, customer, address, time_window, status)
```

## Integration Flow
1. Client sends route request
2. Backend validates input
3. Query Google Directions (traffic) + optionally Distance Matrix
4. Run local optimization (stop order, penalties)
5. Apply constraints and returns route + IDs
6. Persist plan and return to client

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/routes/estimate` | Calculate route with traffic data |
| POST | `/api/v1/routes/optimize` | Optimize multi-stop sequence |
| GET | `/api/v1/routes/{route_id}` | Retrieve specific route |
| GET | `/api/v1/routes/history` | Fetch user route history |
| GET | `/api/v1/vehicles` | List available vehicles |
| POST | `/api/v1/vehicles` | Register new vehicle |

## Deployment
- Docker compose with FastAPI + DB
- CI/CD pipelines:
  - Lint, tests, security scan
  - Build/push Docker image
  - Deploy to GCP/Azure/AWS

## Non-Functional Requirements
- High availability
- Response time < 500ms for route compute (with caching)
- Secure API auth (JWT + RBAC)
- Rate limiting (e.g., 100 req/min)
- Comprehensive logging
- NZ locale/timezone handling

## Milestones

| Phase | Deliverable |
|-------|------------|
| 1 | Setup project skeleton + FastAPI boilerplate |
| 2 | Key route estimation endpoint + Google API integration |
| 3 | Multi-stop optimizer + weight/toll constraints |
| 4 | Data persistence + history endpoints |
| 5 | UI/dispatch integration + unit tests |
| 6 | Documentation + deployment automation |

## Optional Enhancements
- Live driver location telemetry + dynamic reroute
- Fuel consumption estimate
- Offline route fallback (cache baseline roads)
- Customer access for real-time ETA tracking
- Map visualization data (GeoJSON output)
- Driver shift compliance and hour-limits
- Cost analysis (fuel, tolls, time-based rates)

## Directory Structure (Proposed)
```
rmc-delivery/
├── project.md
├── requirements.txt
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── app/
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   ├── models/
│   ├── schemas/
│   ├── services/
│   │   ├── google_maps.py
│   │   ├── route_optimizer.py
│   │   └── vehicle_manager.py
│   ├── api/
│   │   └── v1/
│   │       ├── routes.py
│   │       └── vehicles.py
│   ├── db/
│   │   ├── database.py
│   │   └── models.py
│   └── utils/
├── tests/
│   ├── test_routes.py
│   └── test_optimizer.py
└── docs/
    └── API.md
```

---

**Last Updated**: March 11, 2026
