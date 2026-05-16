# NZ RMC Delivery Route Optimizer — Project Reference

## Business Context

**Ready-Mix Concrete (RMC)** is one of the most time-critical logistics problems in construction. Once concrete is batched at a plant, the clock starts. Under **NZS 3109** (New Zealand standard), concrete must be poured within **90 minutes** of mixing — or it is wasted. A single wasted load costs hundreds of dollars in materials alone, plus labour, site delays, and contractual penalties.

Auckland's road network is congested and unpredictable. A dispatcher managing 5–20 simultaneous deliveries has to:
- Pick the right plant (closest is not always fastest at 5 PM on a Friday)
- Estimate if the truck will beat the concrete's expiry
- Re-route trucks mid-delivery when traffic worsens
- Know instantly if a load is about to expire

This system automates all of that with real-time traffic data, predictive risk scoring, and proactive alerts.

---

## What This System Does (Business Summary)

| Capability | What it means in practice |
|---|---|
| **Plant selection** | Dispatcher enters a job site address and concrete brand → system ranks all plants of that brand by remaining concrete life, not just distance |
| **Delivery prediction** | For each plant→site route, system calculates Google ETA, adjusts it using NZTA Auckland traffic patterns, and gives a 0–100% success probability |
| **Dispatch scheduling** | Dispatcher picks a plant and schedules a departure time → system creates a trip record and stores the route |
| **Live monitoring** | Once a truck departs and concrete is batched, the system starts a 90-minute countdown and monitors traffic every 2 minutes |
| **Automatic rerouting** | If traffic worsens >15% or adds >5 minutes, the system finds a better route and notifies the dispatcher in real time |
| **Load expiry alerts** | If the load is approaching 60 / 75 / 90 minutes, the system escalates alerts: WARNING → CRITICAL → EXPIRED (emergency) |
| **Retarder advisory** | If delay risk is high but load is still saveable, the system recommends adding chemical retarder (+30 min extension) |
| **Trip history & audit** | Every event (position update, reroute, traffic check, status change) is logged immutably for compliance and review |

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend API** | Python 3.11+, FastAPI, Uvicorn |
| **Database** | SQLite (dev) / PostgreSQL (prod), SQLAlchemy ORM |
| **External APIs** | Google Maps Directions API, Google Geocoding API |
| **Weather** | Open-Meteo (free, no API key) |
| **LLM (optional)** | Ollama `qwen2.5:3b` (local, private, no API cost) |
| **Frontend** | Next.js 14, TypeScript, Tailwind CSS, Leaflet maps |
| **Caching** | In-process TTLCache (cachetools) — geocode 24h, directions 10 min |
| **Real-time** | Server-Sent Events (SSE) for live trip updates |
| **Containerisation** | Docker + docker-compose |

---

## System Architecture

```
┌────────────────────────────────────────────────────────────┐
│                   Next.js Web Client                        │
│  DispatchPanel │ TripsListPanel │ TripManagement │ MapView  │
└─────────────────────────┬──────────────────────────────────┘
                          │ REST + SSE
┌─────────────────────────▼──────────────────────────────────┐
│                    FastAPI Backend                          │
│                                                            │
│  /api/v1/plants    /api/v1/trips    /api/v1/routes         │
│  /api/v1/predict                                           │
│                                                            │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐   │
│  │ Prediction  │  │ Trip        │  │ Route            │   │
│  │ Service     │  │ Service     │  │ Service          │   │
│  └──────┬──────┘  └──────┬──────┘  └────────┬─────────┘   │
│         │                │                   │             │
│  ┌──────▼────────────────▼───────────────────▼──────────┐  │
│  │              GoogleMapsService (cached)               │  │
│  │     Geocoding (24h TTL)  │  Directions (10 min TTL)   │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              RMC Domain Layer                        │   │
│  │  LoadManager │ AlertService │ FeasibilityPipeline    │   │
│  │  DeliveryPredictor │ DispatchEngine                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                            │
│  ┌──────────────────────────┐                             │
│  │  Background Traffic      │  ← Runs every 120 seconds   │
│  │  Monitor                 │    for all active trips      │
│  └──────────────────────────┘                             │
└────────────────────────────────────────────────────────────┘
```

