# Authentication and organization access

The API verifies Clerk session JWTs; it does not trust role values supplied by
the browser. Every `/api/v1` request requires an `Authorization: Bearer <token>`
header, a valid Clerk signature and issuer, and
an allowed `azp` (authorized party) origin.

Both legacy `org_id`/`org_role` session claims and current version-2 `o.id`/
`o.rol` claims are supported. Version-2 role names are normalized to their
`org:` slugs. User profile membership JSON is not accepted as authentication.

## Runtime configuration

Configure these server-side settings in the deployment environment:

| Setting | Purpose |
|---|---|
| `CLERK_JWKS_URL` | Clerk instance's public JWKS endpoint used to verify JWT signatures |
| `CLERK_ISSUER` | Exact issuer URL expected in session tokens |
| `CLERK_AUTHORIZED_PARTIES` | Comma-separated allowed frontend origins, including scheme |
| `SUPER_ADMIN_USER_ID` | Semicolon-separated Clerk user IDs of platform admins; no company role grants this privilege |

These are verification identifiers/URLs, not the Clerk secret key. Never place
`SUPER_ADMIN_USER_ID` in client configuration. Do not log bearer tokens.
Authentication fails closed with `503` if verification settings are missing.

## Clerk role mapping

- **Platform Super Admin (owner):** a verified Clerk user ID listed in
  `SUPER_ADMIN_USER_ID`. Can register businesses, manage business-owned brands
  and plants, and maintain each business's private geography catalogue.
- **Company Admin:** `org:admin` grants company operational access only. It never
  grants platform privileges, catalogue editing, or cross-company administration.
- **Plant Admin:** a verified `org:plantadmin` in the active organization.
- **Driver:** a verified `org:driver` in the active organization.
  Both have the same operational access to that organization's trips/routes
  and business-owned plants for now; separate Driver permissions are deferred.
- **Member:** `org:member` retains the same operational access for compatibility
  with the initial rollout. Missing or unrecognized roles are rejected.

Custom organization roles may require Clerk's paid B2B add-on in production.
Creating them in development does not establish free production eligibility.

Company users need an active organization. The platform owner may use catalogue
and assignment administration without an active organization or membership in
each customer business. Trip, route, prediction, and analysis operations require
an active supported organization membership even for the owner, and remain scoped
to that active organization.
Cross-company catalogue administration is explicitly allowed only for the
owner, not via an unrestricted operational-data bypass.
Company users cannot view another company's assignments or operate its trips.
Never accept role or organization membership from client metadata or bodies.
If `SUPER_ADMIN_USER_ID` is empty, nobody receives platform privileges.

For multiple platform admins, keep the existing setting name:

```env
SUPER_ADMIN_USER_ID=user_first;user_second;user_third
```

Entries are trimmed, blank entries ignored, and IDs compared exactly.
A single ID remains supported. Restart FastAPI after configuration changes.
Every listed admin receives identical platform capabilities; the list is
server-only and is not returned by `/auth/me`.

## Business ownership and legacy plant adoption

Only the platform owner can register businesses and create/change their
catalogues. Every new brand requires a registered business organization ID.
Every new plant inherits exclusive ownership from its brand; company users
see only brands/plants belonging to their active organization.

The owner can adopt an unowned legacy plant below after its brand is assigned
to that business. This is no longer a many-company sharing operation:

```http
POST /api/v1/organizations/{organization_id}/plants
Authorization: Bearer <Clerk session token>
Content-Type: application/json

{"plant_id": "plant-id"}
```

List owned plants for a business (owner) or the active organization (company user):

```http
GET /api/v1/organizations/{organization_id}/plants
Authorization: Bearer <Clerk session token>
```

Remove a legacy, unowned assignment for reviewed cleanup:

```http
DELETE /api/v1/organizations/{organization_id}/plants/{plant_id}
Authorization: Bearer <Clerk session token>
```

Owned plants cannot be unassigned or transferred; DELETE returns `409`.
Deactivate with plant PATCH instead. Legacy conflicts must be explicitly
reviewed before adoption. Catalogue and adoption mutations are recorded in
`catalogue_events`, with the verified Clerk actor ID.

## Frontend contract

Call `GET /api/v1/auth/me` with the session token to obtain the verified
`user_id`, `organization_id`, `organization_role`, `is_platform_admin`, and
capabilities `can_manage_catalogue`, `can_manage_businesses`,
`can_manage_company_assignments` (legacy ownership adoption), and
`can_operate_trips`. Use these for navigation rather than assuming `org:admin`
means platform owner. The endpoint does not expose the environment setting.
For an owner without an active organization, `organization_id` and
`organization_role` are null and `can_operate_trips` is false. Geographic
dropdown, brand, and plant reads are business-scoped. Platform-admin screens
must filter geography lists by the business opened in Businesses, not blindly
use the active Clerk organization. Country/state creates require that business's
`organization_id`; city/region ownership is inherited from the selected parent.
Country detail/delete requires the business query parameter for platform admins.
Dispatch, analysis, trips, and job sites still use the active Clerk organization.

`can_manage_job_sites` follows active-company operational access. Saved job
sites are shared within that company and editable by all supported operational
roles for now. See [job-site contract](./JOB_SITES_API.md).

Create business organizations and manage membership in Clerk, then register
the local business with `POST /businesses`. Registration does not create or
verify the organization in Clerk. See [CATALOGUE_API.md](./CATALOGUE_API.md).

The web client should obtain the current session token from Clerk and attach it
as a Bearer token to API `fetch` calls. Do not send role, user ID, or
organization ID as authorization claims from client-controlled request data;
the API reads those from the verified token. Use an active organization
switcher before calling organization-scoped APIs.

For trip event streaming, use `fetch` with the Bearer header and parse the SSE
stream. Native `EventSource` cannot set an Authorization header; do not put
session tokens in query strings.

## Existing database rollout

The additive auth migration preserves existing routes and trips with
`organization_id = NULL`. It also adds soft-archive fields without deleting
records. Those legacy records are deliberately inaccessible
through tenant-scoped API queries until an operator performs a reviewed,
backed-up ownership assignment. Do not automatically assign old records to the
first organization or Super Admin. The trip DELETE endpoint archives eligible
terminal trips and keeps their rows and event history.

The API does not import or contact Clerk during startup. Apply and verify the
database migration against a backup/staging database before deploying it to an
existing operational database.
