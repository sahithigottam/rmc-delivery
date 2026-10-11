# RMC Delivery Route Optimizer

**New to setup? Follow the [start-to-finish setup guide](docs/SETUP_GUIDE.md).**
It covers Clerk, backend configuration, first-business registration, plants,
locations, saved job sites, and troubleshooting in order.

Start with the [engineering handover](docs/HANDOVER.md) for the current product
scope, business permissions, architecture, complete database dictionary,
operating procedures, and known limitations. It supersedes older roadmap
statements below when describing implemented functionality.

A production-ready Python FastAPI backend for optimizing delivery routes for New Zealand RMC (Ready-Mix Concrete) trucks using real-time traffic data from Google Maps API.

## Features
- **Route Calculation (Feature 1)**: Calculate optimal routes with real-time traffic data
- **Multi-Stop Support**: Coming in Feature 3
- **Vehicle Constraints**: Coming in Feature 4
- **Dispatch Management**: Coming in Feature 6
- **Live Tracking**: Coming in enhancements

## Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL 14+
- Google Maps API Key
 
### run dev server

``` 
.\.venv\Scripts\activate 
uvicorn app.main:app --reload
```

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/rmc-delivery.git
cd rmc-delivery
```

2. **Create virtual environment**
```bash
python -m venv .venv
source .venv/Scripts/activate  # Windows
# or
source .venv/bin/activate  # macOS/Linux
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure API Credentials**

Copy the example credentials file and add your Google Maps API key:
```bash
cp config/credentials.example.json config/credentials.json
```

Edit `config/credentials.json` and replace with your actual credentials:
```json
{
  "google_maps": {
    "api_key": "YOUR_GOOGLE_MAPS_API_KEY_HERE"
  },
  "database": {
    "host": "localhost",
    "port": 5432,
    "username": "rmc_user",
    "password": "rmc_password",
    "database": "rmc_delivery"
  }
}
```

See [config/README.md](config/README.md) for detailed setup instructions.

5. **Initialize database**
```bash
alembic upgrade head  # When migrations are ready
# Or use SQLAlchemy auto-creation (currently enabled in main.py)
```

6. **Run the application**
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Visit http://localhost:8000/docs for interactive API documentation.

## Docker Setup

### Build and run with Docker Compose
```bash
docker-compose up --build
```

The API will be available at http://localhost:8000

## API Endpoints

### Structured catalogue

Plants, brands, and regions are stored in SQLite. Startup imports
`config/plants.json` once through a versioned catalogue migration, preserving
existing plant IDs. Back up the SQLite file before the first rollout; editing
the seed after import does not update the live catalogue.

See [Catalogue API contract](docs/CATALOGUE_API.md) for the new `/api/v1`
request/response shapes, pagination, version-checked PATCH, and idempotent POST.
Shared company delivery destinations use the [job-site API](docs/JOB_SITES_API.md),
not browser-only storage or the batching-plant catalogue.
All API requests require a verified Clerk session; company operations also
require an active organization.
Configure `CLERK_JWKS_URL`, `CLERK_ISSUER`, `CLERK_AUTHORIZED_PARTIES`, and the
server-only `SUPER_ADMIN_USER_ID` listing platform admins separated by semicolons.
Only those verified users can manage business-owned brands and plants across
companies. Register a business with its existing Clerk organization ID, then
create its brands and plants. Plant ownership is inherited from its brand and
cannot be shared or transferred to another business. Structured countries,
states, cities, and city-linked regions are private to each business and support
international operations. Platform-admin geography screens target the business
opened in Businesses; dispatch and trips still use the active Clerk organization.
Company roles `org:admin`, `org:plantadmin`, `org:driver`,
and `org:member` share organization-scoped operational access for now.
Company cross-organization write attempts return `403`; no company role
grants platform-owner access. See
[Authentication and organization access](docs/AUTHENTICATION.md). Back up and
test the additive ownership migration on staging before applying it to the
operational database.

### Health Check
```
GET /health
```

### Feature 1: Route Calculation
```
POST /api/v1/routes/estimate          # Calculate a route
GET /api/v1/routes/{route_id}         # Retrieve specific route
GET /api/v1/routes                    # Get route history
```

