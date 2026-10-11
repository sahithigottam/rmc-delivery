## Deploy RMC Backend to Render

Routing runs inside this backend and calls Google Maps directly. A separate
Railway routing service is not required. Follow [the setup guide](docs/SETUP_GUIDE.md)
for Clerk and business onboarding before deploying.

### Step 1: Go to Render
- Visit https://render.com
- Sign up or log in with GitHub

### Step 2: Create Web Service
- Click "+ New" → "Web Service"
- Select repository: `rmc-delivery`
- Branch: `dev-branch-2`
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`
- For durable local SQLite, choose a paid service and attach a persistent disk
  at `/var/data`. Free service local storage is ephemeral and is unsuitable for
  durable operational records or continuous background trip monitoring.
- Click "Create Web Service"

### Step 3: Wait & Copy URL
- Render will build and deploy (2-3 minutes)
- Once "Live", copy the URL (looks like `https://rmc-delivery-backend-xxxx.onrender.com`)
- Configure the frontend's backend URL and verify `/api/v1/auth/me` returns
  401 without a bearer token, then test with a valid Clerk session.

### Environment Variables
- `ENV=production`, `DEBUG=false`, `DB_ECHO=false`, `LOG_LEVEL=INFO`
- `DATABASE_URL=sqlite:////var/data/rmc_delivery.db` when the disk is attached
- `GOOGLE_MAPS_API_KEY`: your key with the required Maps APIs enabled
- `CLERK_ISSUER`, `CLERK_JWKS_URL`: the issuer and JWKS URL for your Clerk instance
- `CLERK_AUTHORIZED_PARTIES`: exact frontend origins, comma-separated
- `SUPER_ADMIN_USER_ID`: verified platform-owner user IDs, semicolon-separated
- Optional hosted LLM configuration: see [the handover](docs/HANDOVER.md).

### Low-volume operational logging

The backend writes one-line JSON to stdout, not application log files on disk.
Render captures this output with plan-dependent retention. Existing local log
files are not deleted automatically. `ENV=production` prevents DEBUG-level
application logging even if `LOG_LEVEL=DEBUG` is supplied.

Each HTTP response includes a generated `X-Request-ID`, also exposed through
CORS. Search that ID in Render logs when investigating a failure. Logs use
route templates, not query strings, request bodies or authorization headers.
Errors include exception types and stack locations, without exception messages,
source lines or local variables. Credential/URL redaction is defense in depth,
not a substitute for keeping sensitive input out of log messages.

Successful fast requests, GPS polls, cache activity and normal monitor cycles
are DEBUG-only. Requests taking at least `SLOW_REQUEST_MS=2000` (the default)
and HTTP errors are logged at WARNING/ERROR. SSE timing covers connection setup,
not the lifetime of the stream. Google Maps failures and slow responses include
operation/status/timing without API keys, addresses or coordinates. Slow monitor
cycles and cycle failures remain visible; important trip transitions remain INFO.

This is a logging foundation, not a metrics dashboard, distributed tracing or
alert delivery system. `/health` remains a basic liveness endpoint, not proof
that GPS, the database and background monitoring are healthy end to end.

Transfer a consistent backup of the existing database to the persistent disk
before first application startup if retaining local business/catalogue/history
data. Code deployment alone does not transfer it. Keep independent backups.
The existing `render.yaml` is an older ephemeral-storage example; do not use it
as a durable SQLite production configuration without updating it.
