# Backend Functionality Review

**Review date:** 2026-10-11  
**Workload:** Approximately 3-4 trips per day  
**Database:** SQLite  
**Scope:** Current backend worktree, including the recent India analysis,
100-metre completion review, and GPS capture-time changes.

## Executive assessment

SQLite is suitable for this workload. PostgreSQL, Redis, microservices, and a
larger deployment are not required to address the identified issues.

The principal concerns are time correctness, concrete-life calculations,
lifecycle consistency, and misleading recommendations. The backend should not
yet be treated as a reliable source of delivery feasibility or successful-pour
decisions.

This was a read-only audit. Existing tests and isolated SQLite/offline probes
were used; the operational database was not changed. The separate production UI,
live Google API behaviour, and concurrent writers across multiple backend
processes were not verified. This is a functional review, not a comprehensive
security audit.

## Priority definitions

- **P1:** Incorrect behaviour that can materially affect a dispatch or load-life decision.
- **P2:** Inconsistent lifecycle behaviour, incomplete functionality, or reliability gaps.
- **Operational:** Installation, deployment, persistence, and recovery requirements.

## Highest-priority findings

### Remediation progress

- **Finding 1 - COMPLETE (backend), verified 2026-10-11:** Client-supplied batch, schedule,
  departure, and GPS timestamps require an explicit timezone and normalize to
  UTC. A shared SQLAlchemy type stores UTC and restores awareness on SQLite
  reads; typed API responses return UTC timestamps. The UI must now send an
  offset or `Z` and display UTC values locally. Regression tests cover request
  validation, SQLite round trips, trip start/begin, dispatch, and response output.
  Historical timestamps with unknown lost offsets still require separate review
  and have not been rewritten. **Validation: 50 targeted regression tests passed.**
  UI integration and historical-data review remain follow-up work.
  This does not resolve the separate weather/local
  congestion-hour issue in finding 4.
- **Finding 2 - COMPLETE (backend), verified 2026-10-11:** New trips persist
  grade-adjusted base life separately from retarder extension. Response remaining
  life and monitoring reconstruct the same timer, with the extension applied
  once and high-grade thresholds preserved. Legacy extended-limit records are
  interpreted correctly when the stored batch/expiry interval confirms their
  representation, without rewriting historical data. The coupled monitoring
  keyword mismatch was also corrected.
  **Validation: 57 targeted regression tests passed**, including retarded and
  non-retarded start/begin, SQLite reload, high-grade limits, and legacy expiry.
  Historical records missing reliable expiry evidence still need assessment.
- **Finding 3 - COMPLETE (backend), verified 2026-10-11:** Completion recomputes
  actual load status from the shared timer, not the last projected traffic status.
  Future/already-expired batches are rejected before start/begin; valid older
  batches start with their actual status. Operator success for an expired load
  requires non-blank notes, preserves actual expired status, and is durably
  flagged for review together with any location reason.
  **Validation: 71 targeted regression tests passed**, including stale/projected
  status, manual/automatic outcomes, rejected blank overrides, accepted audited
  overrides, invalid batch times, and pending completion.
- **Finding 9 - COMPLETE (backend), verified 2026-10-11:** Pending completion is
  rejected; only in-progress or paused trips can complete. Covered in the
  71-test regression run.
- **Finding 8 - PARTIALLY COMPLETE:** Automatic and manual completion now use
  the same timer-based default outcome. Separating GPS arrival from confirmed
  pour completion still requires a workflow decision and UI integration.