See [docs/API.md](docs/API.md) for detailed API documentation.

## Project Structure
```
rmc-delivery/
├── app/
│   ├── main.py                 # FastAPI application
│   ├── config.py              # Configuration management
│   ├── dependencies.py        # FastAPI dependencies
│   ├── api/
│   │   └── v1/
│   │       ├── __init__.py
│   │       └── endpoints/
│   │           └── routes.py  # Feature 1: Route endpoints
│   ├── db/
│   │   ├── database.py        # Database setup
│   │   └── models.py          # SQLAlchemy models
│   ├── models/                # Data models (Pydantic)
│   ├── schemas/               # Request/response schemas
│   ├── services/
│   │   ├── google_maps.py    # Google Maps API client
│   │   └── route.py          # Route calculation logic
│   └── utils/                 # Utility functions
├── tests/                      # Unit and integration tests
├── docs/                       # API documentation
├── requirements.txt            # Python dependencies
├── docker-compose.yml         # Docker composition
├── Dockerfile                 # Docker image
└── project.md                 # Project roadmap
```

## Development

### Run Tests
```bash
pytest tests/ -v --cov=app
```

### Code Quality
```bash
# Format code
black app/ tests/

# Sort imports
isort app/ tests/

# Lint
flake8 app/ tests/

# Type checking
mypy app/
```

### Environment Variables
Create `.env` file based on `.env.example` (optional - credentials.json is recommended):
```env
ENV=development
DATABASE_URL=postgresql://user:password@localhost:5432/rmc_delivery
GOOGLE_MAPS_API_KEY=your_api_key_here
LOG_LEVEL=INFO
DEBUG=true
```

**Recommended**: Use `config/credentials.json` instead for better credential management. See [config/README.md](config/README.md).

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| ENV | development | Environment (development/production) |
| DATABASE_URL | - | PostgreSQL connection string |
| GOOGLE_MAPS_API_KEY | - | Google Maps API key |
| LOG_LEVEL | INFO | Logging level |
| DEBUG | false | Debug mode |
| API_V1_PREFIX | /api/v1 | API version prefix |
| RATE_LIMIT_REQUESTS | 100 | Requests per window |
| RATE_LIMIT_WINDOW | 60 | Rate limit window in seconds |

## Deployment

### Production Checklist
- [ ] Set `ENV=production` and `DEBUG=false`
- [ ] Use strong database credentials
- [ ] Configure CORS origins
- [ ] Implement API authentication (JWT)
- [ ] Set up rate limiting
- [ ] Enable HTTPS
- [ ] Configure logging and monitoring
- [ ] Set up CI/CD pipeline
- [ ] Run security scan
- [ ] Load test

### Recommended Deployment
- **Platform**: GCP Cloud Run, AWS ECS, or Azure Container Instances
- **Database**: Managed PostgreSQL (Cloud SQL, RDS, or Azure Database)
- **Reverse Proxy**: Cloud Load Balancer or CloudFront

## Monitoring

- API health check: `GET /health`
- Operational logging: JSON stdout, generated `X-Request-ID`, slow/error request
  summaries and dependency diagnostics; see [Render logging](RENDER_DEPLOYMENT.md#low-volume-operational-logging).
- Database health: Connection pooling with health checks
- Google API monitoring: Quota tracking (coming in Feature 7)

## Milestones

- [x] Feature 1: Route Calculation with Google Traffic API
- [ ] Feature 2: Traffic-Aware Routing
- [ ] Feature 3: Multi-Stop Optimization (TSP)
- [ ] Feature 4: Vehicle Constraints
- [ ] Feature 5: Safety & Compliance
- [ ] Feature 6: Dispatch Management
- [ ] Feature 7: Monitoring & Alerts
- [ ] Feature 8: Admin Configuration

## Contributing

1. Create a feature branch
2. Make your changes
3. Run tests and linting
4. Submit a pull request

## License

MIT License - see LICENSE file for details

## Support

For issues and questions, please open a GitHub issue or contact the development team.

## Changelog

### v1.0.0 (2026-03-11)
- Initial release
- Feature 1: Route Calculation with Google Directions API
- Production-ready folder structure
- Docker support
- Basic API documentation
