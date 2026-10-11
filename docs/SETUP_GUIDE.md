# Start here: setup and first business

This is the ordered setup guide. Read this first, not every technical document.
It describes the current backend; some frontend screens still need integration.

## 1. Understand the five different things

| Term | Meaning | Example |
|---|---|---|
| Platform owner | You, managing the whole application | Verified user matching `SUPER_ADMIN_USER_ID` |
| Business | A customer company, represented by a Clerk organization | rmc-delivery |
| Brand | A supplier label owned by a business | Example Concrete |
| Plant | A batching location that produces concrete | Warangal batching plant |
| Job site | A customer's delivery destination | Kazipet construction project |

**Plants and job sites are not the same.**
The plant seed contains batching plants, not saved delivery job sites.

One business can own several brands and plants across countries.
Do not create a separate Clerk organization for each city unless it is actually
a separate customer business.

## 2. Prepare the backend

Prerequisites:

- Python and the repository's virtual environment/dependencies.
- Google Maps key for routing.
- Existing Clerk application.
- Persistent SQLite database for the current deployment.

On Windows, from the backend repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Skip virtual-environment creation if it already exists.
Do not create a replacement Clerk application for this project.

## 3. Configure backend authentication

Create/update the backend root `.env`, not just the frontend environment.
Do not commit this file. Preserve existing database/Google configuration.

For the existing development Clerk instance:

```env
CLERK_ISSUER=https://live-robin-8047.clerk.accounts.dev
CLERK_JWKS_URL=https://live-robin-8047.clerk.accounts.dev/.well-known/jwks.json
CLERK_AUTHORIZED_PARTIES=http://localhost:3000
SUPER_ADMIN_USER_ID=user_REPLACE_WITH_YOUR_CLERK_USER_ID
```

- Get your user ID from Clerk Dashboard -> Users -> your user.
- For multiple platform admins use
  `SUPER_ADMIN_USER_ID=user_first;user_second`. Every listed ID has identical
  platform privileges. Single-ID configuration remains supported.
- Issuer is the instance Frontend API URL, not `https://api.clerk.com`.
- Do not paste a public-key block into the backend; it retrieves JWKS keys.
- A Clerk secret key is not required for this backend's JWT verification.
- Change authorized frontend origins and Clerk instance settings deliberately
  when moving to production.
- Set `GOOGLE_MAPS_API_KEY` securely for routing.
- Default database is `sqlite:///./rmc_delivery.db`; set `DATABASE_URL` explicitly
  when using an isolated development copy or a persistent deployment volume.

## 4. Start or restart FastAPI

**Back up an existing operational database before running updated startup
migrations.** Prefer verifying the upgrade on a copy first.

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Run from the repository root. Startup creates missing tables and applies
specific catalogue/auth/business/geography migrations. It is not a complete
repair tool for every old schema.

After changing `.env`, fully stop/restart FastAPI. Saving environment values
or restarting only Next.js does not reload an already-running backend.

The default API is at `http://localhost:8000`; interactive docs are at `/docs`.
Production should use persistent storage, HTTPS, and one backend instance.

## 5. Connect the frontend and verify login

The real frontend is the separate Next.js project, not the legacy Gradio client.
Its team must configure the existing Clerk application and proxy/backend URL.
Do not move the backend owner ID into public frontend configuration.

After login, the UI calls:

```http
GET /api/v1/auth/me
Authorization: Bearer <current Clerk session token>
```

Check:

- `is_platform_admin: true` for your configured owner account.
- `can_manage_businesses: true` and `can_manage_catalogue: true` for the owner.
- Company operations/job sites require an active supported organization role.
- The owner can manage catalogues without an active organization, but cannot
  perform unscoped trip/job-site operations.

Do not paste tokens into URLs, screenshots, source files, or this guide.

## 6. Create the company in Clerk

In Clerk Dashboard:

1. Open Organizations and create/select the customer company.
2. Invite/add its users.
3. Assign supported organization roles.
4. Copy the organization's **ID**.

The company name `rmc-delivery` is not its ID. Its ID looks like `org_...`.
The backend cannot infer that ID from the display name.

Current supported roles:

- `org:admin`: company admin, not platform owner.
- `org:plantadmin`, `org:driver`, `org:member`: company operations.

These roles currently share operational permissions. Driver-specific
assigned-trip restrictions are not implemented.

## 7. Register the same company in the backend

Use the platform-owner UI once wired, or an authenticated API client.
Every example below is a request payload, not a command to paste in a shell.

```http
POST /api/v1/businesses
Idempotency-Key: unique-business-create-key
```

```json
{"id": "org_ACTUAL_CLERK_ORGANIZATION_ID", "name": "rmc-delivery"}
```

This creates a local business record only. It does not create, validate, or
invite members to a Clerk organization. Use the actual ID from step 6.

Keep returned resource IDs and versions for subsequent requests.

## 8. Add the locations where the company operates

Create/select in this order:

1. Country.
2. State/province within country.
3. City within state.
4. Operating region within city.

The geography list is private to each business and curated, not automatically
populated worldwide. On platform-admin screens, use the business opened in
Businesses, not blindly the active Clerk organization. Filter paginated lists
with `organization_id=org_ActualClerkId` before creating duplicates.

| POST endpoint | Example body |
|---|---|
| `/api/v1/countries` | `{"organization_id":"org_ActualClerkId","code":"IN","name":"India"}` |
| `/api/v1/states` | `{"organization_id":"org_ActualClerkId","country_code":"IN","name":"Telangana"}` |
| `/api/v1/cities` | `{"state_id":"returned-state-id","name":"Warangal","timezone":"Asia/Kolkata"}` |
| `/api/v1/regions` | `{"name":"Warangal area","city_id":"returned-city-id"}` |

