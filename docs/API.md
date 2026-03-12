# RMC Delivery Route Optimizer — API Documentation

> **Version:** 1.0.0  
> **Base URL:** `http://localhost:8000/api/v1`  
> **Interactive Docs:** [Swagger UI](http://localhost:8000/docs) · [ReDoc](http://localhost:8000/redoc)

---

## Table of Contents

- [RMC Delivery Route Optimizer — API Documentation](#rmc-delivery-route-optimizer--api-documentation)
  - [Table of Contents](#table-of-contents)
  - [Overview](#overview)
    - [Architecture](#architecture)
  - [Authentication](#authentication)
  - [Routes — Route Calculation](#routes--route-calculation)
    - [POST `/routes/estimate`](#post-routesestimate)
    - [POST `/routes/reroute`](#post-routesreroute)
    - [GET `/routes/{route_id}`](#get-routesroute_id)
    - [GET `/routes`](#get-routes)
    - [GET `/routes/cache/stats`](#get-routescachestats)
  - [Trips — Active Delivery Management](#trips--active-delivery-management)
    - [Trip Lifecycle](#trip-lifecycle)
    - [POST `/trips/start`](#post-tripsstart)
    - [GET `/trips/active`](#get-tripsactive)
    - [GET `/trips/{trip_id}`](#get-tripstrip_id)
    - [GET `/trips/{trip_id}/events`](#get-tripstrip_idevents)
    - [POST `/trips/{trip_id}/position`](#post-tripstrip_idposition)
    - [POST `/trips/{trip_id}/check`](#post-tripstrip_idcheck)
    - [POST `/trips/{trip_id}/pause`](#post-tripstrip_idpause)
    - [POST `/trips/{trip_id}/resume`](#post-tripstrip_idresume)
    - [POST `/trips/{trip_id}/complete`](#post-tripstrip_idcomplete)
    - [POST `/trips/{trip_id}/cancel`](#post-tripstrip_idcancel)
    - [GET `/trips/{trip_id}/stream`](#get-tripstrip_idstream)
  - [Data Models](#data-models)
    - [Coordinate](#coordinate)
    - [LocationRequest](#locationrequest)
    - [RouteStep](#routestep)
    - [TripResponse](#tripresponse)
    - [TripRerouteInfo](#triprerouteinfo)
    - [TripEventResponse](#tripeventresponse)
    - [ErrorResponse](#errorresponse)
  - [Real-Time Events (SSE)](#real-time-events-sse)
  - [Background Traffic Monitor](#background-traffic-monitor)
    - [Configuration](#configuration)
    - [Behavior](#behavior)
  - [Error Handling](#error-handling)
  - [Status Codes](#status-codes)
  - [Health Check](#health-check)
    - [GET `/health`](#get-health)
  - [Typical Workflow](#typical-workflow)

---

## Overview

REST API for calculating optimized delivery routes for New Zealand RMC (Ready-Mix Concrete) trucks. Features include:

- **Route calculation** with real-time traffic via Google Maps Directions API
- **Alternative routes** with comparison summaries
- **Active trip management** — start, pause, resume, complete, cancel
- **Automatic rerouting** — background traffic monitor proactively reroutes active deliveries
- **Real-time SSE stream** — push notifications for reroutes, traffic updates, and status changes
- **Full audit trail** — every position update, traffic check, and reroute logged as an immutable event

### Architecture

```
┌──────────────────┐    REST/SSE     ┌────────────────────────────────────────────┐
│   Next.js / App  │ ◄────────────► │              FastAPI Backend               │
└──────────────────┘                │                                            │
                                    │  ┌──────────────┐  ┌─────────────────────┐ │
                                    │  │ RouteService  │  │    TripService      │ │
                                    │  └──────┬───────┘  └──────────┬──────────┘ │
                                    │         │                     │            │
                                    │  ┌──────▼─────────────────────▼──────────┐ │
                                    │  │         Google Maps API (httpx)       │ │
                                    │  └──────────────────────────────────────┘ │
                                    │                                            │
                                    │  ┌──────────────────────────────────────┐  │
                                    │  │  Background Traffic Monitor (asyncio)│  │
                                    │  │  • Checks all active trips every 2m  │  │
                                    │  │  • Auto-reroutes on delay detection  │  │
                                    │  │  • Pushes SSE events to subscribers  │  │
                                    │  └──────────────────────────────────────┘  │
                                    │                                            │
                                    │  ┌──────────────────────────────────────┐  │
                                    │  │  SQLite / PostgreSQL (SQLAlchemy)    │  │
                                    │  │  Tables: routes, trips, trip_events  │  │
                                    │  └──────────────────────────────────────┘  │
                                    └────────────────────────────────────────────┘
```

---

## Authentication

Currently no authentication required. Implement JWT/API key auth in production.

---

## Routes — Route Calculation

### POST `/routes/estimate`

Calculate the optimal route between two street addresses with real-time traffic data.

**Request Body (Minimal)**
```json
{
  "start": { "address": "Queen Street, Auckland, New Zealand" },
  "end": { "address": "Hamilton City Centre, New Zealand" }
}
```

**Request Body (Full)**
```json
{
  "start": { "address": "Queen Street, Auckland, New Zealand" },
  "end": { "address": "Hamilton City Centre, New Zealand" },
  "vehicle_type": "rmc_truck",
  "vehicle_id": "RMC-001",
  "load_weight": 8000,
  "load_volume": 10,
  "departure_datetime": "2026-03-12T14:30:00",
  "priority": "normal",
  "max_delivery_minutes": 90,
  "request_alternatives": true,
  "avoid": ["tolls", "ferries"],
  "route_index": 0
}
```

**Mandatory vs optional inputs:**

> **Google Maps Directions API only requires an origin and destination.** Everything else below is either an optional Google parameter or fleet-tracking metadata that does not affect routing.

| Field | Type | Required | Default | Affects routing? | Description |
|-------|------|----------|---------|:---:|-------------|
| `start.address` | string | ✅ | — | ✅ | Origin address — geocoded to lat/lng, sent to Google as `origin` |
| `end.address` | string | ✅ | — | ✅ | Destination address — geocoded to lat/lng, sent to Google as `destination` |
| `priority` | string | — | `"normal"` | ✅ | Maps to Google `traffic_model` (see table below) — changes ETA by ~5-15% |
| `avoid` | string[] | — | `null` | ✅ | Sent to Google as `avoid` param: `tolls`, `highways`, `ferries` |
| `request_alternatives` | bool | — | `false` | ✅ | Sent to Google as `alternatives=true` — returns up to 3 routes |
| `route_index` | int | — | `0` | ✅ | Which alternative to use (0 = primary) |
| `departure_datetime` | ISO 8601 | — | now | ✅ | Sent to Google as `departure_time` — affects traffic calculation |
| `waypoints` | Coordinate[] | — | `null` | ✅ | Sent to Google as `waypoints` — intermediate stops |
| `vehicle_type` | string | — | `"rmc_truck"` | ❌ | Fleet metadata only — stored in DB for reports. Google treats all vehicles as cars. |
| `vehicle_id` | string | — | `null` | ❌ | Fleet tracking — "which truck ran this route." Not sent to Google. |
| `load_weight` | float | — | `null` | ❌ | Business metadata — stored but not used in routing logic |
| `load_volume` | float | — | `null` | ❌ | Business metadata — stored but not used in routing logic |
| `max_delivery_minutes` | int | — | `null` | ❌ | Post-calculation check — flags if calculated duration exceeds this limit |

**Priority → Traffic Model Mapping:**

| Priority | Google Traffic Model | Behavior |
|----------|---------------------|----------|
| `urgent` / `high` | `pessimistic` | Worst-case traffic estimate |
| `normal` | `best_guess` | Most likely duration |
| `low` / `economy` | `optimistic` | Best-case traffic estimate |

**Response `200 OK`**
```json
{
  "id": 1,
  "start": { "address": "Queen Street, Auckland, New Zealand" },
  "end": { "address": "Hamilton City Centre, New Zealand" },
  "resolved_start_address": "Queen Street, Auckland 1010, New Zealand",
  "resolved_end_address": "Hamilton, 3204, New Zealand",
  "start_lat": -36.8485,
  "start_lng": 174.7633,
  "end_lat": -37.7870,
  "end_lng": 175.2793,
  "vehicle_type": "rmc_truck",
  "vehicle_id": "RMC-001",
  "load_weight": 8000,
  "load_volume": 10,
  "departure_datetime": "2026-03-12T14:30:00",
  "priority": "normal",
  "distance_meters": 128450,
  "duration_seconds": 5640,
  "traffic_delay_seconds": 420,
  "exceeds_delivery_limit": false,
  "delivery_limit_exceeded_by": null,
  "polyline": "p~}eFyraiMlAoB~Cq@xD...",
  "route_steps": [
    {
      "start_location": { "latitude": -36.8485, "longitude": 174.7633 },
      "end_location": { "latitude": -36.8502, "longitude": 174.7651 },
      "instruction": "Head south on Queen St toward Customs St",
      "distance_meters": 240,
      "duration_seconds": 35
    }
  ],
  "total_alternatives": 3,
  "selected_route_index": 0,
  "alternatives_summary": [
    { "index": 1, "distance_meters": 132100, "duration_seconds": 5820, "summary": "via SH2" },
    { "index": 2, "distance_meters": 141200, "duration_seconds": 6100, "summary": "via SH27" }
  ],
  "request_alternatives": true,
  "avoid": ["tolls", "ferries"],
  "route_index": 0,
  "created_at": "2026-03-11T10:00:00",
  "updated_at": "2026-03-11T10:00:00"
}
```

**Errors:** `400` Invalid address / geocoding failure · `500` Google API or internal error

---

### POST `/routes/reroute`

Lightweight traffic probe from the truck's current GPS position. Does **not** persist to DB.

**Request Body**
```json
{
  "current_lat": -36.9100,
  "current_lng": 174.8200,
  "end": { "address": "Hamilton City Centre, New Zealand" },
  "vehicle_type": "rmc_truck",
  "priority": "normal",
  "avoid": ["tolls"]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `current_lat` | float | ✅ | Truck's current latitude |
| `current_lng` | float | ✅ | Truck's current longitude |
| `end.address` | string | ✅ | Destination address |
| `vehicle_type` | string | — | Default: `"rmc_truck"` |
| `priority` | string | — | Default: `"normal"` |
| `avoid` | string[] | — | Features to avoid |

**Query Parameters**

| Param | Type | Description |
|-------|------|-------------|
| `original_duration` | float | Original trip duration (seconds) for comparison |

**Response `200 OK`**
```json
{
  "distance_meters": 95200,
  "duration_seconds": 4100,
  "traffic_delay_seconds": 180,
  "polyline": "nzreFq{`iM...",
  "route_steps": [...],
  "reroute_recommended": true,
  "reason": "Route is 22% slower than original (traffic congestion detected)"
}
```

**Reroute logic:** Recommended if >15% slower than original OR >5 min absolute delay.

---

### GET `/routes/{route_id}`

Retrieve a previously calculated route by ID.

**Response `200 OK`** — Same schema as `POST /routes/estimate`  
**Errors:** `404` Route not found

---

### GET `/routes`

Retrieve route history with optional filters.

| Query Param | Type | Default | Description |
|-------------|------|---------|-------------|
| `vehicle_id` | string | — | Filter by vehicle |
| `limit` | int | `10` | Max results (1–100) |

**Response `200 OK`** — Array of `RouteResponse`

---

### GET `/routes/cache/stats`

Returns cache hit/miss stats for geocoding, directions, and route caches.

**Response `200 OK`**
```json
{
  "geocode_hits": 42,
  "geocode_misses": 8,
  "geocode_cache_size": 12,
  "directions_hits": 31,
  "directions_misses": 15,
  "directions_cache_size": 10,
  "route_hits": 18,
  "route_misses": 6,
  "route_cache_size": 6
}
```

---

## Trips — Active Delivery Management

Trips represent an **active delivery in progress**. A trip is created from a calculated route and is tracked with GPS position updates, automatic traffic monitoring, and real-time rerouting.

### Trip Lifecycle

```
                  ┌──────────┐
                  │  pending  │
                  └─────┬────┘
                        │ start_trip
                  ┌─────▼────┐
             ┌───►│in_progress│◄───┐
             │    └──┬──┬──┬─┘    │
             │       │  │  │      │
        resume│ pause│  │  │cancel│
             │       │  │  │      │
          ┌──┴──┐    │  │  │  ┌───▼─────┐
          │paused│◄───┘  │  └─►│cancelled│
          └─────┘        │    └─────────┘
                         │ complete (manual or auto < 200m)
                   ┌─────▼────┐
                   │ completed │
                   └──────────┘
```

---

### POST `/trips/start`

Start a new tracked trip from a previously calculated route. This activates background traffic monitoring.

**Request Body**
```json
{
  "route_id": 1,
  "vehicle_id": "RMC-001"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `route_id` | int | ✅ | ID of the calculated route |
| `vehicle_id` | string | — | Override vehicle (defaults to route's vehicle) |

**Response `200 OK`** — `TripResponse` (see [Data Models](#data-models))

**Side effects:**
- Trip status set to `in_progress`
- `trip_started` event logged
- Background monitor begins checking this trip every ~2 minutes

**Errors:** `404` Route not found

---

### GET `/trips/active`

List all trips with status `in_progress`, `paused`, or `pending`.

**Response `200 OK`** — Array of `TripResponse`

---

### GET `/trips/{trip_id}`

Get full trip state including the 20 most recent events.

**Response `200 OK`** — `TripResponse`  
**Errors:** `404` Trip not found

---

### GET `/trips/{trip_id}/events`

Get the trip's immutable event audit log.

| Query Param | Type | Default | Description |
|-------------|------|---------|-------------|
| `limit` | int | `50` | Max events to return |

**Response `200 OK`**
```json
[
  {
    "id": 12,
    "trip_id": 1,
    "event_type": "reroute_applied",
    "data": {
      "reroute_number": 2,
      "old_duration": 5640,
      "new_duration": 4900,
      "distance_saved_meters": 1200
    },
    "lat": -37.1200,
    "lng": 175.0100,
    "created_at": "2026-03-11T11:15:42"
  },
  {
    "id": 11,
    "trip_id": 1,
    "event_type": "reroute_suggested",
    "data": {
      "reason": "Heavy traffic — 8 min delay detected",
      "reroute_number": 2,
      "new_distance": 94800,
      "new_duration": 4900,
      "delay_seconds": 480
    },
    "lat": -37.1200,
    "lng": 175.0100,
    "created_at": "2026-03-11T11:15:42"
  }
]
```

**Event types:**

| Event Type | Description |
|------------|-------------|
| `trip_started` | Trip created and tracking began |
| `trip_paused` | Trip paused by user |
| `trip_resumed` | Trip resumed after pause |
| `trip_completed` | Trip finished (manual or auto-complete) |
| `trip_cancelled` | Trip cancelled |
| `position_update` | GPS position received |
| `traffic_check` | Background traffic probe result |
| `reroute_suggested` | Reroute recommended by engine |
| `reroute_applied` | New route applied to trip |
| `eta_updated` | ETA recalculated |
| `delay_detected` | Significant delay or repeated failures flagged |
| `delay_cleared` | Previously detected delay resolved |

---

### POST `/trips/{trip_id}/position`

Report the truck's current GPS position.

**Request Body**
```json
{
  "lat": -37.0500,
  "lng": 175.1200,
  "heading": 195.5,
  "speed_kmh": 72.3
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `lat` | float | ✅ | Latitude (−90 to 90) |
| `lng` | float | ✅ | Longitude (−180 to 180) |
| `heading` | float | — | Bearing in degrees (0–360) |
| `speed_kmh` | float | — | Current speed in km/h |

**Response `200 OK`** — Updated `TripResponse`

**Side effects:**
- Updates `current_lat`, `current_lng`, `heading`
- Recalculates remaining distance (haversine)
- Logs `position_update` event
- **Auto-completes trip** if within 200m of destination

**Errors:** `400` Trip not in progress/paused state

---

### POST `/trips/{trip_id}/check`

Force an immediate traffic check and reroute analysis (bypasses the 2-minute cycle).

**Response `200 OK`** — `TripRerouteInfo` if rerouted, or:
```json
{ "message": "Traffic is clear, no reroute needed" }
```

**Errors:** `404` Trip not found

---

### POST `/trips/{trip_id}/pause`

Pause an active trip. Background traffic checks will skip paused trips.

**Response `200 OK`** — Updated `TripResponse` with `status: "paused"`  
**Errors:** `400` Trip not in `in_progress` state

---

### POST `/trips/{trip_id}/resume`

Resume a paused trip. Background traffic monitoring resumes.

**Response `200 OK`** — Updated `TripResponse` with `status: "in_progress"`  
**Errors:** `400` Trip not in `paused` state

---

### POST `/trips/{trip_id}/complete`

Manually mark a trip as completed.

**Response `200 OK`** — Updated `TripResponse` with `status: "completed"`  
**Errors:** `400` Trip already completed/cancelled

---

### POST `/trips/{trip_id}/cancel`

Cancel a trip.

**Response `200 OK`** — Updated `TripResponse` with `status: "cancelled"`  
**Errors:** `400` Trip already completed/cancelled

---

### GET `/trips/{trip_id}/stream`

**Server-Sent Events (SSE)** stream for real-time trip updates.

```
GET /api/v1/trips/1/stream
Accept: text/event-stream
```

**Connection:** Long-lived HTTP connection. Sends heartbeat every 30 seconds.

**JavaScript client example:**
```javascript
const es = new EventSource('/api/v1/trips/1/stream');

es.addEventListener('reroute', (e) => {
  const data = JSON.parse(e.data);
  // data.new_polyline — updated encoded polyline
  // data.reason       — "Heavy traffic — 8 min delay detected"
  // data.new_steps    — updated turn-by-turn directions
  updateMapPolyline(data.new_polyline);
  showNotification(data.reason);
});

es.addEventListener('position', (e) => {
  const { lat, lng, remaining_km } = JSON.parse(e.data);
  moveTruckMarker(lat, lng);
});

es.addEventListener('traffic_ok', (e) => {
  const { remaining_km, delay_seconds, eta } = JSON.parse(e.data);
  updateETA(eta);
});

es.addEventListener('status', (e) => {
  const { status } = JSON.parse(e.data);
  // "paused", "completed", "cancelled"
  if (status === 'completed') showDeliveredBanner();
});

es.addEventListener('heartbeat', () => {
  // keepalive — no action needed
});
```

**curl example:**
```bash
curl -N http://localhost:8000/api/v1/trips/1/stream
```

**SSE event types:**

| Event | Payload | Description |
|-------|---------|-------------|
| `reroute` | `TripRerouteInfo` | New route applied — contains polyline, steps, reason |
| `position` | `{lat, lng, remaining_km}` | Truck position updated |
| `traffic_ok` | `{remaining_km, delay_seconds, eta}` | Traffic check passed, no reroute |
| `status` | `{status}` | Trip status changed |
| `heartbeat` | `{}` | Connection keepalive (every 30s) |

**Response headers:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

---

## Data Models

### Coordinate
```json
{
  "latitude": -36.8485,
  "longitude": 174.7633
}
```

### LocationRequest
```json
{
  "address": "Queen Street, Auckland, New Zealand"
}
```

### RouteStep
```json
{
  "start_location": { "latitude": -36.8485, "longitude": 174.7633 },
  "end_location": { "latitude": -36.8502, "longitude": 174.7651 },
  "instruction": "Head south on Queen St toward Customs St",
  "distance_meters": 240,
  "duration_seconds": 35
}
```

### TripResponse

Full trip state returned by all trip endpoints:

```json
{
  "id": 1,
  "route_id": 5,
  "status": "in_progress",

  "current_lat": -37.0500,
  "current_lng": 175.1200,
  "heading": 195.5,

  "start_address": "Queen Street, Auckland 1010, New Zealand",
  "end_address": "Hamilton, 3204, New Zealand",
  "start_lat": -36.8485,
  "start_lng": 174.7633,
  "end_lat": -37.7870,
  "end_lng": 175.2793,

  "vehicle_type": "rmc_truck",
  "vehicle_id": "RMC-001",
  "priority": "normal",
  "avoid_options": ["tolls"],

  "current_polyline": "p~}eFyraiMlAoB~Cq@xD...",
  "original_distance_meters": 128450,
  "original_duration_seconds": 5640,
  "remaining_distance_meters": 72100,
  "remaining_duration_seconds": 3200,
  "current_traffic_delay": 180,

  "reroute_count": 2,
  "last_reroute_at": "2026-03-11T11:15:42",
  "last_traffic_check_at": "2026-03-11T11:18:01",
  "estimated_arrival": "2026-03-11T12:10:00",

  "started_at": "2026-03-11T10:00:00",
  "completed_at": null,
  "created_at": "2026-03-11T10:00:00",
  "updated_at": "2026-03-11T11:18:01",

  "recent_events": [
    {
      "id": 15,
      "trip_id": 1,
      "event_type": "traffic_check",
      "data": { "condition": "clear", "delay_seconds": 180 },
      "lat": -37.0500,
      "lng": 175.1200,
      "created_at": "2026-03-11T11:18:01"
    }
  ]
}
```

### TripRerouteInfo

Returned when a reroute is applied (also pushed via SSE):

```json
{
  "trip_id": 1,
  "reroute_number": 2,
  "reason": "Heavy traffic — 8 min delay detected",
  "old_duration_seconds": 5640,
  "new_duration_seconds": 4900,
  "new_distance_meters": 94800,
  "traffic_delay_seconds": 480,
  "new_polyline": "xz}eFqr`iMnBpC...",
  "new_steps": [
    {
      "start_location": { "latitude": -37.12, "longitude": 175.01 },
      "end_location": { "latitude": -37.15, "longitude": 175.05 },
      "instruction": "Turn left onto SH1",
      "distance_meters": 4200,
      "duration_seconds": 180
    }
  ],
  "applied": true
}
```

### TripEventResponse

Single immutable audit log entry:

```json
{
  "id": 12,
  "trip_id": 1,
  "event_type": "reroute_applied",
  "data": {
    "reroute_number": 2,
    "old_duration": 5640,
    "new_duration": 4900
  },
  "lat": -37.1200,
  "lng": 175.0100,
  "created_at": "2026-03-11T11:15:42"
}
```

### ErrorResponse

```json
{
  "detail": "Route 999 not found",
  "error_code": null
}
```

---

## Real-Time Events (SSE)

The SSE stream (`GET /trips/{id}/stream`) uses an in-memory pub/sub system:

1. Client connects → a subscriber `asyncio.Queue` is registered for that trip
2. Any TripService action (position update, reroute, status change) pushes to all queues
3. SSE endpoint reads from queue and formats as `event: <type>\ndata: <json>\n\n`
4. Heartbeat every 30s keeps the connection alive through proxies/load balancers
5. On disconnect → subscriber queue is unregistered and garbage collected

**Note:** SSE subscribers are in-memory. If the server restarts, clients must reconnect. The trip state itself is persisted in the database.

---

## Background Traffic Monitor

An `asyncio` background task that runs for the lifetime of the application. Started automatically at API boot, stopped on shutdown.

### Configuration

| Setting | Value | Description |
|---------|-------|-------------|
| Check interval | **120s** | Full cycle runs every 2 minutes |
| Inter-trip delay | **2s** | Gap between individual trip checks (rate limiting) |
| Reroute threshold (ratio) | **>15%** | Reroute if new duration exceeds original by 15%+ |
| Reroute threshold (absolute) | **>5 min** | Reroute if absolute traffic delay exceeds 5 minutes |
| Reroute cooldown | **180s** | No re-reroute within 3 minutes of last reroute |
| Min distance for check | **1 km** | Skip check if truck is < 1 km from destination |
| Auto-complete distance | **200m** | Auto-complete trip if within 200m of destination |
| Max consecutive errors | **5** | Flag trip for manual review after 5 consecutive check failures |

### Behavior

- **Priority ordering:** Urgent trips are checked first, economy last
- **Rate limiting:** 2-second delay between individual trip checks to avoid Google API quota spikes
- **Exponential backoff:** If 3+ consecutive cycle-level errors occur, backs off up to 10 minutes
- **Error handling:** Individual trip check failures are isolated — one failing trip does not block others
- **Dead letter:** After 5 consecutive failures for a single trip, a `delay_detected` event is logged with `action: "manual_review_required"`

---

## Error Handling

All errors return a consistent JSON structure:

```json
{
  "detail": "Human-readable error message"
}
```

Common error patterns:

| Scenario | Status | Detail |
|----------|--------|--------|
| Invalid address | 400 | `"Could not geocode address: ..."` |
| Route not found | 404 | `"Route 999 not found"` |
| Trip not found | 404 | `"Trip 42 not found"` |
| Wrong trip state | 400 | `"Can only pause an in-progress trip"` |
| Trip already done | 400 | `"Trip already completed"` |
| Google API failure | 500 | `"Failed to calculate route. Please try again later."` |

---

## Status Codes

| Code | Meaning |
|------|---------|
| `200` | OK — Request successful |
| `400` | Bad Request — Invalid input or wrong state transition |
| `404` | Not Found — Route or trip does not exist |
| `500` | Internal Server Error — Google API or database failure |

---

## Health Check

### GET `/health`

```json
{
  "status": "healthy",
  "service": "RMC Delivery Route Optimizer",
  "version": "1.0.0"
}
```

---

## Typical Workflow

```
1.  POST /routes/estimate       → Calculate route, receive route_id
2.  POST /trips/start           → Start trip with { route_id }
3.  GET  /trips/{id}/stream     → Connect SSE for real-time updates
4.  POST /trips/{id}/position   → Report GPS every few seconds
    ↕ Background monitor checks traffic every 2 min
    ↕ If delay detected → auto-reroutes → pushes SSE "reroute" event
5.  POST /trips/{id}/complete   → Mark delivered (or auto-complete at <200m)
6.  GET  /trips/{id}/events     → Review full audit trail
```
