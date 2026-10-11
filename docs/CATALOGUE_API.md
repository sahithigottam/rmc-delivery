# Structured catalogue API contract

This replaces the unpublished JSON-backed catalogue contract directly under
`/api/v1`. There is no `/v2` or legacy response adapter.

## Storage and rollout

- SQLite is the runtime source of truth for registered businesses, business-owned
  brands/plants, and structured geography.
- The versioned startup migration imports `config/plants.json` once, including
  inactive records. Existing plant IDs are preserved.
- The seed is not reread or overwritten on subsequent starts.
- Unknown legacy geography, invalid data, duplicate IDs, or ambiguous brand
  mappings fail migration rather than silently skipping records.
- Migration and seed import run transactionally. Back up the existing SQLite
  database before the first rollout and verify restore on a separate copy.
- This migration adds catalogue tables; it does not upgrade unrelated legacy
  trip/route columns. Operational schema migration remains a separate open task.
- Catalogue initialization failure prevents application startup.

## Authentication boundary

All `/api/v1` routes require a verified Clerk session JWT. Company operations
also require an active organization; the platform owner can administer the
business catalogues and legacy plant adoption without an active organization.
Super Admin, selected by the server-only `SUPER_ADMIN_USER_ID`,
is required to change business catalogues and geography. See
[AUTHENTICATION.md](./AUTHENTICATION.md) for setup, roles, and company plant
assignments. UI-only role checks are never authorization.

## Resources

| Endpoint | Methods | Response |
|---|---|---|
| `/businesses` | GET, POST | Page or registered business |
| `/businesses/{id}` | GET, PATCH | Business |
| `/countries` | GET, POST | Country catalogue |
| `/states` | GET, POST | State/province catalogue |
| `/cities` | GET, POST | City catalogue |
| `/brands` | GET, POST | Page or created brand |
| `/brands/{id}` | GET, PATCH | Brand |
| `/regions` | GET, POST | Page or created region |
| `/regions/{id}` | GET, PATCH, DELETE | Region; delete only when unused |
| `/plants` | GET, POST | Page or created plant |
| `/plants/{id}` | GET, PATCH | Plant |
| `/plants/analyse` | POST | Ranked plant predictions |

There is no PUT or plant/business/brand hard DELETE endpoint. Unused geography
may be deleted by a platform admin; in-use references return 409.
Deactivate a plant with PATCH; it
remains readable and historical trips retain their references.
IDs are immutable. Business IDs are existing Clerk `org_...` IDs; other new
resources receive opaque IDs such as `plant_<uuid>`.
Renaming does not alter an ID. Seed plant IDs remain unchanged.

## Register a business

Create the company organization and memberships in Clerk first. The platform
owner then calls `POST /api/v1/businesses` with an `Idempotency-Key`:

```json
{"id": "org_ExistingClerkOrganizationId", "name": "Business A"}
```

This registers a local business profile; it does not create, synchronize, or
verify an organization in Clerk. The owner must provide the actual organization
ID from Clerk. A company user sees only their own business. Business profiles
have a version-checked name PATCH and cannot be deleted through this API.

## Create a brand

```http
POST /api/v1/brands
Idempotency-Key: create-brand-unique-key
Content-Type: application/json
```

```json
{"name": "Example Concrete", "organization_id": "org_ExistingClerkOrganizationId"}
```

Brand names are trimmed and case-insensitively unique within their owning
business. Two businesses may use the same brand name. Ownership must reference
a registered business, and an owned brand cannot move to another business.
One brand may have plants across multiple countries. Geography is not a brand.

## Create a region

```json
{
  "name": "Warangal operating area",
  "city_id": "city_id_from_cities_endpoint"
}
```

`POST /api/v1/regions` also requires `Idempotency-Key`.
Create/select Country → State → City first. The region derives `country_code`,
`administrative_area`, `timezone`, and business ownership from its selected city
and state. Country/state creation requires the target `organization_id`; filter
geography lists by the business opened in Businesses. Geography is private to
that business, and a plant's region and brand must have matching owners. Optional
copies of these fields are accepted only when they match the selected hierarchy.
Country codes are assigned uppercase ISO 3166-1 alpha-2 codes; timezone is an
IANA zone. More than one operating region may belong to a city.
See [GEOGRAPHY_API.md](./GEOGRAPHY_API.md) for the dropdown endpoints.