---

## Repository Structure

```
rmc-delivery/
├── app/
│   ├── main.py                  # FastAPI application factory, lifespan, logging
│   ├── config.py                # Settings from env / credentials.json
│   ├── dependencies.py          # FastAPI dependency injection (singletons)
│   │
│   ├── api/v1/endpoints/
│   │   ├── plants.py            # GET /plants, POST /plants/analyse
│   │   ├── predictions.py       # POST /predict/delivery, POST /predict/best-plant
│   │   ├── routes.py            # POST /routes/estimate, GET /routes/{id}
│   │   └── trips.py             # Full trip lifecycle (dispatch → begin → complete)
│   │
│   ├── db/
│   │   ├── database.py          # SQLAlchemy engine + session factory
│   │   └── models.py            # ORM models: Route, Trip, TripEvent, Vehicle, TrafficSnapshot
│   │
│   ├── domain/
│   │   ├── enums.py             # LoadStatus, ConcreteGrade, FeasibilityResult, etc.
│   │   ├── events.py            # Domain events: LoadBatched, LoadExpired, RetarderRecommended
│   │   ├── exceptions.py        # Domain exceptions: DispatchError, FeasibilityError
│   │   └── values.py            # Immutable value objects: LoadTimer, ConcreteSpec, Plant
│   │
│   ├── rmc/                     # Core RMC business logic (no HTTP, no DB)
│   │   ├── predictor.py         # DeliveryPredictor — NZTA-calibrated risk scoring
│   │   ├── load_manager.py      # LoadManager — 90-minute countdown + status transitions
│   │   ├── alerts.py            # AlertService — Observer event bus
│   │   ├── feasibility.py       # FeasibilityPipeline — Chain of Responsibility checks
│   │   ├── dispatch.py          # DispatchEngine — Strategy pattern for plant selection
│   │   └── interfaces.py        # Protocols (IRouteCalculator, ILoadTracker, etc.)
│   │
│   ├── services/
│   │   ├── google_maps.py       # Google Directions + Geocoding with TTL caching
│   │   ├── route.py             # Route estimation, geocoding, DB persistence
│   │   ├── trip.py              # Trip lifecycle, rerouting, SSE, position tracking
│   │   ├── prediction.py        # PredictionService — orchestrates Google + Weather + AI
│   │   ├── plant_locator.py     # Haversine pre-filter (free) before Google API calls
│   │   ├── traffic_monitor.py   # Background async task — proactive rerouting
│   │   ├── weather.py           # Open-Meteo weather + RMC delivery impact factors
│   │   └── llm_analyzer.py      # Ollama LLM narrative generation (optional, graceful fallback)
│   │
│   └── schemas/
│       └── __init__.py          # All Pydantic request/response schemas
│
├── config/
│   ├── plants.json              # Static catalogue: ~20 Auckland concrete plants
│   ├── credentials.json         # API keys (gitignored)
│   └── credentials.example.json # Template for credentials.json
│
├── client/                      # Legacy Gradio prototype (superseded by rmc-delivery-web)
├── tests/                       # pytest test suite
├── notebooks/                   # Jupyter analysis notebooks
└── docker-compose.yml           # Full stack: API + PostgreSQL
```

---

## API Reference

### Plants

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/plants` | List all active plants (filterable by brand, region) |
| `GET` | `/api/v1/plants/brands` | List distinct brands (for dropdown) |
| `GET` | `/api/v1/plants/{id}` | Get a single plant |
| `POST` | `/api/v1/plants/analyse` | **Core dispatch planning** — rank plants by concrete life for a job site |

**`POST /plants/analyse` flow:**
1. Receives brand + job site address + concrete mix
2. Geocodes job site once (cached 24h)
3. Filters plants by Haversine distance (free, no API cost)
4. Calls Google Directions only for top N candidates (typically 3–5)
5. Scores each plant: adjusted ETA → remaining concrete life → success probability
6. Returns ranked list with risk levels. Result cached 10 min.

### Trips

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/trips/dispatch` | Schedule a pending trip (plant → job site, future date) |
| `POST` | `/api/v1/trips/{id}/begin` | Activate trip — concrete is batched, truck is leaving |
| `GET` | `/api/v1/trips/active` | List active trips (in_progress, paused, pending) |
| `GET` | `/api/v1/trips/all` | List all trips with any status |
| `GET` | `/api/v1/trips/{id}` | Get full trip state |
| `GET` | `/api/v1/trips/{id}/stream` | SSE stream for real-time updates |
| `POST` | `/api/v1/trips/{id}/position` | Report GPS position |
| `POST` | `/api/v1/trips/{id}/pause` | Pause a trip |
| `POST` | `/api/v1/trips/{id}/resume` | Resume a paused trip |
| `POST` | `/api/v1/trips/{id}/complete` | Mark trip complete (records outcome) |
| `POST` | `/api/v1/trips/{id}/cancel` | Cancel a trip |

