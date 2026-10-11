"""Main FastAPI application"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.config import settings
from app.db import Base, engine, migrate_auth_schema
from app.db.catalogue_migration import migrate_catalogue
from app.db.business_migration import migrate_business_schema
from app.db.geography_migration import migrate_geography
from app.services.google_maps import GoogleMapsService
from app.services.traffic_monitor import start_traffic_monitor, stop_traffic_monitor
from app.dependencies import get_google_maps_client, get_load_manager, get_alert_service
from app.observability import RequestLoggingMiddleware, configure_logging

# ── Logging setup ──────────────────────────────────────────────────────────
configure_logging(settings.log_level, production=settings.env.lower() == "production")

logger = logging.getLogger(__name__)


# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager"""
    # Startup
    logger.info("Starting RMC Delivery Route Optimizer API")
    # Create existing operational tables and run the versioned catalogue import.
    try:
        migrate_geography(engine)
        Base.metadata.create_all(bind=engine)
        migrate_business_schema(engine)
        migrate_catalogue(engine)
        migrate_auth_schema(engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.exception("Database initialization failed")
        raise

    # Start background traffic monitor for active trips
    try:
        gmaps_service = await get_google_maps_client()
        load_mgr = get_load_manager()
        alert_svc = get_alert_service()
        await start_traffic_monitor(gmaps_service, load_mgr, alert_svc)
        logger.info("Background traffic monitor started (with RMC load tracking)")
    except Exception as e:
        logger.exception("Traffic monitor startup failed")

    yield

    # Shutdown
    logger.info("Shutting down RMC Delivery Route Optimizer API")
    await stop_traffic_monitor()
    logger.info("Background traffic monitor stopped")
    gmaps_service = await get_google_maps_client()
    if gmaps_service:
        await gmaps_service.close()
        logger.info("Google Maps service closed successfully.")


# Create FastAPI application
app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    lifespan=lifespan,
    debug=settings.debug,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(RequestLoggingMiddleware, slow_request_ms=settings.slow_request_ms)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": settings.api_title,
        "version": settings.api_version,
    }


# Include API routes
app.include_router(api_router, prefix=settings.api_v1_prefix)


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "title": settings.api_title,
        "version": settings.api_version,
        "docs": f"{settings.api_v1_prefix}/docs",
        "status": "running",
    }


# Error handlers
@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions"""
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers={"X-Request-ID": request.state.request_id},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        log_config=None,
    )