New regions have `calibration_status: "uncalibrated"`; administrators cannot
claim validated calibration by supplying a status field. Seed NZ regions use
`"nz_baseline"`, describing the existing Auckland model, not proof of validation
for every location. A region metadata update resets calibration to uncalibrated.
Regional time metadata does not itself replace the existing prediction factors
or correct the still-open weather/local-hour findings.

Region PATCH currently requires all editable region fields plus `version`.
Brand PATCH requires `version` and a non-null changed field. Plant PATCH is partial.

## Create a plant

```json
{
  "name": "Warangal Plant",
  "brand_id": "brand_id_from_brands_endpoint",
  "region_id": "region_id_from_regions_endpoint",
  "address": "Warangal, Telangana, India",
  "location": {
    "latitude": 17.9833537,
    "longitude": 79.5335163
  },
  "active": true,
  "supported_mix_codes": ["GP", "HE", "RE"]
}
```

`POST /api/v1/plants` requires `Idempotency-Key`.
Address and required names cannot be blank; coordinates must be finite and
within geographic bounds. Brand and city-linked region must exist. The plant's
`organization_id` is derived from its brand, never supplied independently.
An owned plant cannot move to another business's brand. Mix codes must be a
nonempty, duplicate-free subset of GP, HE, RE. Supported mix codes describe
catalogue eligibility, not approval of a concrete-life or retarder policy.
Capacity, opening hours, approved regional mix policies, and truck constraints
are not implemented in this phase.

Successful create returns `201` and a `Location` header. Repeating the same
idempotency key and normalized body returns the same original response and does
not create a second resource or audit event. Reusing a key for a different body
or resource type returns `409`. Keys are database-persistent and currently do
not expire; use a new key for each intended create operation.

## Plant response

```json
{
  "id": "india_nit_warangal",
  "name": "NIT Warangal",
  "organization_id": null,
  "city_id": null,
  "state_id": null,
  "administrative_area": "Telangana",
  "brand_id": "brand_india",
  "region_id": "in_telangana_warangal",
  "address": "NIT Warangal, Warangal, Telangana, India",
  "location": {"latitude": 17.9833537, "longitude": 79.5335163},
  "active": true,
  "supported_mix_codes": ["GP", "HE", "RE"],
  "country_code": "IN",
  "timezone": "Asia/Kolkata",
  "calibration_status": "uncalibrated",
  "version": 1,
  "created_at": "2026-10-11T10:00:00Z",
  "updated_at": "2026-10-11T10:00:00Z"
}
```

This example is an unowned legacy seed plant. Country, state/city IDs, timezone,
and calibration status are derived from the referenced region. New plants also
return their owning business's `organization_id`.

## Legacy ownership migration

The seed is preserved, not rewritten. Existing brands/plants remain unowned
(`organization_id: null`), and old regions remain unlinked (`city_id: null`).
They are visible to the platform owner but not usable by company users.

1. Register the actual business.
2. Create/select its city hierarchy and PATCH the old region with `name`,
   `city_id`, and its last-read `version`.
3. Assign an unowned brand once through PATCH with `organization_id` and
   `version`, or create a new owned brand.
4. Adopt each plant with `POST /organizations/{organization_id}/plants`
   and `{"plant_id": "existing-id"}` when its brand belongs to that business.
   Alternatively, PATCH an unowned plant to the appropriate owned brand and
   city-linked region; this establishes its owner in the same versioned write.

Conflicting legacy assignments must be reviewed explicitly; ownership is never
inferred from them. The former multi-company assignment behavior is removed.
An owned plant cannot be unassigned or shared with another business. Deactivate
it with PATCH instead. DELETE of an owned assignment returns `409`; legacy
unowned assignment records can still be removed for reviewed cleanup.

## Lists and filters

All list resources return:

```json
{"items": [], "total": 0, "limit": 50, "offset": 0}
```

- Stable ordering by ID.
- `limit`: 1-100, default 50; `offset`: >= 0.
- Plants: `brand_id`, `region_id`, `country_code`, `state_id`, `city_id`,
  `administrative_area`, `organization_id`, `active_only` (default true).
