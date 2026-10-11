# Company job sites

Job sites are saved delivery destinations, not batching plants. They are now
stored in the backend and shared by users of the same active Clerk organization.
The browser address book is not automatically imported.

## Permissions

Every endpoint requires a Clerk bearer token and supported active organization.
Company admin, plant admin, driver, and member roles have the same access for
this rollout. Ownership is derived from the token, never a request field.
Even the platform owner uses active-company scope for these operational records.
`GET /auth/me` returns `can_manage_job_sites` for UI navigation.
Listing shows only that company's entries; accessing another company's ID returns
403. No local business registration is needed for this address book.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/job-sites` | Company list; `active_only=true`, `limit=50`, `offset=0` |
| GET | `/api/v1/job-sites/{id}` | Detail, including inactive records |
| POST | `/api/v1/job-sites` | Create; requires `Idempotency-Key` |
| PATCH | `/api/v1/job-sites/{id}` | Versioned edit or deactivation |

Lists return `items`, `total`, `limit`, `offset`; maximum limit is 100.
There is no hard-delete endpoint.

Create example:

```json
{
  "name": "Kazipet project",
  "address": "Kazipet Junction, Telangana, India",
  "country_code": "IN",
  "location": {"latitude": 17.98, "longitude": 79.51},
  "notes": "Use the site entrance agreed with the supervisor."
}
```

Only name and address are required. Country is an assigned uppercase ISO code;
location is optional and must supply both valid coordinates. Country and location
are destination information, not authorization evidence. Unknown fields,
including client organization/user IDs, are rejected.

Responses include immutable `id`, `organization_id`, name/address/location,
country/notes, `active`, `version`, actor IDs, and UTC creation/update timestamps.
Creation defaults to active. Matching retries return the original create response;
key reuse for a different company or body returns 409.

Edit/deactivate examples:

```json
{"version": 1, "name": "Renamed project", "notes": "Updated access instructions"}
```

```json
{"version": 2, "active": false}
```

Location, country, and notes may be cleared with null. Name, address, and active
cannot be cleared. Empty PATCH is rejected. Stale versions return 409 with
`detail.details.current_version`; reload before retrying.

## UI migration

1. Replace local-storage reads/writes with these endpoints.
2. Clear cached site lists and selections on Clerk organization changes.
3. Do not automatically import browser entries: old storage has no trustworthy
   company ownership. Offer explicit review/import into the selected company.
4. Reuse a create retry key for the same operation; use a new key per intended site.
5. Store returned IDs/versions and handle 401, 403, and 409 explicitly.
6. Select a saved site and pass its address/location as appropriate to existing
   dispatch/prediction forms. This change does not add a `job_site_id` relationship
   to trips or rewrite historical destinations.

Startup `create_all` creates the new `job_sites` table. No browser records or
operational database rows were imported during implementation. Writes persist
actor-attributed events in `catalogue_events` in the same transaction.