- **Structured catalogue - COMPLETE (backend), verified 2026-10-11:** Brands,
  regions, and plants now use SQLite tables with strict request schemas,
  pagination, immutable IDs, version-checked edits, idempotent creates, and
  transactional change audits. A versioned, atomic seed migration preserves all
  existing plant IDs and inactive records and does not overwrite catalogue
  changes on restart. Analysis, locator, and dispatch read the database.
  Dispatch saves a catalogue snapshot and rejects inactive/unsupported plants.
  Clerk verification now protects `/api/v1`; company routes/trips are scoped by
  verified organization, and actor IDs are persisted on routes, trips, and audit
  events. Only the environment-configured verified Clerk user ID is platform
  Super Admin; `org:admin` is company-scoped and never grants platform access.
  Company roles share operational access for now. The owner alone registers
  businesses and manages business-owned brands/plants and private geography.
  New plants inherit exclusive business ownership from their brands.
  Country/state/city-linked regions support international business locations;
  legacy catalogue ownership is not guessed automatically. `GET /auth/me` exposes
  verified capabilities; company cross-org mutation returns 403.
  Additive auth migration preserves old rows
  unassigned; a separate reviewed backfill is required before they are visible.
  Related fixtures now reflect exclusive ownership and private geography.
  All 12 changed test modules passed together (203 tests); the full repository
  suite and production UI integration were not verified.
  In-memory onboarding and legacy seed migration smoke checks passed. Subsequent
  explicitly approved operator commands adopted the local catalogue and linked
  the reviewed Auckland subset after SQLite backups; historical trip ownership
  was not backfilled.
  Terminal trip DELETE now archives rather than erasing trip/event history.
  UI integration and live Clerk token verification remain unverified. No
  operational database migration was executed during implementation.
  **Validation: 136 tests passed using isolated SQLite**, including migration,
  catalogue API, and previous UTC/load/completion regressions.
  See [Catalogue API contract](docs/CATALOGUE_API.md) for breaking unpublished
  `/api/v1` UI changes and remaining production integration requirements.
- **Plant shortlist finding - COMPLETE (backend):** Brand analysis now sorts
  eligible plants by distance before applying `top_n`, with catalogue-version
  cache invalidation. Covered in the 136-test suite.
- **Dependency installation finding - COMPLETE (manifest):** Direct runtime
  `cachetools` and timezone database `tzdata` dependencies are declared. A fresh
  container build was not run.
- Other findings remain open unless explicitly updated here.

### 1. P1: Batch and scheduled timestamps are not consistently normalized to UTC

**Status: COMPLETE for new requests, persistence, and typed responses.**
Historical-data assessment remains open; the following describes the original defect.

Client-supplied batch and scheduled times accept general datetimes without a
consistent UTC normalization contract. SQLite drops their timezone offsets;
subsequent load-timer handling treats naive batch times as UTC.

**Evidence:** An isolated SQLite round trip of `2026-10-11T10:00:00+05:30`
returned `2026-10-11T10:00:00` without a timezone. Interpreting that as UTC makes
the batch appear 5.5 hours fresher than its actual `04:30Z` capture time.

The new GPS `captured_at` handling does not fix batch or scheduling timestamps.

**Recommended correction:** Require an explicit offset for client-supplied
timestamps, normalize to UTC before persistence, and return timezone-qualified
UTC values. Assess existing stored timestamps before attempting a data repair;
their original timezone may not be recoverable.

**References:** [Request schemas](app/schemas/__init__.py),
[trip lifecycle](app/services/trip.py),
[load timer](app/domain/values.py), [database models](app/db/models.py).

### 2. P1: Retarder extension is counted twice

**Status: COMPLETE for new trips and confirmed legacy representations.**
Records without reliable expiry evidence remain follow-up work. The following
describes the original defect.

Trip begin stores the already-extended effective life in
`load_max_life_minutes`. Later reconstruction passes that value and the retarder
extension into `LoadTimer`, which adds the extension again. The response's
remaining-time calculation also adds it again.

**Evidence:** A standard 90-minute load with a 45-minute extension can be
evaluated as 180 minutes instead of 135. The persisted expiry timestamp and the
subsequent remaining-life/status calculations disagree.

**Recommended correction:** Persist base life and extension separately and use
one shared calculation for effective life, expiry, and remaining time. Add
round-trip tests and assess affected existing trip records.

**References:** [Trip begin, timer reconstruction, and response calculation](app/services/trip.py),
[LoadTimer](app/domain/values.py).

### 3. P1: Completion derives success from stale load status

**Status: COMPLETE for completion-time checks and batch validation.**
Explicit expired-load success overrides require an audited reason and review.
The following describes the original defect.

Manual completion without an explicit outcome treats the trip as succeeded
unless its persisted `load_status` is `expired`. This status is not recomputed
from the actual timer at completion. Begin can also accept an already-expired
or future batch time while initializing the load as fresh.

The monitor can persist a projected expired status based on ETA, which is not
necessarily the same as the actual status at an earlier arrival.

**Impact:** A load that expired between checks can be recorded as succeeded.
Recorded delivery outcome is not reliably tied to actual expiry or pour state.
An explicit `success=True` can override an expired status.

**Recommended correction:** Validate batch times at begin, calculate actual
load status at lifecycle transitions, distinguish actual from projected status,
and define how operator-reported pour outcomes and overrides are audited.

**References:** [Trip begin and completion](app/services/trip.py),
[load evaluation](app/rmc/load_manager.py).

### 4. P1: Weather and congestion calculations use the wrong hour

Weather requests use Auckland-local hourly labels for every destination, but
forecast selection matches those labels against UTC. Prediction also supplies
UTC hour and weekday to local NZTA congestion factors.

**Evidence:** A synthetic forecast at 09:45 UTC, corresponding to 22:45 Auckland
time, selected forecast hour 09 instead of 22. India destinations also request
the Auckland forecast timezone.

**Recommended correction:** Match weather data using unambiguous instants and
use the appropriate location's local hour/day for time-of-day factors. Keep
timezone correction separate from the unresolved India calibration question.

**References:** [Weather request and parsing](app/services/weather.py),
[prediction orchestration](app/services/prediction.py).

### 5. P1: Critical wind warnings do not control the final recommendation

The predictor adds a critical risk factor for unsafe pump-truck wind, but the
final risk label and recommendation follow remaining concrete life.

**Evidence:** An isolated input with `pump_truck_safe=False` and 61 km/h gusts
produced LOW risk and DISPATCH NOW alongside an unsafe-wind risk factor.

**Recommended correction:** Ensure critical operational conditions control
the final decision. Distinguish travel feasibility from whether site operations
are safe, including whether a pump truck is actually required.

**Reference:** [Risk factors and final recommendation](app/rmc/predictor.py).

### 6. P1: Weather failure can look like favourable weather

Weather fetch failures use neutral impact factors and mark pump conditions
safe. The predictor does not distinguish unavailable weather from benign
weather when selecting a recommendation.

**Evidence:** An isolated fallback-weather prediction produced LOW risk,
approximately 0.952 success probability, and DISPATCH NOW despite reporting
Unknown (API unavailable) weather.

**Recommended correction:** Surface an explicit degraded/unknown state and
require the appropriate operator check instead of issuing an all-clear.

**References:** [Weather fallback](app/services/weather.py),
[prediction decisions](app/rmc/predictor.py).

### 7. P1: Directions cache does not distinguish traffic models

The Directions cache key omits `traffic_model`, although the outgoing request
uses it.

**Evidence:** Otherwise-identical pessimistic, best-guess, and optimistic
requests share a cache key. A later caller can receive the first model's ETA.

**Recommended correction:** Include every response-affecting routing option,
including the traffic model, in the cache key and test model separation.

**Reference:** [Directions requests and cache keys](app/services/google_maps.py).

## Lifecycle and tracking findings

### 8. P2: GPS arrival and successful delivery are conflated

**Status: PARTIALLY COMPLETE.** Automatic outcomes are now consistent with manual
defaults. Separating arrival from pour completion remains open.