- Regions: `country_code`, `state_id`, `city_id`, `administrative_area`.
- Brands: `organization_id` and pagination.
- Company brand/plant lists always use the verified active organization.
  Only the platform owner may filter across different businesses.
- Include inactive plants with `active_only=false`. Single-resource reads
  include inactive plants.

The old `/plants/brands` and `/plants/regions` dropdown routes are replaced by
structured `/brands` and `/regions` resources.

## Updates and conflict handling

```http
PATCH /api/v1/plants/india_nit_warangal
```

```json
{"version": 1, "active": false}
```

Every update supplies the last-read `version`. A successful write increments
it atomically. A stale version returns `409 VERSION_CONFLICT` with the current
version; reload and ask the user to resolve the conflict instead of blindly
retrying.

Plant PATCH must supply at least one changed field. Omitted fields are preserved.
Explicit null is rejected for all plant fields, including `active`. Unknown
request fields are rejected. Changes persist an audit record containing before
and after snapshots in the same transaction as the resource.

## Analysis and dispatch

```json
{
  "brand_id": "brand_india",
  "region_id": "in_telangana_warangal",
  "country_code": "IN",
  "job_site_data": {"display_name": "Kazipet Junction, Telangana, India"},
  "concrete_mix": "GP",
  "top_n": 3,
  "include_llm_analysis": false
}
```

Analysis now selects by `brand_id`, not a free-text brand name. Region and country
are optional filters. For a multi-country brand, specify one of them so the
request resolves to one country; analysis does not guess from the brand's name.
That country's code is passed to geocoding. Only active plants owned by the active business and supporting the
requested mix participate. When a shortlist is required, candidates are sorted
by distance to the resolved destination before applying `top_n`.

Results include the structured `plant` response and `brand_id` at the response
root. Per-plant routing failures remain explicit errors. Cache identity includes
plant, brand, and region versions and eligible membership so catalogue changes
cannot return stale catalogue analysis.

Dispatch rejects inactive/unsupported plants and persists a catalogue snapshot
alongside the existing prediction snapshot. Editing or deactivating a plant
does not retroactively change that snapshot. Historical operational records
without a snapshot are not rewritten. Foreign keys constrain catalogue relations;
existing trip plant-ID columns are not rebuilt in this phase.

## Errors

Catalogue business errors use FastAPI's established `detail` envelope:

```json
{
  "detail": {
    "code": "VERSION_CONFLICT",
    "message": "Resource has changed",
    "details": {"current_version": 3}
  }
}
```

This deliberately retains the application's existing envelope rather than
introducing a global error format during the catalogue change.
Pydantic request validation uses the standard `422 detail` array with field
locations. Request-ID middleware is not implemented in this phase.

| Status | Meaning |
|---|---|
| 201 | Resource created or original create response replayed |
| 401 | Missing or invalid Clerk bearer token |
| 403 | Insufficient role or no active company organization |
| 404 | Resource missing or no eligible plants |
| 405 | Unsupported replacement or catalogue hard-delete method |
| 409 | Version, duplicate brand, or idempotency conflict |
| 422 | Invalid fields/references, missing key, or ambiguous country |
| 502 | Destination geocoding failed while selecting closest candidates |

Successful create/update and plant assignment actions are attributed to the
verified Clerk user ID in the audit log.

## UI migration checklist

1. Owner: register the Clerk business and create/select countries, states, cities,
   and city-linked regions. Fetch business-filtered `/brands` and retain IDs.
2. Submit brand and region IDs in plant forms; use nested `location`.
3. Submit explicit supported mixes; display region timezone/calibration status.
4. Submit `brand_id` to analysis, with region/country for multi-country brands.
5. Read list `items`, not a raw array.
6. Preserve each edit's `version`; handle `409` without overwriting other edits.
7. Generate and preserve an `Idempotency-Key` across retries of each create.
8. Deactivate with PATCH; do not hard-delete referenced plants.
9. Send a Clerk session token as a Bearer token; Super Admin alone edits the
   business catalogues, and plant/brand ownership is exclusive to one business.
10. Weather availability flags are a separate pending backend change.
