"""RMC Delivery Routing Microservice - Cloud Edition"""
import logging
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session

from config import settings
from database import engine, Base, get_db
from api.routes import router as routes_router

# Setup logging
logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifecycle - create tables on startup"""
    logger.info("Routing Microservice starting up...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified")
    yield
    logger.info("Routing Microservice shutting down...")


app = FastAPI(
    title=settings.API_TITLE,
    description="RMC Delivery Routing Microservice - Handles route calculation with truck constraints",
    version=settings.API_VERSION,
    lifespan=lifespan,
)


@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "RMC Routing Microservice",
        "version": settings.API_VERSION,
    }


@app.get("/")
def root():
    """Root endpoint with API info"""
    return {
        "service": "RMC Delivery Routing Microservice",
        "version": settings.API_VERSION,
        "docs": "/docs",
        "health": "/health",
    }


# Include routes
app.include_router(routes_router, prefix=settings.API_V1_PREFIX)


@app.exception_handler(Exception)
async def universal_exception_handler(request, exc):
    """Handle all uncaught exceptions"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


if __name__ == "__main__":
    import uvicorn
    
    # Get port from environment or default to 8000
    import os
    port = int(os.getenv("PORT", 8000))
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )
