"""Google Maps API integration service for Routing Microservice"""
import hashlib
import logging
from typing import Dict, List, Optional, Tuple
import httpx
from cachetools import TTLCache
from config import settings

logger = logging.getLogger(__name__)

# Cache configuration
GEOCODE_CACHE_TTL = 86400  # 24 hours - addresses don't change often
GEOCODE_CACHE_SIZE = 1000  # Max number of cached addresses

DIRECTIONS_CACHE_TTL = 600  # 10 minutes —traffic doesn't change meaningfully in < 10 min
DIRECTIONS_CACHE_SIZE = 500  # Max number of cached routes


class GoogleMapsService:
    """Service for Google Maps API operations"""

    BASE_URL = "https://maps.googleapis.com/maps/api"

    def __init__(self, api_key: str = settings.GOOGLE_MAPS_API_KEY):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30.0)
        
        # Initialize caches
        self._geocode_cache: TTLCache = TTLCache(maxsize=GEOCODE_CACHE_SIZE, ttl=GEOCODE_CACHE_TTL)
        self._directions_cache: TTLCache = TTLCache(maxsize=DIRECTIONS_CACHE_SIZE, ttl=DIRECTIONS_CACHE_TTL)
        
        # Cache statistics
        self._cache_stats = {
            "geocode_hits": 0,
            "geocode_misses": 0,
            "directions_hits": 0,
            "directions_misses": 0,
        }

    def _get_directions_cache_key(
        self,
        start_lat: float,
        start_lng: float,
        end_lat: float,
        end_lng: float,
        departure_time: Optional[int] = None,
        alternatives: bool = False,
        avoid: Optional[List[str]] = None,
        waypoints: Optional[List[Tuple[float, float]]] = None,
        coarse_start: bool = False,
    ) -> str:
        """Generate a cache key for directions request"""
        if coarse_start:
            s_lat = round(start_lat, 2)
            s_lng = round(start_lng, 2)
        else:
            s_lat = start_lat
            s_lng = start_lng

        key_parts = [
            f"{s_lat:.5f}" if not coarse_start else f"{s_lat:.2f}",
            f"{s_lng:.5f}" if not coarse_start else f"{s_lng:.2f}",
            f"{end_lat:.5f}",
            f"{end_lng:.5f}",
        ]
        
        if departure_time:
            time_bucket = departure_time // 900 * 900
            key_parts.append(str(time_bucket))
        
        key_parts.append(f"alt:{alternatives}")
        
        if avoid:
            key_parts.append(f"avoid:{','.join(sorted(avoid))}")
        
        if waypoints:
            wp_str = "|".join([f"{lat:.5f},{lng:.5f}" for lat, lng in waypoints])
            key_parts.append(f"wp:{wp_str}")
        
        key_string = "|".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()

    def _get_geocode_cache_key(self, address: str) -> str:
        """Generate a cache key for geocode request"""
        normalized = address.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()

    def get_cache_stats(self) -> Dict:
        """Return cache statistics"""
        return {
            **self._cache_stats,
            "geocode_cache_size": len(self._geocode_cache),
            "directions_cache_size": len(self._directions_cache),
        }

    async def get_directions(
        self,
        start_lat: float,
        start_lng: float,
        end_lat: float,
        end_lng: float,
        departure_time: Optional[int] = None,
        traffic_model: str = "best_guess",
        alternatives: bool = False,
        avoid: Optional[List[str]] = None,
        waypoints: Optional[List[Tuple[float, float]]] = None,
        coarse_start: bool = False,
    ) -> Dict:
        """Get directions between two points using Google Directions API"""
        cache_key = self._get_directions_cache_key(
            start_lat, start_lng, end_lat, end_lng, departure_time,
            alternatives, avoid, waypoints, coarse_start=coarse_start
        )
        
        if cache_key in self._directions_cache:
            self._cache_stats["directions_hits"] += 1
            logger.info(f"Directions cache HIT")
            return self._directions_cache[cache_key]
        
        self._cache_stats["directions_misses"] += 1
        logger.info(f"Directions cache MISS")
        
        try:
            url = f"{self.BASE_URL}/directions/json"

            params = {
                "origin": f"{start_lat},{start_lng}",
                "destination": f"{end_lat},{end_lng}",
                "key": self.api_key,
                "mode": "driving",
            }

            if departure_time:
                params["departure_time"] = str(departure_time)
                params["traffic_model"] = traffic_model
            
            if alternatives:
                params["alternatives"] = "true"
            
            if avoid:
                valid_avoid = [a for a in avoid if a in ["tolls", "highways", "ferries"]]
                if valid_avoid:
                    params["avoid"] = "|".join(valid_avoid)
            
            if waypoints:
                wp_str = "|".join([f"{lat},{lng}" for lat, lng in waypoints])
                params["waypoints"] = wp_str

            response = await self.client.get(url, params=params)
            response.raise_for_status()
            result = response.json()
            
            self._directions_cache[cache_key] = result
            return result

        except httpx.HTTPError as e:
            logger.error(f"HTTP error calling Google Directions API: {e}")
            raise
        except Exception as e:
            logger.error(f"Error calling Google Directions API: {e}")
            raise

    async def geocode_address(self, address: str) -> dict:
        """Geocode an address to coordinates using Google Geocoding API"""
        cache_key = self._get_geocode_cache_key(address)
        
        if cache_key in self._geocode_cache:
            self._cache_stats["geocode_hits"] += 1
            logger.info(f"Geocode cache HIT for address: {address}")
            return self._geocode_cache[cache_key]
        
        self._cache_stats["geocode_misses"] += 1
        logger.info(f"Geocode cache MISS for address: {address}")
        
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
                logger.error(f"Geocoding failed for address: {address}")
                raise ValueError(f"Could not geocode address: {address}")

            result = data["results"][0]
            location = result["geometry"]["location"]
            formatted_address = result.get("formatted_address", address)

            geocode_result = {
                "latitude": location["lat"],
                "longitude": location["lng"],
                "formatted_address": formatted_address,
            }
            
            self._geocode_cache[cache_key] = geocode_result
            return geocode_result

        except Exception as e:
            logger.error(f"Error geocoding address '{address}': {e}")
            raise

    async def reverse_geocode(
        self, latitude: float, longitude: float
    ) -> str:
        """Reverse geocode coordinates to address"""
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