An in-radius GPS report calls the shared completion helper directly and leaves
`outcome=None`; manual completion assigns an outcome. More fundamentally,
being within 100 metres proves neither unloading nor a successful pour.

**Recommended correction:** Define arrival and delivery completion as distinct
business events, and make automatic and manual paths consistent with that
definition.

**Reference:** [Position updates and completion](app/services/trip.py).

### 9. P2: A pending trip can be completed without ever starting

**Status: COMPLETE.** Pending completion is now rejected.

Completion rejects completed and cancelled trips but permits pending trips.
A dispatched-but-never-begun trip can therefore be recorded as completed and,
by default, succeeded.

**Recommended correction:** Enforce an explicit lifecycle transition matrix.
Cancelled trips are already rejected; the identified gap is pending completion.

**Reference:** [Completion guards](app/services/trip.py).

### 10. P2: Load expiry evaluation depends on successful traffic checks

Monitoring selects only in-progress trips. Traffic checking skips trips within
1 km of the site, and load evaluation depends on a successful Directions
response. Concrete continues ageing during pauses, near the site, and during
routing outages.

**Recommended correction:** Evaluate load expiry independently of routing,
including paused trips and nearby trips. Publish expiry alerts on transitions
rather than repeatedly on every successful monitoring cycle.

**References:** [Traffic monitor](app/services/traffic_monitor.py),
[traffic-check early returns](app/services/trip.py),
[expiry events](app/rmc/load_manager.py).

### 11. P2: An in-flight traffic check can reroute a completed trip

The traffic check reads active status before awaiting Directions but does not
revalidate it after the await.

**Evidence:** In an isolated SQLite probe, completion occurred while Directions
was pending. When the response arrived, the check changed the polyline and
reroute count and logged traffic/reroute events after `trip_completed`. Status
remained completed; this was a post-completion write, not status resurrection.

**Recommended correction:** Re-read and validate state before applying routing
results, and ensure updates are conditional on the trip still being active.

**Reference:** [Traffic-check continuation](app/services/trip.py).

### 12. P2: GPS ordering protection is not freshness protection

The new timestamp handling rejects future, duplicate, and out-of-order reports.
However, an hours-old capture newer than the previous accepted report can still
auto-complete a trip if its coordinates are within the radius.

**Recommended correction:** Preserve delayed history but require fresh evidence
for terminal/arrival transitions. Define a freshness policy explicitly rather
than discarding all delayed reports.

SQLite ignores the row-level `with_for_update()` lock. No same-event-loop
captured-at lost-update race was reproduced: the synchronous update commits
before its ordinary async yield. Multiple-process writer behaviour was not
established by this audit.

**Reference:** [GPS timestamp validation](app/services/trip.py).

### 13. P2: Traffic-failure review misses ordinary failures

The monitor counts failures when the service raises, but the service catches
ordinary errors and returns normally. A non-OK Directions response path also
logs an event without committing it, so session close discards that event.

**Recommended correction:** Give the monitor an explicit failure result or
consistent exception contract and persist failure audit events. Make the
consecutive-failure review threshold testable.

**References:** [Traffic service failure paths](app/services/trip.py),
[monitor failure counting](app/services/traffic_monitor.py).

### Completion review: working and missing parts

The 100-metre completion review flag is durable: it is stored in the completion
audit event and returned independently of the recent-events limit.

Remaining gaps:

- No implemented review-resolution workflow with reviewer, decision, and notes.
- Location-based review does not independently authenticate GPS evidence.
- Missing coordinates require review, but old coordinates can still look valid.
- Reliable browser tracking cannot continue after the browser is closed or the
  operating system suspends the page. Background tracking requires a native app
  and the necessary OS permissions.

## Other missing functionality