### Routes

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/routes/estimate` | Calculate route with real-time traffic |
| `GET` | `/api/v1/routes/{id}` | Fetch stored route |
| `POST` | `/api/v1/routes/reroute` | Calculate reroute from current position |
| `GET` | `/api/v1/routes/cache/stats` | Cache performance metrics |

### Prediction (advanced)

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/predict/delivery` | Full prediction for one plant→site route |
| `POST` | `/api/v1/predict/best-plant` | Automated best plant selection |

---

## Dispatch UI Flow (Step by Step)

```
Step 1 — Plan
  Dispatcher selects: Brand (e.g. "Holcim") + Concrete Mix (GP/HE/RE) + Job Site Address
  → POST /plants/analyse
  → System returns all brand plants ranked by remaining concrete life

Step 2 — Select Plant
  Dispatcher reviews: ETA, adjusted ETA, remaining life, success %, risk badge
  → Clicks "Select This Plant"

Step 3 — Schedule
  Dispatcher sets: Departure Date & Time (NZST), Volume (m³), Vehicle ID
  → POST /trips/dispatch
  → System creates a route + pending trip in the DB

On Pour Day
  Driver loads truck → dispatcher clicks "Begin Trip" in Live Trip tab
  → POST /trips/{id}/begin
  → 90-minute load timer starts
  → Background traffic monitor begins checking every 2 minutes
  → Dispatcher receives real-time SSE updates

Trip Ends
  → POST /trips/{id}/complete  (or /cancel)
  → Outcome (succeeded/failed) is recorded for analytics
```

---

## Trip Lifecycle

```
pending ──(begin)──→ in_progress ──(pause)──→ paused
                         │                       │
                         │         ←──(resume)───┘
                         │
                    (complete / cancel)
                         │
                    completed / cancelled
```

---

## Concrete Load Timer

Every trip that begins has a running clock based on NZS 3109:

| Mix | Max Life | Grade |
|---|---|---|
| GP (General Purpose) | 90 min | Standard |
| HE (High Early) | 60 min | Faster set, less tolerance |
| RE (Retarded) | 120 min | Chemical retarder pre-added |

Status transitions:
- `fresh` → 0–60 min (GP): no action
- `warning` → 60–75 min: consider adding retarder
- `critical` → 75–90 min: pour immediately
- `expired` → 90+ min: reject load, do not pour

With retarder applied: +30–60 min extension depending on grade.

---

## Core Domain Models (Database)

### `routes`
Stores every calculated route — start/end addresses (geocoded to lat/lng), distance, duration, traffic delay, polyline, route steps, alternative routes. Created by both the Route and Dispatch flows.

### `trips`
The active delivery record. Links to a route and adds:
- Truck GPS position (updated in real time)
- Reroute count and history
- Full RMC fields: `batch_time`, `load_expiry_time`, `load_status`, `concrete_grade`, `volume_m3`, `plant_id`
- Scheduling: `scheduled_at`, `concrete_mix`
- Outcome: `succeeded` / `failed`

### `trip_events`
Immutable append-only event log. Every status change, position update, traffic check, reroute, and alert is stored here. Used for audit, replay, and analytics. Never deleted.

### `traffic_snapshots`
Point-in-time traffic conditions captured during route calculations.

---

## RMC Domain Layer (`app/rmc/`)

All business logic is isolated here — no HTTP calls, no ORM dependencies. Pure Python, fully testable.

