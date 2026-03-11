# API Credentials Configuration

This directory contains configuration files for managing API credentials and secrets.

## Setup Instructions

### 1. Create credentials.json

Copy the example file and fill in your actual API keys:

```bash
cp credentials.example.json credentials.json
```

### 2. Update credentials.json

Edit `credentials.json` and replace the placeholder values with your actual credentials:

```json
{
  "google_maps": {
    "api_key": "YOUR_ACTUAL_GOOGLE_MAPS_API_KEY_HERE",
    "geocoding_enabled": true,
    "directions_enabled": true,
    "traffic_model": "best_guess"
  },
  "database": {
    "type": "sqlite",
    "path": "./rmc_delivery.db"
  }
}
```

#### Database Options

**SQLite (Development/Testing - Default):**
```json
"database": {
  "type": "sqlite",
  "path": "./rmc_delivery.db"
}
```

**PostgreSQL (Production):**
```json
"database": {
  "type": "postgresql",
  "host": "localhost",
  "port": 5432,
  "username": "rmc_user",
  "password": "rmc_password",
  "database": "rmc_delivery"
}
```

## Getting Google Maps API Key

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable the following APIs:
   - Maps JavaScript API
   - Directions API
   - Distance Matrix API
   - Geocoding API
4. Create an API key in Credentials section
5. Restrict the key to your application (optional but recommended)
6. Copy the API key and paste it into `config/credentials.json`

## Security Notes

⚠️ **IMPORTANT**: 

- `credentials.json` is **NOT** tracked by git (see `.gitignore`)
- Never commit `credentials.json` to version control
- Keep your API keys private and secure
- Use environment-specific credentials for development, staging, and production
- Rotate API keys regularly
- Use IP whitelisting for production API keys

## Usage in Application

The application automatically loads credentials in this order:

1. **credentials.json** (if exists) - Takes priority
2. **.env file** - Environment variables

```python
# Example: Credentials are automatically loaded in app/config.py
from app.config import settings

# Google Maps API key
api_key = settings.google_maps_api_key

# Database connection
db_url = settings.database_url
```

## Environment Variables Alternative

If you prefer not to use `credentials.json`, you can set environment variables instead:

```bash
export GOOGLE_MAPS_API_KEY=your_api_key_here
export DATABASE_URL=postgresql://user:password@localhost:5432/rmc_delivery
export ENV=production
```

## Credentials.json Structure

### Google Maps Configuration
- `api_key`: Your Google Maps API key
- `geocoding_enabled`: Enable geocoding (address to coordinates)
- `directions_enabled`: Enable directions (routing)
- `traffic_model`: "best_guess", "pessimistic", or "optimistic"

### Database Configuration
- `host`: Database server hostname
- `port`: Database port (default 5432 for PostgreSQL)
- `username`: Database user
- `password`: Database password
- `database`: Database name

## Testing Credentials

To verify your credentials are loaded correctly:

```python
from app.config import settings

# Print to verify (only in development!)
print(f"API Key loaded: {settings.google_maps_api_key[:10]}...")
print(f"Database URL: {settings.database_url}")
```

## Troubleshooting

### "Credentials file not found"
Make sure you've created `credentials.json` from `credentials.example.json`

### "Invalid JSON in credentials file"
Check that your JSON is valid using an online JSON validator

### "API key not configured"
Verify that you haven't left the placeholder text "YOUR_GOOGLE_MAPS_API_KEY_HERE"

