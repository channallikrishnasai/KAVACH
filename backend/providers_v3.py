"""Phase 3 provider contracts and local-first intelligence adapters.

All adapters make their data mode explicit. Demo inventory is intentionally
kept separate from cached/live source records.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ProviderStatus:
    name: str
    type: str
    status: str
    mode: str
    source: str
    lastUpdated: str | None
    freshness: str
    requiresAuth: bool
    configured: bool
    error: str | None
    capabilities: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProviderData:
    data: Any
    source: str
    mode: str
    retrievedAt: str
    freshness: str
    confidence: float
    provenance: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class CityDataProvider(ABC):
    name = "City provider"
    type = "CityDataProvider"
    source = ""
    requires_auth = False
    capabilities: tuple[str, ...] = ()

    @abstractmethod
    def fetch(self, query: dict[str, Any] | None = None) -> ProviderData:
        raise NotImplementedError

    def getCapabilities(self) -> list[str]:
        return list(self.capabilities)

    def getStatus(self) -> dict[str, Any]:
        return ProviderStatus(
            name=self.name,
            type=self.type,
            status="available",
            mode="UNAVAILABLE",
            source=self.source,
            lastUpdated=None,
            freshness="UNAVAILABLE",
            requiresAuth=self.requires_auth,
            configured=False,
            error=None,
            capabilities=self.getCapabilities(),
        ).as_dict()

    def healthCheck(self) -> dict[str, Any]:
        status = self.getStatus()
        return {"healthy": status["mode"] in {"LIVE", "CACHED", "SIMULATED"}, "provider": self.name, "mode": status["mode"], "error": status["error"]}

    # Snake-case aliases keep Python call sites idiomatic while satisfying the
    # documented cross-language provider contract names.
    def get_status(self) -> dict[str, Any]:
        return self.getStatus()

    def health_check(self) -> dict[str, Any]:
        return self.healthCheck()

    def get_capabilities(self) -> list[str]:
        return self.getCapabilities()


class DataGovProvider(CityDataProvider):
    name = "data.gov.in"
    type = "GovernmentDataProvider"
    source = "https://api.data.gov.in/resource/{resource_id}"
    requires_auth = True
    capabilities = ("resource_records", "query_filters", "pagination", "bounded_cache")
    ttl_seconds = 300
    max_pages = 3
    _last_request_at = 0.0
    _request_lock = threading.Lock()

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, ProviderData]] = {}
        self._last_error: str | None = None
        self._last_updated: str | None = None

    def _configuration(self) -> tuple[str, str]:
        return os.getenv("DATAGOV_API_KEY", "").strip(), os.getenv("DATAGOV_RESOURCE_ID", "").strip()

    def _valid_config(self) -> tuple[str, str] | None:
        key, resource_id = self._configuration()
        if not key or not re.fullmatch(r"[A-Za-z0-9-]{12,80}", resource_id):
            return None
        return key, resource_id

    def getStatus(self) -> dict[str, Any]:
        configured = self._valid_config() is not None
        mode = "CACHED" if self._cache else "UNAVAILABLE"
        return ProviderStatus(
            self.name, self.type, "configured" if configured else "NOT_CONFIGURED",
            mode, self.source, self._last_updated, "CACHED" if self._cache else "UNAVAILABLE", True,
            configured, self._last_error or (None if configured else "DATAGOV_API_KEY and DATAGOV_RESOURCE_ID are required"),
            self.getCapabilities(),
        ).as_dict()

    @staticmethod
    def _safe_query(query: dict[str, Any]) -> dict[str, str]:
        safe: dict[str, str] = {}
        for key, value in query.items():
            if key in {"limit", "offset", "q", "fields"}:
                safe[key] = str(value)
            elif re.fullmatch(r"(?:filters|sort)\[[A-Za-z0-9_ -]{1,80}\]", key):
                safe[key] = str(value)
            else:
                raise ValueError(f"Unsupported data.gov.in query parameter: {key}")
        return safe

    def fetch(self, query: dict[str, Any] | None = None) -> ProviderData:
        config = self._valid_config()
        if not config:
            return ProviderData([], self.source, "UNAVAILABLE", now_iso(), "UNAVAILABLE", 0.0, {"provider": self.name, "reason": "NOT_CONFIGURED"})
        api_key, resource_id = config
        try:
            params = self._safe_query(query or {})
        except ValueError as exc:
            self._last_error = str(exc)
            return ProviderData([], self.source.format(resource_id=resource_id), "UNAVAILABLE", now_iso(), "UNAVAILABLE", 0.0, {"provider": self.name, "error": "INVALID_QUERY", "detail": str(exc)})
        try:
            requested_limit = max(1, min(int(params.pop("limit", 100)), 1000))
            initial_offset = max(0, int(params.pop("offset", 0)))
        except (TypeError, ValueError):
            return ProviderData([], self.source.format(resource_id=resource_id), "UNAVAILABLE", now_iso(), "UNAVAILABLE", 0.0, {"provider": self.name, "error": "INVALID_PAGINATION"})
        cache_key = json.dumps({"resource": resource_id, "params": params, "limit": requested_limit, "offset": initial_offset}, sort_keys=True)
        cached = self._cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] < self.ttl_seconds:
            old = cached[1]
            return ProviderData(old.data, old.source, "CACHED", old.retrievedAt, "CACHED", old.confidence, {**old.provenance, "cache": "ttl"})
        with self._request_lock:
            now = time.monotonic()
            if now - self.__class__._last_request_at < 1.0:
                if cached:
                    old = cached[1]
                    return ProviderData(old.data, old.source, "CACHED", old.retrievedAt, "CACHED", 0.72, {**old.provenance, "fallback_reason": "RATE_LIMITED"})
                return ProviderData([], self.source.format(resource_id=resource_id), "UNAVAILABLE", now_iso(), "UNAVAILABLE", 0.0, {"provider": self.name, "error": "RATE_LIMITED"})
            self.__class__._last_request_at = now
        records: list[dict[str, Any]] = []
        reported_total: int | None = None
        try:
            for page in range(self.max_pages):
                offset = initial_offset + page * requested_limit
                request_params = {**params, "api-key": api_key, "format": "json", "limit": requested_limit, "offset": offset}
                url = f"https://api.data.gov.in/resource/{resource_id}?{urllib.parse.urlencode(request_params)}"
                request = urllib.request.Request(url, headers={"User-Agent": "KAVACH-local-demo/1.0", "Accept": "application/json"})
                with urllib.request.urlopen(request, timeout=6) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
                    raise ValueError("Malformed data.gov.in response: records must be an array")
                batch = payload["records"]
                records.extend(item for item in batch if isinstance(item, dict))
                try:
                    reported_total = int(payload.get("total")) if payload.get("total") is not None else reported_total
                except (TypeError, ValueError):
                    pass
                if len(batch) < requested_limit or (reported_total is not None and offset + len(batch) >= reported_total):
                    break
            result = ProviderData(
                {"resource_id": resource_id, "records": records, "total": reported_total, "pages_fetched": min(self.max_pages, max(1, (len(records) + requested_limit - 1) // requested_limit))},
                self.source.format(resource_id=resource_id), "LIVE", now_iso(), "LIVE", 0.9,
                {"provider": self.name, "endpoint": f"https://api.data.gov.in/resource/{resource_id}", "license": "Open Government Data License - India; verify each resource metadata", "query": params, "pagination": {"limit": requested_limit, "offset": initial_offset}},
            )
            self._cache[cache_key] = (time.monotonic(), result)
            self._last_error = None
            self._last_updated = result.retrievedAt
            return result
        except Exception as exc:
            self._last_error = type(exc).__name__
            if cached:
                old = cached[1]
                return ProviderData(old.data, old.source, "CACHED", old.retrievedAt, "CACHED", 0.65, {**old.provenance, "fallback_reason": type(exc).__name__})
            return ProviderData([], self.source.format(resource_id=resource_id), "UNAVAILABLE", now_iso(), "UNAVAILABLE", 0.0, {"provider": self.name, "endpoint": f"https://api.data.gov.in/resource/{resource_id}", "error": type(exc).__name__})


class BundledOSMProvider(CityDataProvider):
    name = "Bundled OSM KC Valley extract"
    type = "OSMProvider"
    source = "https://www.openstreetmap.org/copyright"
    capabilities = ("road_network", "city_geometry", "offline_routing")

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parent
        self.path = self.root / "kc_valley_area.osm"

    def getStatus(self) -> dict[str, Any]:
        exists = self.path.exists()
        updated = datetime.fromtimestamp(self.path.stat().st_mtime, timezone.utc).isoformat() if exists else None
        return ProviderStatus(self.name, self.type, "available" if exists else "unavailable", "CACHED" if exists else "UNAVAILABLE", str(self.path), updated, "CACHED" if exists else "UNAVAILABLE", False, exists, None if exists else "Bundled OSM extract is missing", self.getCapabilities()).as_dict()

    def fetch(self, query: dict[str, Any] | None = None) -> ProviderData:
        status = self.getStatus()
        if not status["configured"]:
            return ProviderData({}, self.source, "UNAVAILABLE", now_iso(), "UNAVAILABLE", 0.0, {"error": status["error"]})
        return ProviderData({"file": self.path.name, "extract_date": None, "scope": "KC Valley subset", "note": "Snapshot timestamp is unknown; not a live traffic source"}, self.source, "CACHED", status["lastUpdated"] or now_iso(), "CACHED", 0.8, {"license": "ODbL 1.0", "attribution": "© OpenStreetMap contributors", "path": str(self.path)})


class DemoInventoryProvider(CityDataProvider):
    mode_name = "SIMULATED"
    capabilities: tuple[str, ...] = ()

    def __init__(self, records: list[dict[str, Any]], name: str, provider_type: str, capabilities: tuple[str, ...]):
        self.records = records
        self.name = name
        self.type = provider_type
        self.capabilities = capabilities
        self.source = "KAVACH local demonstration inventory"

    def getStatus(self) -> dict[str, Any]:
        return ProviderStatus(self.name, self.type, "available", "SIMULATED", self.source, now_iso(), "SIMULATED", False, True, None, self.getCapabilities()).as_dict()

    def fetch(self, query: dict[str, Any] | None = None) -> ProviderData:
        rows = [dict(row) for row in self.records]
        for row in rows:
            row.setdefault("mode", "SIMULATED")
            row.setdefault("source", self.source)
            row.setdefault("timestamp", now_iso())
            if "ambulance" in self.type.casefold() or row.get("type") == "ambulance":
                row.setdefault("capability", "GENERAL")
                row.setdefault("availability", str(row.get("status", "unknown")).upper())
                row.setdefault("destination", None)
                row.setdefault("eta_minutes", None)
                row.setdefault("latitude", row.get("lat"))
                row.setdefault("longitude", row.get("lon"))
            if "hospital" in self.type.casefold() or "hospital" in row.get("id", ""):
                row.setdefault("emergency_capability", "UNVERIFIED_DEMO")
                row.setdefault("trauma_capability", "UNVERIFIED_DEMO")
                row.setdefault("icu_capability", "UNVERIFIED_DEMO")
                row.setdefault("capacityMode", "SIMULATED")
                row.setdefault("capabilityMode", "SIMULATED")
            if row.get("type") in {"fire_engine", "police_unit"}:
                row.setdefault("availability", str(row.get("status", "unknown")).upper())
                row.setdefault("jurisdiction", "UNVERIFIED_DEMO" if row.get("type") == "police_unit" else None)
        if query and query.get("type"):
            rows = [row for row in rows if row.get("type") == query["type"]]
        return ProviderData(rows, self.source, "SIMULATED", now_iso(), "SIMULATED", 0.5, {"provider": self.name, "capacity_mode": "SIMULATED", "availability_mode": "SIMULATED"})


class RoadDamageModelProvider(CityDataProvider):
    name = "Local ONNX road-damage model"
    type = "RoadDamageProvider"
    source = "local configured ONNX weights"
    capabilities = ("image_detection", "video_frame_detection", "bounding_boxes", "model_confidence")
    compatible_licenses = {"MIT", "MIT License", "Apache-2.0", "BSD-3-Clause", "BSD 3-Clause"}
    classes = ("alligator crack", "block crack", "crack", "edge damage", "longitudinal crack", "pothole", "transverse crack")

    def __init__(self) -> None:
        self._session: Any = None
        self._error: str | None = None
        self._input_name = "images"
        self._input_size = 640
        self._load()

    def _load(self) -> None:
        model_path = os.getenv("ROAD_DAMAGE_MODEL_PATH", "").strip()
        if not model_path or not Path(model_path).is_file():
            self._error = "NOT_CONFIGURED"
            return
        try:
            import onnxruntime as ort
            session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
            metadata = session.get_modelmeta().custom_metadata_map
            metadata_license = metadata.get("license", "").strip()
            configured_license = os.getenv("ROAD_DAMAGE_MODEL_LICENSE", "").strip()
            declared_license = metadata_license or configured_license
            if metadata_license and configured_license and metadata_license.casefold() != configured_license.casefold():
                self._error = "MODEL_LICENSE_METADATA_MISMATCH"
                return
            if not declared_license or not any(item.casefold() == declared_license.casefold() for item in self.compatible_licenses):
                self._error = "MODEL_LICENSE_UNVERIFIED_OR_INCOMPATIBLE"
                return
            inputs = session.get_inputs()
            if len(inputs) != 1 or len(inputs[0].shape) != 4 or inputs[0].shape[1] not in (3, None, "3"):
                self._error = "UNSUPPORTED_MODEL_INPUT"
                return
            self._input_name = inputs[0].name
            self._input_size = int(inputs[0].shape[2]) if isinstance(inputs[0].shape[2], int) else 640
            if metadata.get("names"):
                import ast
                try:
                    raw_names = ast.literal_eval(metadata["names"])
                    if isinstance(raw_names, dict):
                        self.classes = tuple(str(raw_names[key]) for key in sorted(raw_names, key=lambda value: int(value)))
                    elif isinstance(raw_names, (list, tuple)):
                        self.classes = tuple(str(name) for name in raw_names)
                except (ValueError, SyntaxError, TypeError):
                    self._error = "MODEL_CLASS_METADATA_INVALID"
                    return
            self._session = session
            self._error = None
        except Exception as exc:
            self._error = f"MODEL_LOAD_FAILED:{type(exc).__name__}"

    def getStatus(self) -> dict[str, Any]:
        ready = self._session is not None
        return ProviderStatus(self.name, self.type, "ready" if ready else ("unavailable" if self._error == "NOT_CONFIGURED" else "blocked"), "LIVE" if ready else "UNAVAILABLE", self.source, None, "LOCAL" if ready else "UNAVAILABLE", False, ready, self._error, self.getCapabilities()).as_dict()

    def infer(self, frame: Any) -> list[dict[str, Any]]:
        if self._session is None:
            return []
        import cv2
        import numpy as np

        height, width = frame.shape[:2]
        size = self._input_size
        scale = min(size / width, size / height)
        resized = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))))
        canvas = np.full((size, size, 3), 114, dtype=np.uint8)
        pad_x = (size - resized.shape[1]) // 2
        pad_y = (size - resized.shape[0]) // 2
        canvas[pad_y:pad_y + resized.shape[0], pad_x:pad_x + resized.shape[1]] = resized
        tensor = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype(np.float32).transpose(2, 0, 1)[None, ...] / 255.0
        output = self._session.run(None, {self._input_name: tensor})[0]
        rows = np.asarray(output).reshape(-1, np.asarray(output).shape[-1])
        results = []
        for row in rows:
            if len(row) < 6:
                continue
            x1, y1, x2, y2, confidence, class_index = (float(value) for value in row[:6])
            if not 0.0 <= confidence <= 1.0 or confidence < 0.25:
                continue
            bounds = [max(0, min(width, round((x1 - pad_x) / scale))), max(0, min(height, round((y1 - pad_y) / scale))), max(0, min(width, round((x2 - pad_x) / scale))), max(0, min(height, round((y2 - pad_y) / scale)))]
            if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                continue
            label = self.classes[int(class_index)] if 0 <= int(class_index) < len(self.classes) else "unknown"
            normalized = label.casefold().replace(" ", "_")
            damage_type = "POTHOLE" if "pothole" in normalized else "CRACK" if "crack" in normalized or normalized in {"d00", "d10", "d20"} or normalized in {"alligator", "longitudinal", "transverse", "block"} else "ROAD_SURFACE_DAMAGE" if normalized in {"edge", "deformation", "patch", "surface_damage"} else "OBSTRUCTION" if "obstruction" in normalized else "UNKNOWN"
            results.append({"damageType": damage_type, "confidence": round(confidence, 4), "boundingBox": bounds, "modelClass": label})
        return sorted(results, key=lambda item: item["confidence"], reverse=True)

    def fetch(self, query: dict[str, Any] | None = None) -> ProviderData:
        status = self.getStatus()
        if not status["configured"]:
            return ProviderData([], self.source, "UNAVAILABLE", now_iso(), "UNAVAILABLE", 0.0, {"provider": self.name, "error": self._error})
        frame = (query or {}).get("frame")
        if frame is None:
            return ProviderData([], self.source, "UNAVAILABLE", now_iso(), "UNAVAILABLE", 0.0, {"provider": self.name, "error": "IMAGE_REQUIRED"})
        detections = self.infer(frame)
        return ProviderData(detections, self.source, "LIVE", now_iso(), "LOCAL", max((d["confidence"] for d in detections), default=0.0), {"provider": self.name, "license": os.getenv("ROAD_DAMAGE_MODEL_LICENSE", "declared in ONNX metadata"), "inference": "ONNX Runtime CPU", "detections_are_model_outputs": True})


_road_damage_provider = RoadDamageModelProvider()


def get_road_damage_provider() -> RoadDamageModelProvider:
    return _road_damage_provider


def provider_status_rows() -> list[dict[str, Any]]:
    """Return provider health rows from Phase 3 contracts."""
    from providers import _data_gov_provider, _weather_provider, provider_catalog
    from email_service import email_provider_status

    weather = _weather_provider.fetch()
    w_mode = "LIVE" if weather.freshness == "LIVE" else "CACHED" if weather.freshness == "CACHED" else "SIMULATED"
    rows = provider_catalog()
    for row in rows:
        row.setdefault("mode", row.get("freshness", "UNAVAILABLE"))
        row.setdefault("lastUpdated", None)
        row.setdefault("error", row.get("reason"))
        row.setdefault("configured", row.get("status") in {"available", "configured"})
        row.setdefault("capabilities", [])
        row.setdefault("freshness", row["mode"])
    for row in rows:
        if row["name"] == "weather":
            row.update({"mode": w_mode, "freshness": weather.freshness, "lastUpdated": weather.retrievedAt, "error": weather.provenance.get("fallback_reason")})
        elif row["name"] == "government_open_data":
            details = _data_gov_provider.getStatus()
            row.update({key: value for key, value in details.items() if key != "name"})
            row["provider"] = details["name"]
        elif row["name"] == "city_geometry":
            details = BundledOSMProvider().getStatus()
            row.update({key: value for key, value in details.items() if key != "name"})
            row["provider"] = details["name"]
        elif row["name"] == "road_damage":
            details = get_road_damage_provider().getStatus()
            row.update({key: value for key, value in details.items() if key != "name"})
            row["provider"] = details["name"]
        elif row["name"] == "communications":
            email = email_provider_status()
            row.update({"provider": email["provider"], "mode": "LIVE" if email["status"] == "READY" else "UNAVAILABLE", "freshness": email["status"], "status": email["status"], "configured": email["configured"], "error": email["reason"], "capabilities": ["drafts", "approval", "smtp_send"]})
    gemini_configured = bool(os.getenv("GEMINI_API_KEY", "").strip())
    rows.append({"name": "gemini_agents", "type": "ai_advisory", "provider": "Google Gemini", "source": "Google Gemini API",
                 "lastUpdated": None, "mode": "LIVE" if gemini_configured else "LOCAL_FALLBACK",
                 "freshness": "CONFIGURED" if gemini_configured else "NOT_CONFIGURED", "status": "available" if gemini_configured else "NOT_CONFIGURED",
                 "configured": gemini_configured, "requiresAuth": True, "error": None if gemini_configured else "GEMINI_API_KEY is not set",
                 "capabilities": ["advisory_incident_analysis"], "actionsEnabled": False})
    return rows
