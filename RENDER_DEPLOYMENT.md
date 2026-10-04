## Deploy RMC Backend to Render (2 minutes)

Your Python backend is ready on GitHub. Here's how to deploy it:

### Step 1: Go to Render
- Visit https://render.com
- Sign up or log in with GitHub

### Step 2: Create Web Service
- Click "+ New" → "Web Service"
- Select repository: `rmc-delivery`
- Branch: `dev-branch-2`
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Plan: Free
- Click "Create Web Service"

### Step 3: Wait & Copy URL
- Render will build and deploy (2-3 minutes)
- Once "Live", copy the URL (looks like `https://rmc-delivery-backend-xxxx.onrender.com`)
- Send URL to me, I'll update frontend

### Environment Variables (optional)
- GOOGLE_MAPS_API_KEY: (leave blank for now)
- LOG_LEVEL: INFO

That's it. App will be live.
