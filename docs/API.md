# RMC Delivery Route Optimizer — API Documentation

> **Version:** 1.0.0  
> **Base URL:** `http://localhost:8000/api/v1`  
> **Interactive Docs:** [Swagger UI](http://localhost:8000/docs) · [ReDoc](http://localhost:8000/redoc)

Company-shared saved destinations are available under `/api/v1/job-sites`.
See [job-site API](./JOB_SITES_API.md) for ownership, creation, editing,
deactivation, and browser address-book migration.

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

### Timestamp contract

Client-supplied `departure_datetime`, `scheduled_at`, `batch_time`, and GPS
`captured_at` must include `Z` or an explicit timezone offset. Timezone-less
timestamps are rejected with HTTP `422`; the backend does not infer the user's
timezone from the brand, country, or server location. Optional batch/departure
times can still be omitted to use the existing defaults.

For example, `2026-10-11T10:00:00+05:30` is normalized to
`2026-10-11T04:30:00Z`. SQLite stores UTC wall-time values, and the ORM restores
their UTC timezone when reading them. Typed route, trip, event, vehicle, and
dispatch responses serialize timestamps as timezone-qualified UTC. The UI should
convert UTC to local time only for display.

For a browser-local date/time input, convert the selected local instant before
sending, e.g. `new Date(localDateTimeValue).toISOString()`. This uses the device's
timezone; if scheduling for a different site timezone, convert using that
explicit timezone instead. Never append `Z` to an unconverted local time.

Existing SQLite timestamps are read as UTC without rewriting them. If older
requests stored local wall time after losing their offset, the original instant
cannot be inferred safely. Such records need review using independent evidence;
this change does not guess offsets or bulk-repair historical data. The SQLite
column representation is unchanged, so this type conversion does not require a
SQLite schema migration.

### Load-life and retarder fields

`load_max_life_minutes` is the grade-adjusted **base** life, before retarder.
When `retarder_added` is true, the effective limit is that base plus
`retarder_extension_minutes`, applied once. For example, base 90 and extension 45
give 135 minutes, not 180. `load_expiry_time`, live `load_minutes_remaining`, and
monitoring all use the same reconstructed timer, including high-grade warning
and critical thresholds.

Older retarded trips may store the extended limit in the base-life column.
When the persisted batch/expiry interval confirms this legacy representation,
the backend reads it as base plus extension without rewriting the historical
record. Legacy records with missing expiry evidence or incorrect historical
timestamps still need manual assessment; the backend does not guess a repair.

REST API for calculating optimized delivery routes for New Zealand RMC (Ready-Mix Concrete) trucks. Features include:

- **Route calculation** with real-time traffic via Google Maps Directions API
- **Alternative routes** with comparison summaries
- **Active trip management** — start, pause, resume, complete, cancel
- **Automatic rerouting** — background traffic monitor proactively reroutes active deliveries
- **Real-time SSE stream** — push notifications for reroutes, traffic updates, and status changes
- **Full audit trail** — every position update, traffic check, and reroute logged as an immutable event

### Plant brand analysis

See [Structured catalogue API](CATALOGUE_API.md) for the unpublished `/api/v1`
catalogue replacement, migration, write restrictions, and UI integration changes.

`POST /api/v1/plants/analyse` accepts a business-owned `brand_id` and
`job_site_data.display_name`, the full destination address including its country.
The optional `country_code` field accepts an uppercase ISO 3166-1 alpha-2 code
(`IN` for India, `NZ` for New Zealand) and restricts geocoding of both addresses
to that country. When omitted, geocoding supports international addresses without
a country restriction; existing address-only requests continue to work.
Your UI can send `"country_code": "IN"` when analysing India plants.
Geocoding and analysis caches distinguish country codes.
Successful results contain ETAs, remaining concrete life, risk, probability, and
a recommendation; `best_plant_id` identifies the highest remaining-life result.
Set `include_llm_analysis` to `true` to request a comparison of successful results.

If geocoding or routing fails, the affected result contains an explicit `error`
instead of an empty, success-shaped prediction. Failed plants are ranked last
and excluded from best-plant selection and LLM comparison. Failed analyses and
unsuccessful Directions responses are not cached, so retrying can recover.

**Calibration limitation:** India routes use live Google routing and local weather,
but risk probabilities and delay adjustments still use the existing NZTA/NZS 3109
baselines. They are planning estimates, not India-calibrated guarantees.

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

Every `/api/v1` endpoint requires a Clerk session token:

```http
Authorization: Bearer <Clerk session token>
```

The API validates the token signature against the configured Clerk JWKS,
requires the configured issuer and allowed frontend origin (`azp`), and scopes
route/trip operations to the active organization. Only the verified user ID
configured as `SUPER_ADMIN_USER_ID` is the platform owner and can edit the
business-owned catalogue across companies.
`org:admin` is a company role, never platform Super Admin. It shares company
operational access with `org:plantadmin`, `org:driver`, and `org:member` for now.
Company cross-organization write attempts return `403`.
`GET /auth/me` returns verified identity and capabilities for UI navigation.

Business registration uses `POST /businesses` with an existing Clerk organization
ID and name; it does not provision or verify an organization in Clerk. A brand
requires that business's `organization_id`. Plants inherit exclusive ownership
from their brand. Company brand/plant reads are automatically tenant-scoped.
Structured `/countries`, `/states`, and `/cities` provide cascading location
selection; regions require `city_id` and derive country, state, and timezone.
See [CATALOGUE_API.md](./CATALOGUE_API.md) for onboarding and legacy ownership rules.
`/health` and `/` remain public.

See [Authentication and organization access](./AUTHENTICATION.md) for server
configuration, the free-tier role mapping, plant assignments, and rollout
requirements.

The trip DELETE endpoint archives eligible terminal trips and retains their
rows and event history; it does not physically erase operational data.

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
                         │ complete (manual or auto <= 100m)
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
  "speed_kmh": 72.3,
  "captured_at": "2026-10-11T15:00:00+05:30"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `lat` | float | ✅ | Latitude (−90 to 90) |
| `lng` | float | ✅ | Longitude (−180 to 180) |
| `heading` | float | — | Bearing in degrees (0–360) |
| `speed_kmh` | float | — | Current speed in km/h |
| `captured_at` | ISO 8601 datetime | — | Original GPS capture time, including `Z` or a timezone offset |

**Response `200 OK`** — Updated `TripResponse`

**Side effects:**
- Updates `current_lat`, `current_lng`, `heading`
- Recalculates remaining distance (haversine)
- Logs `position_update` event
- **Auto-completes trip** if within 100m of destination (inclusive)
- For in-progress trips, checks GPS distance from the current route locally.
  Two consecutive accepted fixes **more than 100m** from the same route,
  both captured within the last **30 seconds**, trigger immediate route
  recalculation from exact current coordinates, without a traffic-delay trigger.
  An on-route fix or route change resets confirmation. Paused trips and stale
  fixes do not trigger off-route recalculation.
- Off-route attempts have a separate **30-second cooldown**, including failures,
  persisted in `off_route_check` events. Traffic's 180-second cooldown, movement
  skip and 1km guard do not block confirmed off-route recalculation. The existing
  100m arrival/auto-completion rule still runs first.
- Successful recalculation persists the new polyline/ETA and emits the existing
  SSE `reroute` payload (including steps) for map and voice consumers. Failures
  preserve the previous route and appear in `traffic_check` audits/logs.
  Missing/invalid route geometry is reported as `off_route_unavailable`.

Local checks do not call Google. Only confirmed off-route attempts call Directions,
using the existing exact-coordinate cache rather than the coarse traffic cache.
Detection uses the encoded route geometry, not road matching; parallel roads
within 100m and simplified geometry/GPS inaccuracies can limit detection.
The two-fix evidence survives restart via position audits; per-trip check
serialization is process-local, so use one backend worker/instance.

`captured_at` is normalized to UTC and stored in the `position_update` audit
payload separately from `received_at` (server receipt time). `created_at` remains
the audit creation time. Trip responses expose `current_position_at` in UTC;
position SSE events include both `captured_at` and `received_at`. The UI should
convert these UTC timestamps to local time for display.

Send the original browser GPS timestamp, e.g.
`new Date(position.timestamp).toISOString()`, not the time an offline queue is
uploaded. Reports older than or equal to the latest accepted capture time are
rejected before updating coordinates, heading, distance, or auto-completion.
Rejected reports are recorded as `position_rejected` audit events. This ordering
survives server restarts. Reports without `captured_at` use receipt time for
backward compatibility; their original capture time cannot be recovered.
Historical position events without capture times use their audit creation time.

**Errors:** `400` Trip not in progress/paused state, stale/duplicate capture time,
or capture time in the future; `422` Invalid or timezone-less `captured_at`.

These timestamps preserve report ordering, not proof of a driver's location:
client-supplied coordinates and timestamps are not independently authenticated.
A website cannot reliably track after the browser is closed or the device
suspends it. Drivers must keep tracking active; reliable background tracking
requires a native mobile app with the necessary OS permissions.

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

Completion is allowed beyond **100 metres** from the destination, but
`completion_review_required` is `true` and `completion_review_reason` explains why.
`completion_distance_meters` is the straight-line distance calculated from the
latest stored truck coordinates, not the remaining route distance. At exactly
100 metres, completion is not flagged. Missing truck coordinates also require
review. The distance and review flag are persisted in the `trip_completed` audit
event and included in trip responses and the completion SSE status event.
Historical trips without this audit data return `null` for these fields.
The review flag does not change the reported delivery `outcome`.

Only in-progress or paused trips can be completed; pending, completed, and
cancelled trips are rejected. The backend recomputes actual load status from the
timer at completion rather than trusting the last traffic-projected status.
When `success` is omitted, actual expiry yields `outcome: "failed"`; otherwise
the existing default is `"succeeded"`. GPS automatic completion uses the same
outcome calculation. This default is not independent proof of a successful pour;
separating arrival from pour completion remains a planned workflow change.

An operator can report `success: true` for an actually expired load only with
non-blank `notes` explaining the override. Without a reason, the API returns
`400` without completing the trip. With a reason, the reported outcome is saved,
actual load status remains `expired`, and completion is flagged for review even
when the truck is within 100 metres. Location and expiry review reasons are
combined. The audit records `expiry_override`, `reported_success`,
`actual_load_status`, the load-timer snapshot, and the operator notes.

Trip start/begin rejects future batch times and already-expired loads with
`400`, before changing trip state. A valid older batch starts with its actual
load status, rather than always starting as fresh.

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
| Reroute threshold (ratio) | **>15%** | New duration exceeds expected remaining time from previous ETA; original duration is fallback when ETA is absent |
| Reroute threshold (absolute) | **>5 min** | Reroute if absolute traffic delay exceeds 5 minutes |
| Traffic reroute cooldown | **180s** | Traffic-triggered reroutes wait 3 minutes after the last applied reroute |
| Off-route threshold | **>100m, two fixes** | Local geometry checks on fresh GPS updates |
| Off-route freshness / attempt cooldown | **30s / 30s** | Both fixes must be recent; failed attempts also consume cooldown |
| Min distance for check | **1 km** | Skip check if truck is < 1 km from destination |
| Auto-complete distance | **100m** | Auto-complete trip if within 100m of destination |
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
5.  POST /trips/{id}/complete   → Mark delivered (or auto-complete at <=100m)
6.  GET  /trips/{id}/events     → Review full audit trail
```