Country/state/city creation does not require an idempotency key; region creation
does. Duplicate geographic records return 409. Region country/state/timezone
and ownership are derived from the selected hierarchy. Country detail/delete
requires `?organization_id=org_ActualClerkId` for platform admins. Clear dependent
selections and business-scoped caches when switching businesses.

For another country, repeat the location steps. The business stays the same.
Do not infer the city of every legacy plant from its seed region label.

Platform admins may delete unused countries/states/cities/regions through their
detail DELETE endpoints. Referenced records return 409; there is no cascade.
See [geography deletion rules](./GEOGRAPHY_API.md#deleting-unused-records).

## 9. Create brands and plants

Create a business-owned brand:

```http
POST /api/v1/brands
Idempotency-Key: unique-brand-create-key
```

```json
{"name":"Example Concrete","organization_id":"org_ACTUAL_CLERK_ORGANIZATION_ID"}
```

Create a plant using returned brand and region IDs:

```http
POST /api/v1/plants
Idempotency-Key: unique-plant-create-key
```

```json
{
  "name": "Warangal Plant",
  "brand_id": "returned-brand-id",
  "region_id": "returned-region-id",
  "address": "Warangal, Telangana, India",
  "location": {"latitude": 17.9833537, "longitude": 79.5335163},
  "supported_mix_codes": ["GP", "HE", "RE"],
  "active": true
}
```

The plant inherits the brand's business owner. It cannot be shared with or
transferred to another business. Deactivate through PATCH instead of deleting.

### If you want existing seed plants instead

Startup imports the plant seed once. Re-importing or editing the JSON is not
the way to assign company ownership.

Legacy plants may already exist but remain unowned/hidden from company users.
The owner must register the business, link legacy regions to verified cities,
assign/adopt legacy brands and plants, and resolve conflicting assignments.
Follow [legacy adoption instructions](./CATALOGUE_API.md#legacy-ownership-migration).
Do not automatically assign all brands to the first company.

For the current local catalogue, the operator explicitly adopted 15 brands,
23 plants, 11 regions and two country entries into the business now named
`My_RMC1`, after backups. Approved Auckland links cover 15 plants; the eight
South/Warangal exceptions remain unlinked pending review. See the
[current legacy linkage](./GEOGRAPHY_API.md#storage-and-current-legacy-adoption).

## 10. Add delivery job sites

Select the active company in Clerk first. Job-site ownership comes from that
verified organization, not an organization ID in the request.

```http
POST /api/v1/job-sites
Idempotency-Key: unique-site-create-key
```

```json
{
  "name": "Kazipet project",
  "address": "Kazipet Junction, Telangana, India",
  "country_code": "IN",
  "notes": "Confirm the site entrance with the supervisor."
}
```

Name/address are required; coordinates/country/notes are optional.
These sites are shared across devices **only after the UI uses backend APIs
instead of browser local storage**. Existing browser records are not migrated
automatically. Review each import into the selected company.

Job sites do not require local business registration, although plants/brands do.
See [job-site API](./JOB_SITES_API.md).

## 11. Verify the first operational flow

1. Company user logs in and selects the intended organization.
2. Brand/plant lists contain only that company's owned records.
3. Saved job sites come from the backend.
4. Analyse a plant/brand for the destination; select country/region when needed.
5. Dispatch a pending trip and begin with an explicit timezone-qualified batch time.
6. Verify GPS updates, trip details/events, and authenticated SSE.
7. Complete/cancel through the supported workflow.
8. Check a second company's account cannot access the first company's data.

International predictions are still planning estimates based on existing
calibration assumptions. The presence of a city/timezone does not establish
locally validated concrete or congestion rules.

## 12. Troubleshooting

| Symptom | First check |
|---|---|
| 503 Authentication is not configured | Three Clerk verification settings; restart FastAPI; confirm frontend targets this backend |
| 401 Invalid/expired token | Current session token, matching issuer, authorized frontend origin |
| Owner controls missing | Signed-in user ID matches `SUPER_ADMIN_USER_ID`; refresh capabilities |
| 403 Active company required | Select a supported active organization for operations/job sites |
| Empty plant list | Plant and brand both belong to that company; seed records may be unowned |
| Missing country/state/city options | Geography list starts empty; owner creates verified records |
| Site visible only on one device | UI still uses browser storage, not job-site API |
| 409 Version conflict | Reload record and resolve edits; do not overwrite blindly |
| Duplicate POST after timeout | Reuse the original idempotency key for the same intended create |

## 13. Where to look next

| Need | Document |
|---|---|
| Start-to-finish setup | This guide |
| Overall app architecture and all database columns | [Engineering handover](./HANDOVER.md) |
| Tokens and permissions | [Authentication](./AUTHENTICATION.md) |
| Business/brand/plant payloads and legacy adoption | [Catalogue API](./CATALOGUE_API.md) |
| Geographic dropdown contracts | [Geography API](./GEOGRAPHY_API.md) |
| Shared saved destinations | [Job-site API](./JOB_SITES_API.md) |
| Routing and operational API details | [API reference](./API.md) |
| Deployment guidance | [GCP deployment](./GCP_DEPLOYMENT.md) |
| Outstanding functionality risks | [Remediation tracker](../review-doc.md) |

All 12 changed test modules passed together (203 tests); ownership/geography
fixtures now use the current contract. The full repository suite and production
UI integration were not verified. Job sites passed the earlier isolated HTTP
smoke checks. These checks are not a production release approval.
