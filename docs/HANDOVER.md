# RMC Delivery Application - Engineering Handover

**Last reviewed:** 2026-10-11  
**Scope:** Current backend worktree, including business ownership and geography changes.  
**Audience:** Incoming developers, frontend engineers, operators, and product owners.  
**Status:** Implemented backend with outstanding integration, regression, and production-readiness work.

For ordered installation and onboarding, start with the
[setup guide](./SETUP_GUIDE.md). This handover is the technical reference.

## Contents

1. [What the application is](#1-what-the-application-is)
2. [Implemented functionality](#2-implemented-functionality)
3. [Business model and permissions](#3-business-model-and-permissions)
4. [Architecture and code ownership](#4-architecture-and-code-ownership)
5. [Main workflows](#5-main-workflows)
6. [API inventory and frontend contract](#6-api-inventory-and-frontend-contract)
7. [Database relationships](#7-database-relationships)
8. [Database data dictionary](#8-database-data-dictionary)
9. [Configuration and integrations](#9-configuration-and-integrations)
10. [Startup, migration, and deployment](#10-startup-migration-and-deployment)
11. [Validation status and known gaps](#11-validation-status-and-known-gaps)
12. [Handover and maintenance checklist](#12-handover-and-maintenance-checklist)

## 1. What the application is

The application supports **ready-mix concrete (RMC) delivery planning and trip
tracking**. Concrete has a limited usable life after batching. Dispatchers need
to choose a suitable plant, estimate travel time, track deliveries, and identify
loads that may arrive too late.

The backend combines:

- Plant and business catalogue data.
- Google Maps routing and live traffic estimates.
- Destination weather.
- Concrete-life and congestion calculations.
- Optional LLM-generated explanations.
- Scheduled dispatch, GPS updates, traffic checks, and trip event history.

It is becoming a multi-business application: Business A and Business B have
separate users, brands, plants, routes, and trips. Each business can operate in
multiple countries, states, and cities.

**Important:** This is decision-support software, not certification that a load
is safe or a pour succeeded. International geography is supported, but existing
prediction assumptions are substantially NZ/Auckland-derived. Production
readiness and regional calibration must not be inferred from the existence of
these features.

### Application boundaries

| Component | Responsibility |
|---|---|
| This repository | FastAPI backend, persistence, predictions, trip lifecycle, API authorization |
| Separate `rmc-delivery-web` project | Next.js web UI, Clerk login, dashboards, map and GPS interaction |
| Clerk | Users, authentication sessions, organizations, organization memberships and roles |
| In-repository `client/` | Legacy Gradio client; not the active production UI |

No local password system, user-management table, or Clerk organization
provisioning API is implemented here.

## 2. Implemented functionality

| Area | What the backend provides | Important limitation |
|---|---|---|
| Authentication | Verifies signed Clerk session tokens, issuer, expiry, and allowed frontend origin | Live Clerk integration still needs deployment verification |
| Business catalogue | Register a local business using an existing Clerk organization ID; list and rename it | Does not create or verify that organization in Clerk |
| Brands | Business-owned brands, normalized names, versioned edits | Ownership cannot transfer between businesses |
| Geography | Country, state/province, city, and city-linked operating regions | Starts without a worldwide location dataset |
| Plants | Business-owned plants with coordinates, address, supported mixes, and active status | No capacity, shift/opening-hours, or stock model |
| Job sites | Company-owned saved destinations with shared lists, versioned edits and deactivation | Browser entries require explicit reviewed import; no trip site-ID FK |
| Plant selection | Company-scoped nearest plants and brand analysis | Region/country selection matters for international operations |
| Routing | Route estimates, alternatives, route history, rerouting | Generic driving directions, not certified truck-restricted routing |
| Predictions | Traffic-adjusted ETA, remaining concrete life, risk, and optional LLM narrative | Weather/calibration/decision-quality gaps remain |
| Scheduled dispatch | Creates a pending trip from a selected plant and destination | Driver assignment and fleet scheduling are not complete subsystems |
| Trip lifecycle | Start/begin, pause/resume, completion, cancellation, archival | Arrival and confirmed pour completion are not separate workflows yet |
| GPS tracking | Position reports with capture/receipt times and ordering checks | Browser background tracking and GPS trust/freshness remain limitations |
| Completion review | 100-metre location check, expiry checks, durable review reasons | No review-resolution dashboard/API |
| Live events | Authenticated SSE stream and stored trip events | SSE subscribers and alerts are process-local |
| Traffic monitoring | Periodic traffic checks plus GPS-triggered off-route recalculation | Two fresh fixes >100m from route; process-local serialization requires one worker |
| Auditing | Catalogue mutations and trip events include actor identity where available | Not a database-enforced immutable audit store |
| Persistence | SQLite catalogue, routes, trips, events, migration ledger, idempotency records | Backup/restore and reviewed schema rollout are required |

## 3. Business model and permissions

### Ownership rules

- A business is represented locally by `businesses.id`, equal to its Clerk `org_...` ID.
- A brand belongs to one business.
- A plant belongs to the same business as its brand.
- One business or brand can have plants in many locations.
- Public geography is private to each business. The global country table is
  only an internal ISO-code anchor; business country entries are separate.
- Country/state creation selects the target business; cities inherit state
  ownership and regions inherit city ownership. Plant, brand and region owners
  must match.
- New brands require a registered business; new plants inherit ownership from
  the selected brand. The client does not independently set plant ownership.
- Owned brands/plants cannot be shared or transferred to another business.
- Existing seed records can remain unowned until explicitly reviewed/adopted.

### Role matrix

| Action | Platform owner | Company roles |
|---|---|---|
| Register/rename businesses | Yes | No |
| Create/edit brands and plants | Yes, across businesses | No |
| Create geography and edit regions | Yes | No |
| Read geographic dropdowns | Yes | Yes |
| Read company brands/plants | All businesses | Active business only |
| Route, predict, dispatch, operate trips | Requires active supported organization context | Active business only |
| Read another company's trips/events | No general operational bypass | No |
| Adopt legacy plants | Yes, subject to ownership checks | No |

Platform admins are **only** verified Clerk users whose `sub` is an exact entry
in the server's semicolon-separated `SUPER_ADMIN_USER_ID`. A company's `org:admin` role does not
grant platform access.

Supported company roles are `org:admin`, `org:plantadmin`, `org:driver`, and
`org:member`. They currently share the same operational permissions. A driver
is not yet restricted to only personally assigned trips.

The owner can administer catalogues without joining every customer company.
Operational routes still require an active supported organization membership:
missing organization context must not become an unrestricted data query.

Clerk v1 `org_id`/`org_role` and v2 `o.id`/`o.rol` claims are recognized.
Browser-supplied membership JSON or role flags are not authorization evidence.
See [authentication contract](./AUTHENTICATION.md).

## 4. Architecture and code ownership

Normal request flow:

```text
Next.js UI + Clerk token
        |
        v
FastAPI router -> verified Principal -> scoped service
        |                                  |
        |                                  +-> Google / weather / optional LLM
        v
SQLAlchemy session -> SQLite -> records and audit events

FastAPI lifespan -> in-process traffic monitor -> TripService -> alerts/SSE
```

| Source area | Responsibility |
|---|---|
| [Application entry](../app/main.py) | FastAPI initialization, lifespan, migrations, CORS, health and logging |
| [Settings](../app/config.py) | Environment settings and legacy credential-file fallback |
| [Authentication](../app/auth.py) | Clerk JWT verification and permission dependencies |
| [Dependencies](../app/dependencies.py) | Request-scoped services and shared integration/alert objects |
| [API routers](../app/api/v1/endpoints/) | HTTP validation, responses, authorization boundaries |
| [Schemas](../app/schemas/) | Typed request and response contracts |
| [Database models](../app/db/models.py) | Business/catalogue/route/trip tables |
| [Geography models](../app/db/geography.py) | Country/state/city tables |
| [Database setup](../app/db/database.py) | Engine, sessions, SQLite foreign-key enforcement |
| [Catalogue service](../app/services/catalogue.py) | Ownership/reference checks, CRUD, idempotency, versioning, audits |
| [Plant locator](../app/services/plant_locator.py) | Database-backed company-scoped plant selection |
| [Route service](../app/services/route.py) | Route calculations, persistence, history, cache |
| [Prediction service](../app/services/prediction.py) | Routing/weather/predictor integration |
| [Trip service](../app/services/trip.py) | Lifecycle, GPS, completion, dispatch, rerouting, event persistence |
| [Traffic monitor](../app/services/traffic_monitor.py) | Periodic in-process checks of in-progress trips |
| [RMC modules](../app/rmc/) | Load-life, feasibility, prediction, dispatch and alert helpers |
| [Time helpers](../app/utils/time.py) / [UTC storage type](../app/db/types.py) | Timezone-qualified requests and UTC persistence/serialization |
| [Tests](../tests/) | Isolated database, service, auth and API regressions |

Caches, SSE subscribers, the monitor, and several integration objects are
process-local. The operational deployment should currently use one backend
process/instance, not assume that multiple workers share their state.

## 5. Main workflows

### 5.1 Onboard a business

1. Create the organization and users/memberships in Clerk.
2. Platform owner registers the existing organization ID and name locally.
3. Create/select country, state, city, and operating region.
4. Create a brand owned by that business.
5. Create plants under the brand and appropriate regions.
6. Company users select their active Clerk organization in the UI.
7. Their brand, plant, route, and trip views use that organization boundary.

The country/state/city catalogue is curated through owner-only APIs. There is
no automatic worldwide import. Regions derive country, state name, and
timezone from the selected city; duplicate conflicting location inputs are
rejected.

### 5.2 Plan and dispatch

1. Select the active company, eligible brand, destination, and concrete mix.
2. For a multi-country brand, select region or country to avoid ambiguity.
3. Analyse eligible plants, rank results, and show explicit per-plant failures.
4. Dispatch from the chosen active plant supporting the requested mix.
5. Store the pending trip, planned departure, route, and prediction/catalogue snapshot.
6. Begin the trip using a valid batch time; the load timer starts from batching,
   not from the time the API request arrives.

### 5.3 Track and complete

- Position reports update the truck location and record capture/receipt evidence.
- The monitor checks in-progress trips approximately every 120 seconds, with
  a two-second inter-trip delay when multiple trips are checked.
- Operators can also request traffic checks, pause, or resume trips.
- Completion uses actual timer state and location review rules.
- Pending trips cannot be completed directly.
- Terminal completed/cancelled trips can be archived; their rows/events remain.
- Company access is checked before operational reads/writes and SSE subscription.

Trip state vocabulary:

```text
pending -> begin -> in_progress
in_progress -> pause -> paused -> resume -> in_progress
in_progress / paused -> completed
cancellation -> cancelled (subject to lifecycle guards)
completed / cancelled -> archived (timestamp, not a new status value)
```

The UI must not equate a GPS arrival signal with independently confirmed pour
success. Consult lifecycle contracts for edge cases rather than reproducing
timer or outcome rules in frontend code.

## 6. API inventory and frontend contract

All paths below are relative to the configured prefix, normally `/api/v1`.
Interactive `/docs` and `/openapi.json` describe the actual running contracts.

| Area | Endpoints |
|---|---|
| Identity | `GET /auth/me` |
| Businesses | `GET, POST /businesses`; `GET, PATCH /businesses/{id}` |
| Brands | `GET, POST /brands`; `GET, PATCH /brands/{id}` |
| Geography | `GET, POST /countries`, `/states`, `/cities`; GET/DELETE detail for each (delete only unused) |
| Regions | `GET, POST /regions`; `GET, PATCH, DELETE /regions/{id}` (delete only unused) |
| Plants | `GET, POST /plants`; `GET, PATCH /plants/{id}`; `POST /plants/analyse` |
| Job sites | `GET, POST /job-sites`; `GET, PATCH /job-sites/{id}` |
| Legacy adoption | `GET, POST /organizations/{id}/plants`; `DELETE /organizations/{id}/plants/{plant_id}` |
| Routes | `POST /routes/estimate`, `/routes/reroute`; `GET /routes`, `/routes/{id}`, `/routes/cache/stats` |
| Predictions | `POST /predict/delivery`, `/predict/best-plant`, `/predict/nearest-plant` |
| Trip creation | `POST /trips/start`, `/trips/dispatch`, `/trips/{id}/begin` |
| Trip reads | `GET /trips/active`, `/trips/all`, `/trips/{id}`, `/trips/{id}/events` |
| Trip operations | `POST /trips/{id}/position`, `/check`, `/pause`, `/resume`, `/complete`, `/cancel` |
| Trip archival | `DELETE /trips/{id}` |
| Live events | `GET /trips/{id}/stream` |
| Process health | `GET /health` outside the API prefix |

### Cross-cutting client rules

- Send the Clerk token in `Authorization: Bearer <token>`, not query parameters.
- Use `/auth/me` capabilities for navigation; backend guards remain authoritative.
- Catalogue lists use `items`, `total`, `limit`, `offset`; not all operational
  lists use that envelope.
- Business, brand, region, and plant POSTs require `Idempotency-Key`.
  Geography POSTs currently do not; duplicates return `409`.
- Versioned PATCH requires the last-read `version`. Handle `409` by reloading.
- Plant deletion means deactivation through PATCH, not removal of history.
- Send timestamps with `Z` or an explicit offset; display UTC responses locally.
- Clear selected plants, trip state, cached company data, and SSE streams on
  active-organization changes.
- Use fetch-based streaming for SSE; native browser `EventSource` cannot attach
  the bearer header.
- Owned plants cannot be unassigned through the legacy endpoint. Its DELETE is
  available only to clean up unowned legacy assignments.

Detailed payloads live in [API reference](./API.md),
[catalogue contract](./CATALOGUE_API.md), and [geography contract](./GEOGRAPHY_API.md).

## 7. Database relationships

The ORM defines **18 tables / 195 columns**. This documents the current code schema,
not a claim that the existing operational database has already been upgraded.

```text
businesses
  -> brands.organization_id
  -> plants.organization_id
  -> business_countries.organization_id
  -> states.organization_id
  -> cities.organization_id
  -> regions.organization_id

countries.code
  -> business_countries.code
  -> states.country_code
       -> cities.state_id
            -> regions.city_id
                 -> plants.region_id

brands.id -> plants.brand_id
routes.id -> trips.route_id -> trip_events.trip_id
plants.id -> organization_plants.plant_id (legacy assignment records)
```

Additional logical references are deliberately not all database foreign keys:

- Routes/trips store Clerk organization and user IDs as strings.
- Trip `plant_id` is a historical string, not an enforced plant FK.
- Vehicle IDs used in operations are strings, not FKs to `vehicles.id`.
- `traffic_snapshots.route_id` is an integer logical reference, not a declared FK.
- Audit `entity_type`/`entity_id` identify different resource kinds.

Business/brand/plant/region and geography parent ownership consistency is
enforced by service checks and scoped reads, not composite foreign keys tying
their owners together.
Direct SQL writers must preserve these invariants.

## 8. Database data dictionary

### Reading the dictionary

- `?` means nullable in the ORM; absence of `?` means NOT NULL.
- `PK` means primary key; `->` indicates a declared foreign key.
- `S(n)` means `VARCHAR(n)`; `I` integer; `F` float; `B` boolean.
- `UTC` means the application's UTC-aware datetime type. SQLite stores a
  timezone-less representation and the application restores UTC awareness.
- Nullability describes storage, not what a new API request is allowed to omit.
- Integer single-column PKs use database-generated identifiers. New opaque
  catalogue IDs are generated by services; existing seed plant IDs are retained.
- Catalogue version starts at `1`. Creation timestamps default to database time;
  update timestamps use ORM update behavior, not a database-wide trigger.

### 8.1 `businesses`

Local profile linked to an existing Clerk organization.

| Column | Type / rule | Meaning |
|---|---|---|
| `id` | S(100), PK | Existing Clerk organization ID |
| `name` | S(200) | Business display name |
| `version` | I, default 1 | Optimistic concurrency version |
| `created_at` | UTC, default now | Registration time |
| `updated_at` | UTC, default now | Last ORM update |

### 8.2 `brands`

| Column | Type / rule | Meaning |
|---|---|---|
| `id` | S(100), PK | Immutable brand identifier |
| `organization_id` | S(100)? -> businesses.id | Exclusive owner; null for legacy records |
| `name` | S(200) | Display name |
| `name_key` | S(400), unique | Owner-namespaced normalized name used for uniqueness |
| `version` | I, default 1 | Edit version |
| `created_at` | UTC | Creation time |
| `updated_at` | UTC | Last ORM update |

Name/key must be nonblank. Same normalized name is allowed in different
businesses. Unowned legacy keys keep their original normalization.

### 8.3 `countries`

| Column | Type / rule | Meaning |
|---|---|---|
| `code` | S(2), PK | Uppercase ISO country code |
| `name` | S(200) | Country display name |
| `created_at` | UTC | Creation time |
| `updated_at` | UTC | Last ORM update |

Internal ISO-code anchor, not a shared business dropdown. Database checks code
format and nonblank names; assigned ISO codes are validated at the API layer.

### 8.3a `business_countries`

| Column | Type / rule | Meaning |
|---|---|---|
| `organization_id` | S(100), composite PK -> businesses.id | Business owner |
| `code` | S(2), composite PK -> countries.code | ISO country code |
| `name` | S(200) | Private country display name |
| `created_at` | UTC | Creation time |

Public country reads use this table and business-scoped deletion retains the
internal country anchor.

### 8.4 `states`

| Column | Type / rule | Meaning |
|---|---|---|
| `id` | S(36), PK, generated UUID | State/province identifier |
| `organization_id` | S(100)? -> businesses.id | Private business owner; null for unadopted legacy rows |
| `country_code` | S(2) -> countries.code | Parent country |
| `name` | S(200) | State/province name |
| `created_at` | UTC | Creation time |
| `updated_at` | UTC | Last ORM update |

Case-insensitive unique index on business, country and lowercased state name.

### 8.5 `cities`

| Column | Type / rule | Meaning |
|---|---|---|
| `id` | S(36), PK, generated UUID | City/locality identifier |
| `organization_id` | S(100)? -> businesses.id | Business owner inherited from state |
| `state_id` | S(36) -> states.id | Parent state |
| `name` | S(200) | City/locality name |
| `timezone` | S(100) | IANA timezone validated by API |
| `created_at` | UTC | Creation time |
| `updated_at` | UTC | Last ORM update |

Case-insensitive unique index on state plus lowercased city name. Geographic parents may be deleted only when unused, by a platform admin.

### 8.6 `regions`

Operating areas below cities; multiple regions can exist in one city.

| Column | Type / rule | Meaning |
|---|---|---|
| `id` | S(100), PK | Region identifier |
| `organization_id` | S(100)? -> businesses.id | Business owner inherited from city |
| `name` | S(200) | Operating-area name |
| `city_id` | S(100)? -> cities.id | Structured city link; null for legacy regions |
| `country_code` | S(2) | Country derived from city/state on writes |
| `administrative_area` | S(200) | State/province name derived on writes |
| `timezone` | S(100) | City timezone derived on writes |
| `calibration_status` | S(30), default uncalibrated | `uncalibrated` or `nz_baseline` |
| `version` | I, default 1 | Edit version |
| `created_at` | UTC | Creation time |
| `updated_at` | UTC | Last ORM update |

Country format and calibration vocabulary have DB checks. Region metadata
edits reset calibration to uncalibrated. Country/state/timezone values are
stored copies maintained by service writes, not database computed columns.
`state_id` is a derived API/ORM property, not a regions table column.

### 8.7 `plants`

| Column | Type / rule | Meaning |
|---|---|---|
| `id` | S(100), PK | Immutable dispatch plant ID |
| `organization_id` | S(100)? -> businesses.id | Owner inherited from brand; null for legacy plants |
| `name` | S(200) | Plant display name |
| `brand_id` | S(100) -> brands.id | Owning brand |
| `region_id` | S(100) -> regions.id | Operating region |
| `address` | S(500) | Plant street/location address |
| `lat` | F, range -90..90 | Latitude |
| `lng` | F, range -180..180 | Longitude |
| `active` | B, default true | Availability for new dispatch |
| `supported_mix_codes` | JSON, default GP/HE/RE | Eligible mix families |
| `version` | I, default 1 | Edit version |
| `created_at` | UTC | Creation time |
| `updated_at` | UTC | Last ORM update |

API coordinates use nested `location.latitude/longitude`; storage uses `lat/lng`.
Country/state/city/timezone response fields are derived from region relations,
not additional plants table columns.

### 8.8 `organization_plants`

Legacy many-company assignment records retained for review and adoption.
**This is no longer the runtime source of dispatch ownership.**

| Column | Type / rule | Meaning |
|---|---|---|
| `id` | I, PK | Legacy assignment row ID |
| `organization_id` | S(100) | Clerk organization string, no business FK |
| `plant_id` | S(100) -> plants.id | Assigned plant |
| `created_by_user_id` | S(100)? | Actor that made the assignment |
| `created_at` | UTC | Assignment time |

Unique pair `(organization_id, plant_id)`. Legacy records do not automatically
grant access; owned plant and brand fields control runtime visibility.

### 8.9 `routes`

Persisted route request, selected route, and alternatives.

| Column | Type / rule | Meaning |
|---|---|---|
| `id` | I, PK | Route identifier |
| `organization_id` | S(100)? | Tenant boundary; null legacy rows hidden from company APIs |
| `created_by_user_id` | S(100)? | Verified creator |
| `start_address` | S(500) | Requested origin |
| `start_lat` | F | Origin latitude |
| `start_lng` | F | Origin longitude |
| `resolved_start_address` | S(500)? | Provider-resolved origin |
| `end_address` | S(500) | Requested destination |
| `end_lat` | F | Destination latitude |
| `end_lng` | F | Destination longitude |
| `resolved_end_address` | S(500)? | Provider-resolved destination |
| `vehicle_type` | S(50) | Requested vehicle category |
| `vehicle_id` | S(100)? | Application vehicle identifier |
| `load_weight` | F? | Request load weight |
| `load_volume` | F? | Request load volume |
| `departure_datetime` | UTC? | Planned departure |
| `priority` | S(20)?, default normal | Operational priority |
| `max_delivery_minutes` | I? | Requested maximum travel time |
| `distance_meters` | F? | Selected route distance |
| `duration_seconds` | F? | Selected route duration |
| `traffic_delay_seconds` | F? | Traffic delay |
| `exceeds_delivery_limit` | I? | Stored delivery-limit flag |
| `delivery_limit_exceeded_by` | I? | Excess over requested limit |
| `polyline` | TEXT? | Encoded map route |
| `route_steps` | JSON? | Navigation steps |
| `avoid_options` | JSON? | Requested avoidance options |
| `selected_route_index` | I?, default 0 | Chosen alternative index |
| `total_alternatives` | I?, default 1 | Number of alternatives |
| `alternatives_summary` | JSON? | Alternative metadata |
| `created_at` | UTC?, default now | Record creation |
| `updated_at` | UTC?, default now | Last ORM update |

### 8.10 `trips`

Trip state plus concrete-load lifecycle and route progress.

| Column | Type / rule | Meaning |
|---|---|---|
| `id` | I, PK | Trip identifier |
| `organization_id` | S(100)? | Tenant boundary |
| `created_by_user_id` | S(100)? | Verified creator |
| `route_id` | I -> routes.id | Initial associated route |
| `status` | S(20), default pending | pending/in_progress/paused/completed/cancelled |
| `current_lat` | F? | Most recent truck latitude |
| `current_lng` | F? | Most recent truck longitude |
| `heading` | F? | Reported heading |
| `start_address` | S(500) | Trip origin snapshot |
| `end_address` | S(500) | Destination snapshot |
| `start_lat` | F | Origin latitude |
| `start_lng` | F | Origin longitude |
| `end_lat` | F | Destination latitude |
| `end_lng` | F | Destination longitude |
| `vehicle_type` | S(50)?, default rmc_truck | Vehicle category |
| `vehicle_id` | S(100)? | Vehicle identifier |
| `priority` | S(20)?, default normal | Trip priority |
| `avoid_options` | JSON? | Route avoidance options |
| `current_polyline` | TEXT? | Current route, possibly rerouted |
| `original_distance_meters` | F? | Initial distance |
| `original_duration_seconds` | F? | Initial duration |
| `remaining_distance_meters` | F? | Latest remaining distance |
| `remaining_duration_seconds` | F? | Latest remaining duration |
| `current_traffic_delay` | F? | Latest delay in seconds |
| `reroute_count` | I?, default 0 | Number of reroutes |
| `last_reroute_at` | UTC? | Latest reroute time |
| `last_traffic_check_at` | UTC? | Latest traffic check time |
| `estimated_arrival` | UTC? | Latest estimated arrival |
| `batch_time` | UTC? | Actual batching time |
| `load_expiry_time` | UTC? | Concrete expiry |
| `load_status` | S(20)?, default fresh | fresh/warning/critical/expired |
| `mix_code` | S(50)? | Detailed concrete mix specification |
| `concrete_grade` | S(20)? | Concrete grade |
| `volume_m3` | F? | Concrete volume |
| `retarder_added` | B?, default false | Retarder flag |
| `retarder_extension_minutes` | I?, default 0 | Extension applied once |
| `load_max_life_minutes` | I?, default 90 | Grade-adjusted base life before extension |
| `plant_id` | S(50)? | Historical dispatch plant identifier; not FK |
| `pour_duration_minutes` | I? | Expected pour duration |
| `scheduled_at` | UTC? | Planned departure |
| `concrete_mix` | S(10)? | GP/HE/RE family |
| `outcome` | S(20)? | succeeded/failed when completed |
| `prediction_json` | TEXT? | Serialized prediction/catalogue snapshot |
| `started_at` | UTC? | Trip start |
| `completed_at` | UTC? | Completion time |
| `archived_at` | UTC? | Soft archival time |
| `archived_by_user_id` | S(100)? | Archival actor |
| `created_at` | UTC?, default now | Record creation |
| `updated_at` | UTC?, default now | Last ORM update |

Capture/receipt timestamps and completion-review details are stored in trip
event payloads, not dedicated columns in this table. Several lifecycle
vocabularies are service conventions rather than database enum constraints.

### 8.11 `trip_events`

| Column | Type / rule | Meaning |
|---|---|---|
| `id` | I, PK | Event ID |
| `trip_id` | I -> trips.id | Owning trip |
| `actor_user_id` | S(100)? | Verified actor; null for internal/system events |
| `event_type` | S(30) | Lifecycle, position, traffic, reroute, review or archival event |
| `data` | JSON? | Event-specific evidence/details |
| `lat` | F? | Event position |
| `lng` | F? | Event position |
| `created_at` | UTC?, default now | Event receipt/record time |

Event payloads vary by event type. There is no separate feedback or review
resolution table. Archived trips retain their event rows.

### 8.12 `catalogue_events`

| Column | Type / rule | Meaning |
|---|---|---|
| `id` | I, PK | Audit event ID |
| `entity_type` | S(30) | Business/brand/region/plant/geography resource kind |
| `entity_id` | S(100) | Resource identifier |
| `action` | S(30) | Creation, update, ownership adoption or legacy cleanup |
| `data` | JSON, Python default empty dict | Before/after or operation details |
| `actor_user_id` | S(100)? | Verified mutation actor |
| `organization_id` | S(100)? | Business attribution where applicable |
| `created_at` | UTC, default now | Audit time |

Normal service writes add these in the same transaction as catalogue changes.
Private geography writes carry business attribution. Historical events may
remain unattributed. Explicit operator commands retain a source label and null
actor rather than fabricate an authenticated user.

### 8.13 `catalogue_idempotency`

| Column | Type / rule | Meaning |
|---|---|---|
| `key` | S(200), PK | Persisted create retry key |
| `entity_type` | S(30) | Resource kind |
| `request_hash` | S(128) | Canonical request digest |
| `response_data` | JSON | Original successful create response |
| `created_at` | UTC, default now | Key creation |

API keys are restricted to 100 characters despite wider storage. Keys are
global to this table and do not currently expire. Different request bodies
using the same key return `409`. Replay returns the original create response,
not necessarily the current edited record.

### 8.14 `catalogue_migrations`

| Column | Type / rule | Meaning |
|---|---|---|
| `version` | I, PK | Applied seed migration version |
| `applied_at` | UTC, default now | Migration time |

Version 1 records the one-time catalogue import. This is not a complete ledger
of every operational/auth/geography schema migration.

### 8.15 `vehicles`

Existing vehicle reference model; not a full company-scoped fleet subsystem.

| Column | Type / rule | Meaning |
|---|---|---|
| `id` | I, PK | Vehicle row ID |
| `vehicle_code` | S(100)?, unique | Vehicle code |
| `vehicle_type` | S(50) | Vehicle category |
| `max_height_cm` | I? | Height constraint |
| `max_width_cm` | I? | Width constraint |
| `max_weight_kg` | F? | Weight constraint |
| `max_volume_m3` | F? | Volume capacity |
| `registration_number` | S(50)? | Registration |
| `created_at` | UTC?, default now | Creation time |
| `updated_at` | UTC?, default now | Last ORM update |

No vehicle CRUD router or organization ownership column is currently provided.
Stored constraints do not imply truck-safe route enforcement.

### 8.16 `traffic_snapshots`

Existing traffic snapshot model; not a trained prediction-history subsystem.

| Column | Type / rule | Meaning |
|---|---|---|
| `id` | I, PK | Snapshot ID |
| `route_id` | I, logical reference only | Associated route |
| `timestamp` | UTC?, default now | Sample time |
| `current_duration_seconds` | F | Observed route duration |
| `traffic_condition` | S(50)?, default normal | Condition label |
| `congestion_level` | I? | Congestion level |

### Index and schema notes

- Organization IDs are indexed on primary tenant-scoped tables.
- Plant brand/region links and geography parent links are indexed.
- Trip status, trip route ID, event trip ID/type, and traffic route ID have indexes.
- Geography parent/name uniqueness uses expression indexes.
- SQLite foreign keys are enabled for new application connections.
- Nullable owner/city fields preserve legacy rows; they do not make them eligible
  for normal new company dispatch.
- Additive migrations do not rebuild every historical constraint or widen every
  old table definition. PostgreSQL/older database upgrades require staging checks.

### 8.17 `job_sites`

Company-shared delivery address book, independent of batching plants.
Organization IDs are verified Clerk strings, not foreign keys to local business
registration. All supported operational roles can manage their own company sites.

| Column | Type / rule | Meaning |
|---|---|---|
| `id` | S(100), PK | Generated immutable site ID |
| `organization_id` | S(100), indexed | Active Clerk organization |
| `name` | S(200) | Project/site display name |
| `address` | S(500) | Delivery destination address |
| `lat` | F? | Optional latitude |
| `lng` | F? | Optional longitude |
| `country_code` | S(2)? | Optional ISO country code |
| `notes` | TEXT? | Access or delivery notes |
| `active` | B, default true | Address-book availability |
| `created_by_user_id` | S(100) | Verified creator |
| `updated_by_user_id` | S(100) | Verified last editor |
| `version` | I, default 1 | Optimistic concurrency version |
| `created_at` | UTC | Creation time |
| `updated_at` | UTC | Last ORM update |

Database checks nonblank name/address and paired, bounded coordinates.
Creates are idempotent; PATCH supports soft deactivation and audited edits.
Sites do not expose cross-company owner override or hard deletion.
Existing browser-only entries are not auto-imported.
See [job-site contract](./JOB_SITES_API.md).

## 9. Configuration and integrations

Never include real credentials, JWTs, database dumps, or operational customer
data in handover documents or source control.

| Setting | Purpose |
|---|---|
| `ENV`, `DEBUG` | Runtime mode and debugging |
| `DATABASE_URL` | SQLAlchemy connection; code default is local SQLite |
| `DB_ECHO` | SQL diagnostics |
| `GOOGLE_MAPS_API_KEY` | Routing/geocoding integration |
| `CLERK_JWKS_URL` | Public JWT signing-key endpoint |
| `CLERK_ISSUER` | Expected token issuer |
| `CLERK_AUTHORIZED_PARTIES` | Allowed frontend origins |
| `SUPER_ADMIN_USER_ID` | Semicolon-separated platform-admin user IDs |
| `LLM_PROVIDER`, `LLM_MODEL` | Narrative provider/model selection |
| `OPENROUTER_API_KEY`, `GEMINI_API_KEY` | Optional provider credentials |
| `LOG_LEVEL` | Logging verbosity |
| `API_V1_PREFIX`, `API_TITLE`, `API_VERSION` | API configuration |
| `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW` | Declared settings; do not assume rate limiting is wired |

Settings load from the environment and optional local `.env`, with legacy
`config/credentials.json` filling some missing values. Do not distribute those
files in handover packs. Public JWKS/issuer verification does not require a
Clerk backend secret key.

External integrations:

- Google Maps: routing, traffic and geocoding.
- Open-Meteo: weather information used in prediction.
- Clerk: JWT verification and externally managed users/organizations.
- Ollama, OpenRouter, or Gemini: optional risk narrative providers.

Dependency versions in [requirements](../requirements.txt) are mostly unpinned.
A reproducible clean build and dependency policy remain follow-up work.
LLM providers should be approved for the data sent to them; no additional
provider calls were made to produce this handover.

## 10. Startup, migration, and deployment

### Startup sequence

Current [lifespan](../app/main.py):

1. Create/check geography tables.
2. Run ORM `create_all` for missing tables.
3. Add nullable business ownership and region city-link columns.
4. Run one-time versioned catalogue seed migration.
5. Add authentication, actor, and archival columns/indexes.
6. Initialize shared integration/load/alert services and start traffic monitor.

Database initialization failure prevents startup. Monitor startup failure is
logged but does not currently make `/health` report unready.

### Seed and legacy records

[Plant seed](../config/plants.json) is imported once into the catalogue.
Changing it after migration does not change the running catalogue. The seed
contains NZ/India records with retained IDs and explicit region mapping; it is
not a country/state/city dataset.

Unadopted legacy records may retain null ownership and region city links. The
operator explicitly adopted the local 15 brands, 23 plants, 11 regions and two
country entries into the business now named `My_RMC1`, with backups. Approved
Auckland hierarchy links cover 15 plants across nine regions; the remaining
eight South/Warangal plants require reviewed region splits. Legacy route/trip
organization IDs remain null until reviewed backfill.
Do not assign all old records to the first company that logs in.
Use the documented [adoption workflow](./CATALOGUE_API.md#legacy-ownership-migration).

`create_all` creates missing tables; it does not upgrade all pre-existing
columns. The custom additive migrations cover specific changes, not every
historical operational schema.

### Local run

From the repository root with a configured environment and installed dependencies:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Starting the app invokes migrations and the monitor. Use an isolated development
database, not an unbacked-up operational database.

### Operational deployment

- SQLite is intentional for the current small workload (approximately 3-4
  trips/day), not an accidental placeholder that must immediately be replaced.
- Use a persistent disk/volume and one backend process/instance.
- A persistent volume is not a backup; perform consistent SQLite backups and
  verify restoration.
- Ordinary ephemeral Cloud Run container storage is unsuitable for durable
  SQLite operational records.
- Deploy HTTPS before relying on browser geolocation.
- Restrict CORS; current application middleware permits wildcard origins.
- Review log retention and credential redaction.
- Do not assume `/health` proves database, Google, weather, Clerk, LLM, and
  monitor readiness.
- Use [deployment notes](./GCP_DEPLOYMENT.md) as guidance, but recheck older
  secret/configuration examples against the current auth requirements.

## 11. Validation status and known gaps

### What has been checked

- Earlier offline explicit regression suites reached 175 passing tests before
  subsequent ownership/geography changes.
- Latest business/geography flow passed in-memory onboarding and HTTP smoke
  checks, including business visibility and denied cross-company access.
- In-memory seed/migration checks and API/schema registration checks passed.
- Those isolated checks did not migrate the operational database. Subsequent
  explicitly approved operator adoption/linkage did update the local catalogue,
  after integrity-checked SQLite backups; it did not backfill historical trips.
- All 12 changed test modules passed together: 203 tests covering authentication,
  tenant scoping, catalogue/migrations, private geography/linkage, analysis,
  UTC timestamps, routes and trip completion. Older ownership fixtures were
  updated to the current contract. The full repository suite was not run.
- Existing Pydantic/SQLAlchemy deprecation warnings and a Google Maps client
  cleanup coroutine warning remain; IDE diagnostics were unavailable.
- Live Clerk, Google, production UI, deployed startup, and production backups
  were not verified as part of this implementation.

Passing earlier tests must not be reported as validation of the newest schema.

### Open work

| Priority area | Remaining issue |
|---|---|
| Delivery decisions | Weather failures can resemble favourable conditions; wind warnings and recommendation logic need review |
| Regional correctness | Weather/congestion local-hour handling and NZ-derived international calibration remain unresolved |
| Routing | Traffic-model cache separation and vehicle/truck restriction enforcement |
| Monitoring | Expiry evaluation during outages/pauses, terminal-state races, truthful failure counting |
| GPS | Old-but-ordered positions can still be stale; browser-only background tracking is unreliable |
| Completion | Separate arrival from confirmed pour; add reviewer/decision/notes resolution workflow |
| Predictions | Historical trip data is not automatically training/improving live predictions |
| LLM | Returned JSON needs stronger semantic/type validation |
| Tenant administration | No Clerk provisioning/sync; local registration trusts owner-supplied organization ID |
| Fleet/driver RBAC | No organization-scoped fleet management or per-driver assigned-trip policy |
| Geography | No worldwide dataset import, geocoder-backed catalogue population, or country/state/city edit workflow; unused deletion is available |
| Data integrity | Some relationships are logical/service-enforced; direct SQL can bypass invariants |
| Operations | Readiness, HTTPS/CORS, backup restoration, reproducible builds and complete upgrade procedure |

Multi-stop planning, stock/capacity scheduling, proof-of-delivery documents,
billing, enterprise onboarding automation, and native mobile background GPS
must not be described as completed features.

See [functional review and remediation tracker](../review-doc.md) for evidence
and historical finding status; earlier sections describe defects before fixes,
so read its remediation progress first.

## 12. Handover and maintenance checklist

### Before another developer takes over

- [ ] Identify the backend branch/revision and separate frontend revision.
- [ ] Review existing uncommitted changes; do not discard unrelated work.
- [ ] Confirm who owns platform configuration, Clerk organizations, and deployment.
- [ ] Share secrets through an approved secret store, never this document.
- [ ] Confirm the actual deployment database path and backup owner.
- [ ] Reconcile legacy ownership/city links and any conflicting assignments.
- [ ] Update/execute focused tests for the newest contracts.
- [ ] Verify login, org switching, owner dashboard, dispatch, GPS, and SSE end to end.

### Before production rollout

- [ ] Back up the database and test restoration.
- [ ] Apply startup migrations against a copy of the real schema.
- [ ] Validate tenant isolation with at least two businesses.
- [ ] Verify platform owner without active org cannot invoke unscoped operations.
- [ ] Configure issuer/JWKS/authorized parties and HTTPS/CORS.
- [ ] Verify monitor startup, outage behavior, and observable failure reporting.
- [ ] Clearly label uncalibrated predictions as planning estimates.
- [ ] Review unresolved functional risks before using recommendations operationally.

### Keeping this document maintainable

Update this handover in the same change as any:

- New/changed table, column, constraint, migration, or ownership rule.
- Endpoint or response-shape change.
- Permission or workflow change.
- External service or configuration change.
- Deployment architecture change.
- Validation milestone or resolved known gap.

Use ORM metadata for schema verification and the registered router/OpenAPI
for API verification; do not guess from old README feature lists or inspect
customer database contents to generate documentation.

Keep field-level payload examples in the specialist API documents. This
handover owns the overall system picture, table dictionary, operating model,
and transfer-of-responsibility checklist.