### `DeliveryPredictor` (`predictor.py`)
Calculates risk score for a planned delivery using real NZTA Auckland traffic data.
- NZTA hourly congestion indices (measured traffic volume patterns, Auckland TMS)
- Day-of-week multipliers (Friday PM is worst, Sunday is best)
- Outputs: adjusted ETA, success probability (0–1), risk level (low/medium/high/critical), time buffer
- Self-improving: as real trip outcomes accumulate in DB, factors are recalibrated

### `LoadManager` (`load_manager.py`)
The 90-minute countdown engine.
- Tracks `fresh → warning → critical → expired` transitions
- Recommends retarder when delay risk is detected early enough
- Emits domain events (`LoadStatusChanged`, `RetarderRecommended`, `LoadExpired`)
- Stateless — all state lives in the immutable `LoadTimer` value object

### `AlertService` (`alerts.py`)
Observer-pattern event bus. Decouples event producers from consumers.
- Producers: `LoadManager`, `TripService`
- Consumers: `LoggingAlertHandler`, `SSEAlertHandler` (pushes to connected browsers)
- New alert channels (email, SMS, webhook) can be added by registering a new handler

### `FeasibilityPipeline` (`feasibility.py`)
Chain of Responsibility — pre-dispatch checks run in sequence:
1. `TimeCheck` — will the truck make it before expiry?
2. `GradeCheck` — does the grade match the window constraints?
3. `CapacityCheck` — does the plant have the required volume?
Results: `FEASIBLE`, `MARGINAL`, `INFEASIBLE`, `REQUIRES_RETARDER`

### `DispatchEngine` (`dispatch.py`)
Strategy pattern — pluggable plant selection algorithms:
- `NearestPlantStrategy` — minimise distance
- `FastestRouteStrategy` — minimise traffic-adjusted ETA
- `LeastCostStrategy` — minimise composite cost

---

## Services Layer (`app/services/`)

