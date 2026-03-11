"""Google Maps API integration service"""
import logging
from typing import Dict, List, Optional, Tuple

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class GoogleMapsService:
    """Service for Google Maps API operations"""

    BASE_URL = "https://maps.googleapis.com/maps/api"

    def __init__(self, api_key: str = settings.google_maps_api_key):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30.0)

    async def get_directions(
        self,
        start_lat: float,
        start_lng: float,
        end_lat: float,
        end_lng: float,
        departure_time: Optional[int] = None,
        traffic_model: str = "best_guess",
    ) -> Dict:
        """
        Get directions between two points using Google Directions API.

        Args:
            start_lat, start_lng: Starting point coordinates
            end_lat, end_lng: Ending point coordinates
            departure_time: Unix timestamp for traffic calculation
            traffic_model: "best_guess", "pessimistic", or "optimistic"

        Returns:
            Dictionary with route data including distance, duration, and steps
        """
        try:
            url = f"{self.BASE_URL}/directions/json"

            params = {
                "origin": f"{start_lat},{start_lng}",
                "destination": f"{end_lat},{end_lng}",
                "key": self.api_key,
                "mode": "driving",
            }

            if departure_time:
                params["departure_time"] = departure_time
                params["traffic_model"] = traffic_model

            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()

        except httpx.HTTPError as e:
            logger.error(f"HTTP error calling Google Directions API: {e}")
            raise
        except Exception as e:
            logger.error(f"Error calling Google Directions API: {e}")
            raise

    async def geocode_address(self, address: str) -> dict:
        """
        Geocode an address to coordinates using Google Geocoding API.

        Args:
            address: Street address or location name

        Returns:
            Dictionary with latitude, longitude, and formatted address
        """
        try:
            url = f"{self.BASE_URL}/geocode/json"

            params = {
                "address": address,
                "key": self.api_key,
                "components": "country:NZ",  # Restrict to New Zealand
            }

            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("status") != "OK" or not data.get("results"):
                raise ValueError(f"Could not geocode address: {address}")

            result = data["results"][0]
            location = result["geometry"]["location"]
            formatted_address = result.get("formatted_address", address)

            return {
                "latitude": location["lat"],
                "longitude": location["lng"],
                "formatted_address": formatted_address,
            }

        except Exception as e:
            logger.error(f"Error geocoding address '{address}': {e}")
            raise

    async def reverse_geocode(
        self, latitude: float, longitude: float
    ) -> str:
        """
        Reverse geocode coordinates to address.

        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate

        Returns:
            Formatted address string
        """
        try:
            url = f"{self.BASE_URL}/geocode/json"

            params = {
                "latlng": f"{latitude},{longitude}",
                "key": self.api_key,
            }

            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("status") != "OK" or not data.get("results"):
                return f"{latitude}, {longitude}"

            return data["results"][0].get("formatted_address", f"{latitude}, {longitude}")

        except Exception as e:
            logger.error(f"Error reverse geocoding coordinates: {e}")
            return f"{latitude}, {longitude}"
        """
        Get distance matrix between multiple origins and destinations.

        Args:
            origins: List of (lat, lng) tuples
            destinations: List of (lat, lng) tuples
            departure_time: Unix timestamp for traffic calculation

        Returns:
            Dictionary with distance and duration data
        """
        try:
            url = f"{self.BASE_URL}/distancematrix/json"

            origins_str = "|".join([f"{lat},{lng}" for lat, lng in origins])
            destinations_str = "|".join(
                [f"{lat},{lng}" for lat, lng in destinations]
            )

            params = {
                "origins": origins_str,
                "destinations": destinations_str,
                "key": self.api_key,
                "mode": "driving",
            }

            if departure_time:
                params["departure_time"] = departure_time

            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()

        except httpx.HTTPError as e:
            logger.error(f"HTTP error calling Distance Matrix API: {e}")
            raise
        except Exception as e:
            logger.error(f"Error calling Distance Matrix API: {e}")
            raise

    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()

    def __del__(self):
        """Cleanup on object deletion"""
        try:
            import asyncio

            asyncio.run(self.close())
        except:
            pass
