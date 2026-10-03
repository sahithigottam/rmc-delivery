# RMC Delivery Routing Microservice

A standalone FastAPI microservice for route calculation and optimization with truck-specific constraints.

## Features

- **Route Planning**: Calculate optimal routes from origin to destination with real-time traffic
- **Truck Constraints**: Handles vehicle type, load weight/volume, delivery time limits
- **Traffic-Aware**: Uses Google Maps API with predictive traffic models (pessimistic/best_guess/optimistic)
- **Rerouting**: Check and suggest alternative routes based on current traffic conditions
- **Caching**: 5-minute cache for routes, 24-hour cache for geocoding to minimize API calls
- **Alternative Routes**: Support for alternative route options with summaries

## Quick Start

### Local Development

1. **Clone and setup**:
   ```bash
   cd rmc-delivery-routing-service
   python -m venv venv
   source venv/Scripts/activate  # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your Google Maps API key
   ```

3. **Run**:
   ```bash
   python main.py
   ```

4. **Access**:
   - API: http://localhost:8000
   - Docs: http://localhost:8000/docs
   - Health: http://localhost:8000/health

## API Endpoints

### POST /api/v1/routes/estimate
Calculate a new route with traffic data.

**Example Request**:
```json
{
  "start": {"address": "Queen Street, Auckland"},
  "end": {"address": "Hamilton City"},
  "vehicle_type": "rmc_truck",
  "priority": "normal",
  "max_delivery_minutes": 90
}
```

**Response**: Full route with distance, duration, polyline, and steps.

### GET /api/v1/routes/{route_id}
Retrieve a previously calculated route.

### GET /api/v1/routes
Get route history with optional filters by vehicle_id.

### POST /api/v1/routes/reroute
Check if rerouting is recommended from current position.

**Example Request**:
```json
{
  "current_lat": -36.848,
  "current_lng": 174.762,
  "end": {"address": "Hamilton City"},
  "vehicle_type": "rmc_truck",
  "priority": "normal"
}
```

## Truck Constraints & Rules

The routing service respects the following truck-specific rules:

- **Vehicle Type**: Different routing for different vehicle types (rmc_truck, standard, etc.)
- **Load**: Considers load weight and volume in calculations
- **Delivery Time**: Validates that route completes within max_delivery_minutes
- **Traffic Model**: Maps priority (urgent/normal/economy) to traffic predictions
- **Avoid Options**: Can avoid tolls, highways, ferries based on request
- **Departure Time**: Accounts for traffic patterns at specific times

## Cloud Deployment (Railway)

### Deploy to Railway

1. **Push to GitHub**:
   ```bash
   git init
   git add .
   git commit -m "Initial routing microservice"
   git push origin main
   ```

2. **Create Railway project**:
   - Go to https://railway.app
   - Connect your GitHub repository
   - Create a new project

3. **Configure Environment**:
   - In Railway dashboard, set environment variables:
     - `GOOGLE_MAPS_API_KEY`: your Google Maps API key
     - `DATABASE_URL`: PostgreSQL connection string (Railway can provide this)

4. **Deploy**:
   - Railway automatically detects `Dockerfile` and deploys
   - Your routing service will be live at `https://your-app.railway.app`

### Update Frontend Backend URL

After deployment, update your main backend to call the cloud routing service:

```python
# In your main backend
ROUTING_SERVICE_URL = "https://your-app.railway.app"

async def calculate_route(route_request):
    # Call cloud routing service instead of local
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{ROUTING_SERVICE_URL}/api/v1/routes/estimate",
            json=route_request.dict()
        )
        return response.json()
```

## Environment Variables

- `DATABASE_URL`: SQLite (local) or PostgreSQL (cloud)
- `GOOGLE_MAPS_API_KEY`: Your Google Maps API key
- `LOG_LEVEL`: Logging level (INFO, DEBUG, ERROR)
- `API_TITLE`: API title for documentation
- `API_VERSION`: API version

## Architecture

```
main.py                  # FastAPI app entry point
├── config.py          # Settings from environment
├── database.py        # SQLAlchemy setup
├── models.py          # Route and TrafficSnapshot models
├── schemas.py         # Pydantic request/response models
├── google_maps.py     # Google Maps API wrapper with caching
├── route_service.py   # Route calculation business logic
└── api/
    └── routes.py      # REST endpoints
```

## Caching Strategy

- **Route responses**: 5-minute TTL (same route same time = cached)
- **Geocoding**: 24-hour TTL (addresses don't change)
- **Directions**: 10-minute TTL (traffic changes frequently)
- **Cache headers**: Use `coarse_start` for reroute checks to snap small truck movements to 1.1km grid

## Error Handling

- `400 Bad Request`: Invalid address or parameters
- `404 Not Found`: Route ID doesn't exist
- `500 Internal Server Error`: Google Maps API error or database issue

## Monitoring

- Check `/health` endpoint for service status
- View cache stats at `/stats/cache`
- Logs go to console with timestamps

## License

Copyright © 2026 RMC Delivery
