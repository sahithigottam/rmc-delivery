# Geography Catalogue API

The geography catalogue is now **private to each business**, with hierarchy
**Country → State → City → Region**. It does not seed or infer a real-world
geography dataset; platform owners must add verified records.

## Authentication and ownership

All routes require an authenticated Clerk session, including when the endpoint
router is included outside the parent `/api/v1` router. Reads are available to
authenticated users, restricted to their active business. Platform admins can
filter lists by `organization_id` or view all businesses. Creating countries,
states, and cities requires the
configured platform owner (`require_super_admin`).

Country and state creation requires `organization_id`. City ownership is
inherited from its state, and region ownership from its city. A plant's region
and brand must belong to the same business. Businesses may independently create
the same country code, state name, and city name.

Country GET detail and DELETE use a country code plus business: platform admins
must pass `?organization_id=org_...`; company GET detail defaults to the active
organization. Company roles cannot write/delete geography.
All output records include `organization_id`. States/cities retain opaque IDs.

## Routes

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/countries` | Paginated country list |
| `GET` | `/api/v1/countries/{country_code}` | Country detail |
| `POST` | `/api/v1/countries` | Create a country |
| `GET` | `/api/v1/states?country_code=IN` | Paginated state list, optionally filtered by country |
| `GET` | `/api/v1/states/{state_id}` | State detail |
| `POST` | `/api/v1/states` | Create a state under an existing country |
| `GET` | `/api/v1/cities?country_code=IN&state_id=...` | Paginated city list filtered by either or both parent IDs |
| `GET` | `/api/v1/cities/{city_id}` | City detail |
| `POST` | `/api/v1/cities` | Create a city under an existing state |
| `DELETE` | `/api/v1/countries/{country_code}` | Delete an unused country (platform admin) |
| `DELETE` | `/api/v1/states/{state_id}` | Delete an unused state (platform admin) |
| `DELETE` | `/api/v1/cities/{city_id}` | Delete an unused city (platform admin) |
| `DELETE` | `/api/v1/regions/{region_id}` | Delete an unused operating region (platform admin) |

List routes accept `limit` (default 50, maximum 100) and `offset` (default 0)
and return `{ "items": [], "total": 0, "limit": 50, "offset": 0 }`.

Example request sequence:

```json
POST /api/v1/countries
{"organization_id":"org_ActualClerkId","code":"IN","name":"India"}
```

```json
POST /api/v1/states
{"organization_id":"org_ActualClerkId","country_code":"IN","name":"Telangana"}
```

```json
POST /api/v1/cities
{"country_code":"IN","state_id":"<state-uuid>","name":"Warangal","timezone":"Asia/Kolkata"}
```

Country codes must be assigned ISO 3166-1 alpha-2 uppercase codes. State and
city IDs are generated UUIDs. State names are unique case-insensitively within
a business/country; city names are unique case-insensitively within a state. A supplied
city `country_code` is an optional consistency assertion and must match the
state's country. City timezones must be valid IANA timezone identifiers.
Missing parents return `404`, parent-country mismatches return `422`, and
duplicate keys return `409`.

Geography POST endpoints do not currently require an `Idempotency-Key`.
The database rejects duplicate country codes, state names within a country,
and city names within a state. Fetch the existing record after an ambiguous
retry instead of creating another dropdown option. Creates persist an audit
event with the verified platform-owner user ID.

## Deleting unused records

Deletion returns 204, missing IDs return 404, company roles receive 403.
In-use records return 409 `GEOGRAPHY_IN_USE`; no children are deleted automatically.
Remove unused children first: region, city, state, country.

- A region cannot be deleted while any plant references it, including inactive plants.
- A city cannot be deleted while a region references it.
- A state cannot be deleted while a city references it.
- A business country cannot be deleted while that business's states, regions
  (including legacy ones), or saved job sites reference its country code.
  Another business using the same ISO code does not block this deletion.

Deletion preserves an actor-attributed audit event and the previous record
snapshot. Historical audit/idempotency responses are not erased. The UI should
ask for confirmation and show the server's in-use reason rather than offering
cascade deletion.

Legacy Warangal/NZ regions came from the existing plant seed's region labels.
Their country/state/timezone mapping was manually supplied in the seed migration,
not imported from a verified worldwide dataset. In particular, the legacy NZ
mapping uses Auckland broadly and needs location-by-location review.

## Migration and Region integration

`app.db.geography_migration.migrate_geography(engine)` creates only the
`countries`, `states`, and `cities` tables plus the business FK prerequisite,
is idempotent, and does not seed,
backfill, or rewrite records. Startup now runs this migration before catalogue
initialization, then adds nullable business ownership and region city-link
columns. Back up and verify the deployment against staging before starting the
updated application on an operational database.

Regions require a `city_id` on create/update and derive country/state/timezone
from the selected city. Existing regions without a city remain untouched until
the platform owner explicitly links them. The list starts empty; there is no
automatic worldwide import or address lookup. Add only the verified locations
where your businesses operate.

### Storage and current legacy adoption

`business_countries` stores private country entries keyed by business and ISO
code. `countries` remains an internal code/name anchor for legacy foreign keys;
it is not exposed as a shared business dropdown or removed when a private entry
is deleted. States, cities, and regions have nullable owner columns to preserve
unadopted legacy records. Private dropdowns never expose those unowned rows.

The operator explicitly assigned the existing 15 brands, 23 plants, 11 regions,
and two country entries to `rmc-delivery`. There were no structured state/city
rows to adopt. SQLite backups were taken before the approved operations.

After reviewing the existing addresses, the operator approved a limited linkage:
New Zealand -> Auckland administrative region -> Auckland city, covering the
nine non-South NZ operating regions and their 15 plants. Plant/region IDs,
plant versions, addresses, coordinates, and calibration settings are preserved;
region versions increment when their city link changes. These are approved
catalogue mappings, not independently geocoded or verified plant locations.

The remaining eight plants deliberately retain null city/state links:
the shared South region contains three Auckland-address plants and two
Pokeno-address plants, while Warangal contains one Warangal-address plant and
two Hanamkonda-address plants. Since each region has only one city parent,
accurate linkage for those records requires a separately approved region split.

The bounded operator command is:

```powershell
python -m scripts.link_legacy_auckland_geography --organization-id org_ActualClerkId --backup-directory C:\Backups
```

It takes an integrity-checked SQLite backup before linking, validates the exact
approved plant membership and business ownership, and applies the hierarchy and
region audit events in one transaction. Conflicts abort without partial changes.
Repeated execution preserves IDs/versions and adds no duplicate audit events.
Operator audit events have no fabricated authenticated actor; their source is
`explicit_operator_approved_auckland_linkage`. This is not an automatic migration
or a general-purpose geography importer.