| Area | Finding | Reference |
|---|---|---|
| Truck routing | Vehicle/load fields are accepted and stored, but routes use generic driving directions; truck access and load restrictions are not enforced. | [Routing](app/services/route.py), [Google driving mode](app/services/google_maps.py) |
| Historical prediction | Live prediction never supplies DB-derived route profiles or global statistics. Accumulating completed trips does not currently improve this prediction path. | [PredictionService](app/services/prediction.py) |
| Plant shortlist | Brand analysis selects `top_n` plants by catalogue order before evaluating them, not by proximity. Later ranking cannot recover excluded plants. | [Brand analysis](app/api/v1/endpoints/plants.py) |
| LLM output | Valid JSON with the wrong fields/types can be treated as successful analysis because the promised output schema is not validated. | [LLM parsing](app/services/llm_analyzer.py) |
| India calibration | India routes use the existing NZTA/NZS baselines. They should remain clearly labelled planning estimates until local evidence supports calibration. | [Predictor](app/rmc/predictor.py), [API limitations](docs/API.md) |

## SQLite and deployment assessment

Keep SQLite for the stated workload and address these operational basics:

1. **Schema upgrades (partially addressed):** The new catalogue has a versioned
   transactional migration and seed import. Other operational tables still use
   `create_all`, which does not upgrade
   existing tables. An isolated legacy-table probe confirmed this.
   Introduce versioned migrations and a safe upgrade procedure.
   Reference: [Startup](app/main.py).
2. **Truthful readiness:** Health reports healthy even after database
   initialization and monitor startup fail. This was reproduced with mocked
   startup failures. Distinguish process liveness from operational readiness.
   Reference: [Startup and health](app/main.py).
3. **Reproducible installation (manifest corrected):** The originally omitted
   `cachetools` dependency is now declared alongside `tzdata` for IANA timezone
   validation. A clean container build remains unverified.
   References: [Requirements](requirements.txt), [Google service](app/services/google_maps.py),
   [route service](app/services/route.py), [plant endpoint](app/api/v1/endpoints/plants.py).
4. **Backup and restore:** A persistent volume is not a backup. Define a
   consistent SQLite backup procedure and verify restoration. No implemented
   backup/restore tooling was found in scope.
   References: [SQLite deployment](docker-compose.sqlite.yml),
   [deployment guide](docs/GCP_DEPLOYMENT.md).
5. **HTTPS:** The deployment guide exposes plain HTTP. Production browser
   geolocation requires a secure context; deploy HTTPS before relying on phone
   GPS tracking.
   Reference: [Deployment guide](docs/GCP_DEPLOYMENT.md).

## Recommended correction sequence

1. UTC normalization and retarder arithmetic, including affected-data assessment.
2. Actual expiry checks and consistent lifecycle/outcome rules.
3. Weather-hour correctness and decision-controlling critical warnings.
4. Independent expiry monitoring, terminal-state rechecks, and GPS freshness.
5. Cache correctness, readiness, dependencies, backups, and HTTPS.
6. Review resolution, prediction calibration, and truck-routing limitations.

## Validation and limitations

- All **45 existing tests passed** against isolated SQLite.
- Probes used synthetic responses and isolated databases; no live external API
  calls or operational database writes were required.
- Passing tests confirm covered behaviour, not production readiness.
- Important missing regression coverage includes:
  - Offset-time SQLite round trips for batch and scheduled times.
  - Retarder reconstruction and consistent expiry/remaining-life calculations.
  - Expiry during pauses, near the site, and routing outages.
  - Critical weather and unknown-weather decisions.
  - Traffic-model cache separation.
  - Pending completion and automatic completion outcomes.
  - Old-but-ordered GPS reports causing arrival/completion.
  - Traffic-check/completion concurrency.
  - Failure-count review thresholds and review resolution.
  - Existing-schema upgrades and backup restoration.

No fixes were implemented during the original read-only audit. Subsequent fixes
and validation results are tracked in Remediation progress above. Source
references identify the reviewed implementation; revalidate remaining findings
after subsequent changes.
