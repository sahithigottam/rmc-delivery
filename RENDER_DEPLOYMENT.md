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

Transfer a consistent backup of the existing database to the persistent disk
before first application startup if retaining local business/catalogue/history
data. Code deployment alone does not transfer it. Keep independent backups.
The existing `render.yaml` is an older ephemeral-storage example; do not use it
as a durable SQLite production configuration without updating it.