### `GoogleMapsService` (`google_maps.py`)
Wraps Google Directions + Geocoding APIs with aggressive caching:
- Geocode cache: 24-hour TTL (addresses don't change)
- Directions cache: 10-minute TTL, 15-minute time buckets for departure_time
- `coarse_start=True` mode: snaps start coordinates to ~1.1km grid — prevents cache misses from minor truck movements during background traffic checks

### `RouteService` (`route.py`)
Orchestrates route estimation: geocode → Directions API → persist to DB.
- Clamps past `departure_time` to `now` (Google returns `ZERO_RESULTS` for past times)
- Supports alternative routes, waypoints, avoid options

### `TripService` (`trip.py`)
The heaviest service — manages the full trip lifecycle:
- Dispatch (pending trip creation)
- Begin (load timer start, status → in_progress)
- Position updates (GPS tracking, auto-complete when < 200m from destination)
- `check_and_reroute` — called by the background monitor every 2 min. Skips API call if truck moved < 200m since last check (major cost saving)
- SSE subscriber registry for real-time push to browsers

### `PredictionService` (`prediction.py`)
Orchestrates the full prediction pipeline for a single plant→site pair:
1. Geocode both addresses
2. Google Directions (live traffic ETA)
3. Weather at job site (Open-Meteo)
4. DeliveryPredictor (NZTA-calibrated risk score)
5. LLMAnalyzer (plain-English narrative, optional)

### `PlantLocator` (`plant_locator.py`)
Free Haversine pre-filter. Eliminates plants too far to make the delivery window before a single Google API call is made. Typically reduces 20 plants → 3–5 candidates.

### `WeatherService` (`weather.py`)
Open-Meteo integration (free, no API key). Returns RMC delivery impact factors:
- `speed_multiplier` — travel time factor for rain/wind
- `concrete_setting_factor` — NZS 3109 temperature correction for setting time
- `pump_truck_safe` — False if wind gusts > 60 km/h

### `TrafficMonitor` (`traffic_monitor.py`)
Background asyncio task. Every 120 seconds:
1. Queries all `in_progress` trips
2. For each trip, calls `check_and_reroute` (skipped if truck hasn't moved)
3. Evaluates load timer — emits alerts if status changed
4. Inter-trip delay: 2 seconds between checks to avoid API rate spikes

### `LLMAnalyzer` (`llm_analyzer.py`)
Optional Ollama integration (`qwen2.5:3b`). The LLM only explains — it never calculates. All numbers are pre-computed by `DeliveryPredictor` and passed as facts. Deterministic template fallback if Ollama is not running.

---

## Cost Management — Google API

Google Directions API is the primary ongoing cost. The following measures minimise calls:

| Mechanism | Saving |
|---|---|
| Geocode TTL cache (24h) | Eliminates repeat geocoding of known addresses |
| Directions TTL cache (10 min) | Repeated route queries within 10 min = free |
| Haversine pre-filter | 20 plants → 3–5 candidates before Google is called |
| `analyse_brand` result cache (10 min) | Dispatcher re-clicks = 0 Google calls |
| `coarse_start` grid snapping (1.1km) | Truck minor movement = cache hit |
| Movement threshold (< 200m = skip) | Stationary trucks never trigger API calls |
| 15-min departure_time buckets | Near-identical departure times share one cached result |
| `departure_time` past-clamping | Prevents `ZERO_RESULTS` errors from past scheduled times |

---

## Frontend (`rmc-delivery-web/`)

Next.js 14 application. All times interpreted as **NZST (UTC+12)** regardless of browser locale.

| Component | Purpose |
|---|---|
| `DispatchPanel.tsx` | 3-step dispatch flow: Plan → Select Plant → Schedule |
| `TripsListPanel.tsx` | View all trips, filter by status, cancel with confirmation |
| `TripManagement.tsx` | Live trip controls: begin, pause, resume, complete, cancel |
| `TripEventLog.tsx` | Scrollable audit trail of all trip events |
| `MapView.tsx` | Leaflet map with route polyline and truck position |
| `RouteForm.tsx` | Manual route calculation form |

---

## Configuration

### `config/credentials.json`
```json
{
  "google_maps": {
    "api_key": "YOUR_KEY"
  },
  "database": {
    "type": "sqlite",
    "path": "./rmc_delivery.db"
  }
}
```
Switch to PostgreSQL by changing `type` to `postgres` and adding host/port/username/password fields.

### `config/plants.json`
Static catalogue of ~20 Auckland concrete batching plants (Holcim, Allied, Firth, Ready Mix brands) with verified GPS coordinates from Google Places. Add/remove plants by editing this file — no DB migrations required.

---

## Running Locally

```bash
# Backend
cd rmc-delivery
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload        # Run from project root

# Frontend
cd rmc-delivery-web
npm install
npm run dev                          # http://localhost:3000

# API docs
http://localhost:8000/docs           # Swagger UI
http://localhost:8000/redoc          # ReDoc
```

---

## Design Patterns Used

| Pattern | Where | Why |
|---|---|---|
| **Observer** | `AlertService` | Decouples load timer events from alert delivery channels |
| **Chain of Responsibility** | `FeasibilityPipeline` | Modular, ordered pre-dispatch checks |
| **Strategy** | `DispatchEngine` | Swap plant-selection algorithm without changing orchestration |
| **Repository** | `RouteService`, `TripService` | Database access isolated from business logic |
| **Value Object** | `LoadTimer`, `ConcreteSpec`, `Plant` | Immutable domain concepts, safe to share |
| **Dependency Injection** | FastAPI `Depends()` | Singleton services, testable, no global state |
| **TTL Cache** | `GoogleMapsService`, `plants.py` | API cost control without a Redis dependency |

---

## Key Business Rules

1. **90-minute rule** — GP concrete expires 90 min after batching (NZS 3109)
2. **HE concrete** — expires at 60 min (high early strength = faster hydration)
3. **RE concrete** — expires at 120 min (retarder already in mix)
4. **Retarder extension** — adds 30–60 min, recommended when `remaining - ETA < 10 min buffer`
5. **Reroute threshold** — triggered if new route is >15% slower OR adds >5 min vs expected
6. **Reroute cooldown** — minimum 3 min between reroutes to avoid thrashing
7. **Auto-complete** — trip automatically completes when truck is within 200m of destination
8. **NZST only** — all departure times displayed and entered in NZ Standard Time (UTC+12)


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
