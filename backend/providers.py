"""Typed provider results and live-to-cache-to-simulation adapters.

Providers never call an operational dispatch API. External reads have bounded
timeouts and expose source, retrieval time, confidence, freshness and URL.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from communications import communication_status
from providers_v3 import CityDataProvider, DataGovProvider, ProviderData, ProviderStatus, provider_status_rows


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProviderResult:
    source: str
    retrievedAt: str
    freshness: str
    confidence: float
    data: dict[str, Any]
    provenance: dict[str, str]
    mode: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["mode"] = self.mode or {"LIVE": "LIVE", "CACHED": "CACHED", "SIMULATED": "SIMULATED", "UNAVAILABLE": "UNAVAILABLE"}.get(self.freshness, "UNAVAILABLE")
        return result


class WeatherProvider(CityDataProvider):
    name = "Open-Meteo"
    type = "WeatherProvider"
    source = "https://api.open-meteo.com/v1/forecast"
    requires_auth = False
    capabilities = ("current_weather", "forecast", "precipitation", "wind")
    ttl_seconds = 60

    def __init__(self) -> None:
        self._cached: ProviderResult | None = None
        self._cached_at = 0.0
        self._lock = threading.Lock()
        self._last_error: str | None = None

    def getCapabilities(self) -> list[str]:
        return list(self.capabilities)

    def getStatus(self) -> dict[str, Any]:
        import time
        fresh = bool(self._cached and time.monotonic() - self._cached_at < self.ttl_seconds)
        return ProviderStatus(self.name, self.type, "configured", "CACHED" if fresh else "UNAVAILABLE", self.source, self._cached.retrievedAt if self._cached else None, "CACHED" if fresh else "UNAVAILABLE", False, True, self._last_error, self.getCapabilities()).as_dict()

    def fetch(self) -> ProviderResult:
        import time

        with self._lock:
            now = time.monotonic()
            if self._cached and now - self._cached_at < self.ttl_seconds:
                return ProviderResult(self._cached.source, self._cached.retrievedAt, "CACHED", 0.94, dict(self._cached.data), dict(self._cached.provenance))
            url = os.getenv(
                "WEATHER_API_URL",
                "https://api.open-meteo.com/v1/forecast?latitude=12.935&longitude=77.645&current=temperature_2m,relative_humidity_2m,precipitation,rain,wind_speed_10m&hourly=precipitation,rain,wind_speed_10m&forecast_days=3&timezone=Asia%2FKolkata",
            )
            try:
                with urllib.request.urlopen(url, timeout=4) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                current = payload.get("current", {})
                if not isinstance(payload, dict) or not isinstance(current, dict) or not any(key in current for key in ("temperature_2m", "precipitation", "rain", "wind_speed_10m")):
                    raise ValueError("Malformed Open-Meteo response")
                rain = max(float(current.get("rain", 0) or 0), float(current.get("precipitation", 0) or 0))
                data = {
                    "rain_mm": rain,
                    "intensity": round(max(min(rain / 50.0, 1.0), 0.05), 2),
                    "temperature_c": current.get("temperature_2m"),
                    "relative_humidity_percent": current.get("relative_humidity_2m"),
                    "wind_speed_kmh": current.get("wind_speed_10m"),
                    "hourly": payload.get("hourly", {}),
                }
                result = ProviderResult(self.name, utc_now(), "LIVE", 0.98, data, {"url": url, "provider": self.name, "license": "CC BY 4.0; free API is non-commercial"})
                self._cached = result
                self._cached_at = now
                self._last_error = None
                return result
            except Exception as exc:
                self._last_error = type(exc).__name__
                if self._cached:
                    return ProviderResult(self._cached.source, self._cached.retrievedAt, "CACHED", 0.72, dict(self._cached.data), {**self._cached.provenance, "fallback_reason": type(exc).__name__})
                return ProviderResult(self.name, utc_now(), "SIMULATED", 0.25, {"rain_mm": 0.0, "intensity": 0.05, "temperature_c": None, "relative_humidity_percent": None, "wind_speed_kmh": None, "hourly": {}}, {"url": url, "provider": "DETERMINISTIC_WEATHER_FALLBACK", "fallback_reason": type(exc).__name__})


_weather_provider = WeatherProvider()
_data_gov_provider = DataGovProvider()


def provider_catalog() -> list[dict[str, Any]]:
    key = os.getenv("DATAGOV_API_KEY", "").strip()
    resource_id = os.getenv("DATAGOV_RESOURCE_ID", "").strip()
    gov = _data_gov_provider.getStatus()
    communications = communication_status()
    return [
        {"name": "weather", "provider": "Open-Meteo", "type": "WeatherProvider", "source": "https://open-meteo.com/", "requiresAuth": False, "status": "configured", "license": "CC BY 4.0; free API non-commercial", "mode": "UNAVAILABLE", "freshness": "UNAVAILABLE", "configured": True, "capabilities": ["current_weather", "forecast", "precipitation"]},
        {"name": "city_geometry", "provider": "Bundled OSM extract", "type": "OSMProvider", "source": "https://www.openstreetmap.org/copyright", "requiresAuth": False, "status": "available", "freshness": "CACHED", "mode": "CACHED", "configured": True, "capabilities": ["road_network", "offline_routing", "geometry"], "license": "ODbL 1.0"},
        {"name": "terrain", "provider": "Mapzen Terrain Tiles on AWS", "type": "TerrainProvider", "source": "https://registry.opendata.aws/terrain-tiles/", "requiresAuth": False, "status": "configured", "freshness": "CACHED", "mode": "CACHED", "configured": True, "capabilities": ["terrain_mesh"]},
        {"name": "government_open_data", "provider": gov["name"], "type": gov["type"], "source": gov["source"], "requiresAuth": True, "status": gov["status"], "mode": gov["mode"], "freshness": gov["freshness"], "configured": gov["configured"], "error": gov["error"], "capabilities": gov["capabilities"]},
        {"name": "traffic", "provider": "Local graph and closure simulator", "type": "TrafficProvider", "source": "KAVACH deterministic scenario", "requiresAuth": False, "status": "available", "mode": "SIMULATED", "freshness": "SIMULATED", "configured": True, "capabilities": ["graph_route", "simulated_closure", "alternative_route"]},
        {"name": "hospitals", "provider": "KAVACH local demo inventory", "type": "HospitalProvider", "source": "local seeded demonstration data", "requiresAuth": False, "status": "available", "mode": "SIMULATED", "freshness": "SIMULATED", "configured": True, "capabilities": ["facility_lookup", "simulated_capacity"]},
        {"name": "ambulances", "provider": "KAVACH local demo inventory", "type": "AmbulanceProvider", "source": "local seeded demonstration data", "requiresAuth": False, "status": "available", "mode": "SIMULATED", "freshness": "SIMULATED", "configured": True, "capabilities": ["unit_lookup", "simulated_availability"]},
        {"name": "fire", "provider": "KAVACH local demo inventory", "type": "FireProvider", "source": "local seeded demonstration data", "requiresAuth": False, "status": "available", "mode": "SIMULATED", "freshness": "SIMULATED", "configured": True, "capabilities": ["station_lookup", "simulated_availability"]},
        {"name": "police", "provider": "KAVACH local demo inventory", "type": "PoliceProvider", "source": "local seeded demonstration data", "requiresAuth": False, "status": "available", "mode": "SIMULATED", "freshness": "SIMULATED", "configured": True, "capabilities": ["station_lookup", "jurisdiction_unverified"]},
        {"name": "road_damage", "provider": "Local ONNX road-damage model", "type": "RoadDamageProvider", "source": "local configured ONNX weights", "requiresAuth": False, "status": "unavailable", "mode": "UNAVAILABLE", "freshness": "UNAVAILABLE", "configured": False, "error": "No license-verified ONNX detector configured", "capabilities": ["image_detection", "video_frame_detection", "bounding_boxes", "model_confidence"]},
        {"name": "citizen_reports", "provider": "KAVACH local media submissions", "type": "CitizenReportProvider", "source": "local process memory", "requiresAuth": False, "status": "available", "freshness": "SIMULATED"},
        {"name": "simulation", "provider": "Deterministic KAVACH simulation", "type": "SimulationProvider", "source": "local KAVACH core", "requiresAuth": False, "status": "available", "freshness": "SIMULATED"},
        {"name": "communications", "provider": communications["provider"], "type": "CommunicationProvider", "source": communications["source"], "requiresAuth": False, "status": communications["status"], "external_delivery_enabled": communications["external_delivery_enabled"]},
        {"name": "voice", "provider": "Browser Web Speech API", "type": "BrowserVoiceProvider", "source": "browser and operating system", "requiresAuth": False, "status": "available", "freshness": "LOCAL"},
    ]


def provider_status() -> dict[str, Any]:
    weather = _weather_provider.fetch().as_dict()
    rows = provider_catalog()
    mode = weather.get("mode") or weather["freshness"]
    for row in rows:
        if row["name"] == "weather":
            row.update({"mode": mode, "freshness": weather["freshness"], "lastUpdated": weather["retrievedAt"], "error": weather["provenance"].get("fallback_reason"), "capabilities": ["current_weather", "forecast", "precipitation"]})
        row.setdefault("mode", "UNAVAILABLE")
        row.setdefault("lastUpdated", None)
        row.setdefault("error", row.get("reason"))
        row.setdefault("configured", row.get("status") in {"available", "configured"})
        row.setdefault("capabilities", [])
    return {"providers": rows, "weather": weather, "generatedAt": utc_now()}


def fetch_government_resource(query: dict[str, Any] | None = None) -> ProviderResult:
    """Compatibility wrapper for the hardened queryable government adapter."""
    result = _data_gov_provider.fetch(query)
    data = result.data if isinstance(result.data, dict) else {"records": result.data}
    return ProviderResult(result.source, result.retrievedAt, result.freshness, result.confidence, data, {str(key): str(value) for key, value in result.provenance.items()}, mode=result.mode)
