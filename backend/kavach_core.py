"""Deterministic, auditable KAVACH command loop for offline development/demo."""
from __future__ import annotations

import asyncio
import json
import math
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

import networkx as nx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from communications import communication_status, send_approved_event
from voice import parse_voice_command
from providers_v3 import DemoInventoryProvider, get_road_damage_provider
from road_ai import derive_damage_severity
from auth import auth_status
from email_service import configured_recipient, email_provider_status, send_configured_email
from gemini_agents import analyze_incident as analyze_with_gemini

kavach_router = APIRouter(tags=["KAVACH Command"])
_lock = asyncio.Lock()

AGENT_SPECS: list[dict[str, Any]] = [
    {"id": "observer", "name": "Observer", "responsibility": "Maintain city situational awareness", "tools": ["get_incidents", "get_city_state", "get_weather", "get_active_resources"]},
    {"id": "commander", "name": "Commander", "responsibility": "Coordinate findings and produce a gated response plan", "tools": ["decompose_incident", "merge_findings", "require_approval"]},
    {"id": "traffic", "name": "Traffic", "responsibility": "Assess road impacts and closures", "tools": ["get_road_state", "calculate_route", "simulate_road_closure"]},
    {"id": "medical", "name": "Medical", "responsibility": "Select an available demo hospital and medical resource", "tools": ["get_hospitals", "get_hospital_capacity", "get_ambulances"]},
    {"id": "fire", "name": "Fire", "responsibility": "Assess fire-service response needs", "tools": ["get_fire_resources", "calculate_fire_response_route"]},
    {"id": "police", "name": "Police", "responsibility": "Assess public safety and jurisdiction recommendation", "tools": ["get_police_resources", "get_incident_jurisdiction"]},
    {"id": "road_intelligence", "name": "Road Intelligence", "responsibility": "Review road-hazard reports and image-analysis availability", "tools": ["analyze_road_image", "get_road_hazards", "calculate_severity"]},
    {"id": "logistics", "name": "Logistics", "responsibility": "Recommend a demo response-unit allocation", "tools": ["get_resources", "allocate_resource", "calculate_resource_route"]},
    {"id": "routing", "name": "Routing", "responsibility": "Calculate and compare routes against current closures", "tools": ["route", "reroute", "compare_routes"]},
    {"id": "communications", "name": "Communications", "responsibility": "Prepare local-only authority/hospital messages", "tools": ["prepare_message", "create_work_order", "notify_authority"]},
]

DEMO_HOSPITALS = [
    {"id": "demo-hospital-1", "name": "Koramangala Medical Centre (demo)", "lat": 12.93433, "lon": 77.62288, "beds_available": 8, "status": "available"},
    {"id": "demo-hospital-2", "name": "St. John's Emergency Ward (demo)", "lat": 12.93059, "lon": 77.61862, "beds_available": 5, "status": "available"},
    {"id": "demo-hospital-3", "name": "Manipal Hospital (demo)", "lat": 12.91997, "lon": 77.66525, "beds_available": 11, "status": "available"},
]
DEMO_RESOURCES = [
    {"id": "demo-ambulance-1", "type": "ambulance", "name": "Ambulance A (demo)", "lat": 12.9411, "lon": 77.6214, "status": "available"},
    {"id": "demo-fire-1", "type": "fire_engine", "name": "Fire Engine A (demo)", "lat": 12.9168, "lon": 77.6739, "status": "available"},
    {"id": "demo-police-1", "type": "police_unit", "name": "Police Unit A (demo)", "lat": 12.9202, "lon": 77.6513, "status": "available"},
]

_state: dict[str, Any] = {}
_event_sequence = 0
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event(kind: str, summary: str, **extra: Any) -> dict[str, Any]:
    global _event_sequence
    _event_sequence += 1
    item = {"sequence": _event_sequence, "id": uuid.uuid4().hex[:12], "timestamp": _now(), "type": kind, "summary": summary, "data_state": "SIMULATED", **extra}
    _state["audit"].append(item)
    if len(_state["audit"]) > 1000:
        del _state["audit"][:-1000]
    return item


def _create_communication_drafts(incident: dict[str, Any], update: bool = False) -> list[dict[str, Any]]:
    kind = str(incident.get("incident_type", "")).casefold()
    if kind in {"collision", "accident", "medical_emergency"}:
        departments = [("POLICE", "Traffic and scene safety coordination"), ("HOSPITAL", "Possible casualties require awareness of simulated hospital routing")]
    elif kind in {"fire", "building_emergency"}:
        departments = [("FIRE", "Fire response coordination"), ("POLICE", "Perimeter and public safety coordination")]
    elif kind in {"road_hazard", "road_damage"}:
        departments = [("TRAFFIC", "Road hazard and corridor coordination"), ("MUNICIPAL", "Road maintenance review")]
    else:
        departments = [("POLICE", "Public safety coordination")]
    trace_id = incident.get("trace_id")
    existing = {draft.get("department") for draft in _state["communication_drafts"] if draft.get("incident_id") == incident["incident_id"] and draft.get("trace_id") == trace_id and draft.get("status") not in {"REJECTED", "FAILED"}}
    created = []
    plan = incident.get("route") or {}
    route_status = plan.get("status", "not calculated")
    route_distance = plan.get("distance_km")
    for department, reason in departments:
        if department in existing and not update:
            continue
        recipient = configured_recipient(department)
        subject_prefix = "KAVACH UPDATE" if update else "KAVACH ALERT"
        subject = f"{subject_prefix} — {incident['incident_type'].replace('_', ' ').title()} near {incident['location_name']}"
        body = "\n".join([
            "KAVACH INCIDENT UPDATE" if update else "KAVACH INCIDENT ALERT",
            "", f"Incident: {incident['incident_type'].replace('_', ' ').title()}",
            f"Location: {incident['location_name']}", f"Severity: {incident['severity'].upper()}",
            f"Reported: {incident['created_at']}", f"Summary: {incident.get('description', '')}",
            f"Recommended coordination: {reason}.",
            f"Current route: {route_status}" + (f" ({route_distance} km; heuristic estimate)" if route_distance is not None else ""),
            "Data mode: SIMULATED local KAVACH inventory and routing. This is not an operational dispatch.",
            "Status: awaiting explicit human approval.",
        ])
        stamp = _now()
        email_status = email_provider_status()
        draft = {"id": f"COM-{uuid.uuid4().hex[:10].upper()}", "incident_id": incident["incident_id"], "department": department, "recipient": recipient, "subject": subject, "body": body, "status": "AWAITING_APPROVAL", "created_at": stamp, "updated_at": stamp, "approved_at": None, "approved_by": None, "sent_at": None, "provider": email_status["provider"], "mode": "SIMULATED" if not email_status["enabled"] else "CONFIGURED", "reason": reason, "evidence_ids": [output.get("trace_id") for output in incident.get("agent_outputs", []) if output.get("trace_id")], "smtp_result": None, "trace_id": trace_id}
        _state["communication_drafts"].append(draft)
        _event("communication_draft_created", f"{department} email draft created for operator review", incident_id=incident["incident_id"], draft_id=draft["id"], department=department, recipient_configured=bool(recipient), mode=draft["mode"])
        created.append(draft)
    return created


def _transition(incident: dict[str, Any], status: str, reason: str) -> None:
    previous = incident["status"]
    incident["status"] = status
    incident["updated_at"] = _now()
    incident["transitions"].append({"from": previous, "to": status, "at": incident["updated_at"], "reason": reason})
    _event("state_transition", f"{incident['incident_id']}: {previous} → {status}", incident_id=incident["incident_id"], from_status=previous, to_status=status, reason=reason)
    phase_event = {"APPROVED": "approved", "EXECUTING": "action_started", "VERIFYING": "verification_started", "RESOLVED": "incident_resolved", "REPLANNING": "replan_started", "AWAITING_APPROVAL": "approval_requested", "FAILED": "verification_failed"}.get(status)
    if phase_event:
        _event(phase_event, f"{incident['incident_id']} entered {status}", incident_id=incident["incident_id"], from_status=previous)


def _incident(incident_id: str) -> dict[str, Any]:
    for item in _state["incidents"]:
        if item["incident_id"] == incident_id:
            return item
    raise HTTPException(status_code=404, detail="Incident not found")


def _route(start: tuple[float, float], end: tuple[float, float], blocked_nodes: set[Any], hazard_nodes: set[Any] | None = None) -> dict[str, Any]:
    """Use the bundled OSM road graph when available, excluding simulated closures."""
    try:
        import osmnx as ox
        from api import G

        origin = ox.distance.nearest_nodes(G, start[1], start[0])
        destination = ox.distance.nearest_nodes(G, end[1], end[0])
        if origin in blocked_nodes or destination in blocked_nodes:
            raise nx.NetworkXNoPath("route endpoint is blocked")
        graph = nx.subgraph_view(G, filter_node=lambda node: node not in blocked_nodes)
        nodes = nx.shortest_path(graph, origin, destination, weight="length")
        hazard_nodes = hazard_nodes or set()
        hazard_hits = [node for node in nodes if node in hazard_nodes]
        avoided_hazards = False
        if hazard_hits and origin not in hazard_nodes and destination not in hazard_nodes:
            safer_graph = nx.subgraph_view(graph, filter_node=lambda node: node not in hazard_nodes)
            try:
                alternative_nodes = nx.shortest_path(safer_graph, origin, destination, weight="length")
                original_cost = sum(float(min((edge.get("length", 1.0) for edge in (G.get_edge_data(u, v) or {}).values()), default=1.0)) for u, v in zip(nodes, nodes[1:]))
                alternative_cost = sum(float(min((edge.get("length", 1.0) for edge in (G.get_edge_data(u, v) or {}).values()), default=1.0)) for u, v in zip(alternative_nodes, alternative_nodes[1:]))
                if alternative_cost <= original_cost * 1.6:
                    nodes = alternative_nodes
                    avoided_hazards = True
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                pass
        remaining_hazard_hits = [node for node in nodes if node in hazard_nodes]
        distance_m = 0.0
        coordinates = []
        for node in nodes:
            coordinates.append([float(G.nodes[node]["x"]), float(G.nodes[node]["y"])])
        for u, v in zip(nodes, nodes[1:]):
            edges = G.get_edge_data(u, v) or G.get_edge_data(v, u) or {}
            distance_m += min((float(edge.get("length", 1.0)) for edge in edges.values()), default=1.0)
        return {"status": "calculated", "provider": "BUNDLED_OSM_NETWORKX", "data_state": "CACHED", "distance_km": round(distance_m / 1000, 2), "coordinates": coordinates, "nodes": nodes, "road_hazard_impact": {"matched_hazards": len(hazard_hits), "on_selected_route": bool(remaining_hazard_hits), "avoided": avoided_hazards, "risk_mode": "HUMAN_CONFIRMED_HAZARD" if remaining_hazard_hits else "NO_MATCHED_HAZARD_ON_SELECTED_ROUTE"}}
    except (ImportError, KeyError, nx.NetworkXNoPath, nx.NodeNotFound, ValueError):
        if blocked_nodes:
            return {"status": "no_path", "provider": "BUNDLED_OSM_NETWORKX", "data_state": "CACHED", "distance_km": None, "coordinates": [], "nodes": []}
        # A straight connector is only a labeled demo fallback, never a road route.
        return {"status": "straight_line_demo", "provider": "DEMO_FALLBACK", "data_state": "SIMULATED", "distance_km": None, "coordinates": [[start[1], start[0]], [end[1], end[0]]], "nodes": []}


def _estimate_minutes(distance_km: float | None) -> int | None:
    if distance_km is None:
        return None
    # Explicit demo heuristic, not measured travel time or a live traffic estimate.
    return max(1, math.ceil((distance_km / 22.0) * 60.0 + 2.0))


def _active_hazard_nodes(exclude_incident_id: str | None = None) -> set[Any]:
    hazards = {item["incident_id"]: item for item in _state["incidents"] if item.get("incident_type") in {"road_hazard", "road_damage"} and item.get("status") not in {"RESOLVED", "FAILED"} and item.get("incident_id") != exclude_incident_id}
    if not hazards:
        return set()
    try:
        import osmnx as ox
        from api import G
        return {ox.distance.nearest_nodes(G, item["lon"], item["lat"]) for item in hazards.values()}
    except Exception:
        return set()


def _available_route(incident: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    blocked = {b["node_id"] for b in _state["road_blocks"] if b.get("node_id") is not None and b["active"]}
    hazard_nodes = _active_hazard_nodes(incident.get("incident_id"))
    ambulance_provider = DemoInventoryProvider(_state["resources"], "KAVACH Ambulance Demo", "AmbulanceProvider", ("unit_lookup", "simulated_availability"))
    hospital_provider = DemoInventoryProvider(_state["hospitals"], "KAVACH Hospital Demo", "HospitalProvider", ("facility_lookup", "simulated_capacity"))
    resource_rows = ambulance_provider.fetch({"type": "ambulance"}).data
    hospital_rows = hospital_provider.fetch().data
    for hospital_item in hospital_rows:
        hospital_item.setdefault("capabilityMode", "SIMULATED")
        hospital_item.setdefault("capacityMode", "SIMULATED")
    resource = next((r for r in resource_rows if r["type"] == "ambulance" and r["status"] == "available"), None)
    origin = (incident["lat"], incident["lon"])
    resource_route = _route((resource["lat"], resource["lon"]), origin, blocked, hazard_nodes) if resource else {"status": "unavailable", "distance_km": None, "data_state": "SIMULATED", "provider": "DEMO_INVENTORY"}
    hospitals = [h for h in hospital_rows if h["status"] == "available" and h["beds_available"] > 0]
    candidates = []
    for hospital in hospitals:
        route = _route(origin, (hospital["lat"], hospital["lon"]), blocked, hazard_nodes)
        if route["status"] == "calculated":
            resource_distance = resource_route.get("distance_km") if resource_route.get("status") == "calculated" else None
            total_km = round(resource_distance + float(route.get("distance_km") or 0.0), 2) if resource_distance is not None else None
            candidate = {"hospital": hospital, "incident_to_hospital_route": route, "ambulance_to_incident_route": resource_route, "ambulance_id": resource["id"] if resource else None, "total_distance_km_estimate": total_km, "eta_minutes_estimate": _estimate_minutes(total_km), "travel_time_basis": "HEURISTIC_22_KMH_PLUS_2_MIN_SETUP_NO_LIVE_TRAFFIC" if total_km is not None else "UNAVAILABLE_NO_AMBULANCE_ROUTE", "capability_mode": hospital.get("capabilityMode", "SIMULATED"), "capacity_mode": hospital.get("capacityMode", "SIMULATED"), "ambulance_mode": resource.get("mode", "SIMULATED") if resource else "SIMULATED", "risk_assessment": "UNASSESSED_NO_LIVE_TRAFFIC_OR_HAZARD_FEED", "data_state": "SIMULATED"}
            candidates.append(candidate)
    if candidates:
        candidates.sort(key=lambda item: item["eta_minutes_estimate"] if item["eta_minutes_estimate"] is not None else item["incident_to_hospital_route"].get("distance_km", math.inf))
        best = candidates[0]
        return best["incident_to_hospital_route"], best["hospital"], candidates
    return _route(origin, (12.93433, 77.62288), blocked), None, []


def _nearest_resource_response(incident: dict[str, Any], resource_type: str) -> dict[str, Any] | None:
    blocked = {b["node_id"] for b in _state["road_blocks"] if b.get("node_id") is not None and b["active"]}
    hazard_nodes = _active_hazard_nodes(incident.get("incident_id"))
    options = []
    provider = DemoInventoryProvider(_state["resources"], f"KAVACH {resource_type} Demo", "EmergencyResourceProvider", ("unit_lookup", "simulated_availability"))
    for resource in provider.fetch({"type": resource_type}).data:
        if resource["type"] != resource_type or resource["status"] != "available":
            continue
        route = _route((resource["lat"], resource["lon"]), (incident["lat"], incident["lon"]), blocked, hazard_nodes)
        if route["status"] == "calculated":
            options.append((route["distance_km"], resource, route))
    if not options:
        return None
    distance, resource, route = min(options, key=lambda item: item[0])
    return {"resource": resource, "route": route, "distance_km_estimate": distance, "eta_minutes_estimate": _estimate_minutes(distance), "basis": "BUNDLED_OSM_DISTANCE_PLUS_22_KMH_HEURISTIC_NO_LIVE_TRAFFIC", "provider": provider.getStatus(), "data_state": "SIMULATED"}


def _base_agent_output(agent: dict[str, Any], incident: dict[str, Any], finding: str, evidence: list[str], confidence: float, recommendations: list[str], actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    now = _now()
    tool_by_agent = {
        "observer": ["get_city_state", "get_active_incidents", "get_resource_status"],
        "traffic": ["get_road_status", "calculate_route"],
        "medical": ["get_hospitals", "get_hospital_capacity", "get_ambulances"],
        "fire": ["get_fire_resources", "calculate_fire_response_route"],
        "police": ["get_police_resources", "assess_security", "calculate_route"],
        "road_intelligence": ["analyze_road_image"] if incident.get("image_analysis") else [],
        "logistics": ["get_available_resources"],
        "routing": ["calculate_emergency_route"],
        "communications": ["prepare_message"],
        "commander": ["merge_findings", "require_approval"],
    }
    trace_id = incident.get("active_trace_id", "")
    tools_used = tool_by_agent.get(agent["id"], [])
    return {
        "agent": agent["id"], "incident_id": incident["incident_id"], "status": "SUCCESS",
        "findings": [finding], "evidence": evidence, "recommendations": recommendations,
        "actions": actions or [], "confidence": confidence, "confidence_basis": "RULE_HEURISTIC", "requires_approval": True,
        "tools_used": tools_used, "available_tools": agent["tools"], "data_state": "SIMULATED", "created_at": now,
        "trace_id": trace_id, "startedAt": now, "completedAt": now, "durationMs": 0,
        "evidence_records": [{"tool": tools_used[min(index, len(tools_used) - 1)] if tools_used else "specialist_assessment", "source": "Bundled OpenStreetMap road graph" if "BUNDLED_OSM_NETWORKX" in item else "Configured local road-damage ONNX model" if "road_damage_model" in item else "KAVACH local demonstration inventory/state", "timestamp": now, "freshness": "CACHED" if "BUNDLED_OSM_NETWORKX" in item else "LIVE" if "road_damage_model" in item else "SIMULATED", "confidence": confidence, "result": item} for index, item in enumerate(evidence)],
    }


def _run_agent(agent: dict[str, Any], incident: dict[str, Any], route: dict[str, Any], hospital: dict[str, Any] | None) -> dict[str, Any]:
    ident = agent["id"]
    road_count = sum(1 for block in _state["road_blocks"] if block["active"])
    severity = incident["severity"]
    if ident == "observer":
        finding, evidence, confidence = f"City snapshot contains {len(_state['incidents'])} incident(s), {len(_state['road_blocks'])} road-block record(s), and {len(_state['resources'])} demo resources.", ["In-memory deterministic scenario snapshot"], 0.99
        recommendations = ["Investigate the active incident with the relevant specialists."]
    elif ident == "traffic":
        finding = f"Current road graph has {road_count} simulated closure(s); incident-to-facility route status is {route['status']}."
        evidence, confidence, recommendations = [f"Route provider: {route['provider']}", f"Active road closures: {road_count}"], (0.92 if route["status"] == "calculated" else 0.62), ["Keep emergency corridor open and recalculate after any closure."]
    elif ident == "medical":
        finding = f"{hospital['name']} is the selected demo facility; capability mode {hospital.get('capabilityMode', 'SIMULATED')}, capacity mode {hospital.get('capacityMode', 'SIMULATED')}." if hospital else "No demo hospital with available capacity can be reached on the current route graph."
        evidence = [f"Demo inventory: {hospital['beds_available']} simulated beds" if hospital else "No reachable facility in demo inventory"]
        confidence, recommendations = (0.82 if hospital else 0.45), (["Prepare a hospital notification for operator approval."] if hospital else ["Escalate to a human dispatcher; no facility recommendation is available."])
    elif ident == "fire":
        relevant = incident["incident_type"] in {"fire", "collision", "building_emergency"}
        response = incident.get("fire_response")
        finding = (f"Nearest available demo fire unit is {response['resource']['name']} with a {response['distance_km_estimate']} km graph route and estimated {response['eta_minutes_estimate']} minute response." if response else "No reachable available demo fire resource is recorded.") if relevant else "Fire response is not indicated by the incident type."
        evidence = ["Incident type and simulated fire-resource inventory", f"Road provider: {response['route']['provider']}" if response else "No fire-resource route found"]
        confidence, recommendations = (0.78 if relevant else 0.91), (["Stage the demo fire unit for operator review."] if relevant else ["Keep fire resources available for higher-priority events."])
    elif ident == "police":
        response = incident.get("police_response")
        finding = f"Public-safety coordination is recommended for the {severity} {incident['incident_type']} report in {incident['location_name']}. " + (f"Nearest demo police unit has an estimated {response['eta_minutes_estimate']} minute route." if response else "No reachable demo police unit is recorded.")
        evidence, confidence, recommendations = ["Incident fields supplied to the local demo; jurisdiction not verified", f"Bundled graph: {response['distance_km_estimate']} km" if response else "No police-unit route found"], 0.8, ["Prepare a local police coordination note; do not dispatch a real unit."]
    elif ident == "road_intelligence":
        image_analysis = incident.get("image_analysis")
        stored_analysis = _state.get("road_analyses", {}).get(image_analysis.get("analysis_id")) if image_analysis else None
        detections = (stored_analysis or {}).get("detections", [])
        if detections:
            detection = detections[0]
            finding = f"The configured road model detected {detection['damageType']} with raw model confidence {detection['confidence']:.2f}; review priority is {detection['severity']} ({detection['reason']})."
            evidence = [f"road_damage_model · {detection['damageType']} · model confidence {detection['confidence']}", f"Bounding box {detection['boundingBox']} frame {detection['frameIndex']}", f"OCR {stored_analysis.get('ocr', {}).get('provider') or 'unavailable'} confidence {stored_analysis.get('ocr', {}).get('confidence')}"]
            confidence = float(detection["confidence"])
            recommendations = ["Confirm the map location and inspect the original image before updating a route."]
        elif image_analysis:
            finding = "Uploaded road media was attached, but no compatible detector was available; local contrast cues are non-classifying and cannot confirm damage."
            evidence = [f"Road model mode: {stored_analysis.get('model_mode', 'UNAVAILABLE') if stored_analysis else 'UNAVAILABLE'}", f"Non-classifying visual cues: {image_analysis.get('surface_cue_count', 0)}", f"OCR confidence: {stored_analysis.get('ocr', {}).get('confidence') if stored_analysis else None}"]
            confidence, recommendations = 0.0, ["Request human visual confirmation; no model damage conclusion is available."]
        else:
            finding, evidence, confidence = "No road image detector has been run for this incident; this text incident has no image evidence.", ["No image attachment"], 0.99
            recommendations = ["Request photo/video evidence when road condition is relevant."]
    elif ident == "logistics":
        unit = next((r for r in _state["resources"] if r["type"] == "ambulance" and r["status"] == "available"), None)
        finding = f"Recommend {unit['name']} for the response." if unit else "No available demo ambulance is recorded."
        evidence = ["Local demo resource inventory"]
        confidence, recommendations = (0.77 if unit else 0.48), (["Reserve the unit after operator approval."] if unit else ["Escalate resource availability to a human operator."])
    elif ident == "routing":
        finding = f"Road-graph route is {route['status']}" + (f" ({route['distance_km']} km)." if route.get("distance_km") is not None else ".")
        evidence, confidence = [f"Route provider: {route['provider']}", f"Closure-aware: {road_count > 0}"], (0.9 if route["status"] == "calculated" else 0.5)
        recommendations = ["Review route on the city map before approval."]
    elif ident == "communications":
        finding = "A local-only authority and hospital message draft is ready; nothing has been sent."
        evidence, confidence, recommendations = ["Local notification provider (no external credentials configured)"], 0.99, ["Approve the response plan before any external notification integration is enabled."]
    else:
        finding = f"Commander merged {len(_state['agents'])} specialist outputs and requires explicit approval."
        evidence = ["Structured agent findings", f"Incident severity: {severity}", f"Route status: {route['status']}"]
        confidence, recommendations = 0.86, ["Review the plan, then approve or reject it."]
    started = time.perf_counter()
    output = _base_agent_output(agent, incident, finding, evidence, confidence, recommendations)
    output["durationMs"] = round((time.perf_counter() - started) * 1000, 3)
    output["startedAt"] = _now()
    output["completedAt"] = _now()
    if ident == "road_intelligence" and incident.get("image_analysis"):
        output["confidence_basis"] = "MODEL_CONFIDENCE" if incident["image_analysis"].get("model_mode") == "LIVE" else "NO_MODEL_CONFIDENCE"
        output["data_state"] = incident["image_analysis"].get("model_mode", "UNAVAILABLE")
    return output


def _run_all_agents(incident: dict[str, Any]) -> list[dict[str, Any]]:
    trace_id = uuid.uuid4().hex
    incident["active_trace_id"] = trace_id
    route, hospital, candidates = _available_route(incident)
    incident["fire_response"] = _nearest_resource_response(incident, "fire_engine")
    incident["police_response"] = _nearest_resource_response(incident, "police_unit")
    incident_kind = str(incident.get("incident_type", "")).casefold()
    all_ids = {agent["id"] for agent in AGENT_SPECS}
    if incident_kind in {"road_hazard", "road_damage"}:
        selected_ids = {"observer", "road_intelligence", "traffic", "routing", "logistics", "communications", "commander"}
    elif incident_kind in {"fire", "building_emergency"}:
        selected_ids = {"observer", "traffic", "medical", "fire", "police", "logistics", "routing", "communications", "commander"}
    else:
        # A major road collision may involve entrapment, obstruction and hospital
        # diversion, so the flagship scenario legitimately selects all ten.
        selected_ids = all_ids
    selected = [agent for agent in AGENT_SPECS if agent["id"] in selected_ids and agent["id"] != "commander"]
    for agent in selected:
        _event("agent_started", f"{agent['name']} started {incident_kind or 'incident'} assessment", incident_id=incident["incident_id"], trace_id=trace_id, agent=agent["id"])
    outputs = [_run_agent(agent, incident, route, hospital) for agent in selected]
    commander = next(agent for agent in AGENT_SPECS if agent["id"] == "commander")
    _event("agent_started", "Commander started specialist synthesis", incident_id=incident["incident_id"], trace_id=trace_id, agent="commander")
    outputs.append(_run_agent(commander, incident, route, hospital))
    _state["agents"] = {spec["id"]: {"agent": spec["id"], "status": "idle", "result_status": "SKIPPED_NOT_RELEVANT", "confidence": None, "last_run": None, "summary": "Not selected for this incident type."} for spec in AGENT_SPECS}
    _state["agents"].update({output["agent"]: {"agent": output["agent"], "status": "complete", "result_status": output["status"], "confidence": output["confidence"], "last_run": output["created_at"], "summary": output["findings"][0]} for output in outputs})
    for output in outputs:
        _event("agent_completed", f"{output['agent'].replace('_', ' ').title()} completed its assigned assessment", incident_id=incident["incident_id"], trace_id=trace_id, agent=output["agent"], tool=output["tools_used"][0] if output["tools_used"] else None, status=output["status"], confidence=output["confidence"], evidence_count=len(output["evidence_records"]))
    incident.pop("active_trace_id", None)
    incident["trace_id"] = trace_id
    incident["agent_outputs"] = outputs
    incident["route"] = route
    incident["route_candidates"] = [{key: value for key, value in candidate.items() if key != "incident_to_hospital_route" and key != "ambulance_to_incident_route"} | {"route": candidate["incident_to_hospital_route"], "ambulance_route": candidate["ambulance_to_incident_route"]} for candidate in candidates]
    incident["simulation"] = {"provider": "KAVACH_DETERMINISTIC_RESPONSE_SIMULATOR", "data_state": "SIMULATED", "selected_eta_minutes_estimate": candidates[0]["eta_minutes_estimate"] if candidates else None, "resource_utilization": {"available_demo_ambulances": sum(1 for item in _state["resources"] if item["type"] == "ambulance" and item["status"] == "available"), "allocated_by_plan": bool(candidates)}, "risk": "UNASSESSED_NO_LIVE_TRAFFIC_OR_HAZARD_FEED", "hospital_capacity_impact": "SIMULATED_INVENTORY_ONLY"}
    incident["recommended_hospital"] = hospital
    incident["local_notification_draft"] = {"status": "prepared_local_only", "sent": False, "message": f"{incident['severity'].upper()} {incident['incident_type']} reported at {incident['location_name']}. Operator review required."}
    _event("plan_created", "Commander created a deterministic response plan from selected specialists", incident_id=incident["incident_id"], trace_id=trace_id, selected_agents=[item["agent"] for item in outputs], data_state="SIMULATED")
    _event("simulation_started", "Response simulation used demo inventory and heuristic travel time", incident_id=incident["incident_id"], trace_id=trace_id)
    _create_communication_drafts(incident)
    return outputs


class IncidentInput(BaseModel):
    incident_type: str = Field(default="collision", min_length=2, max_length=40)
    severity: str = Field(default="high", pattern="^(low|moderate|high|critical)$")
    description: str = Field(default="Deterministic KAVACH demo incident", max_length=2000)
    location_name: str = Field(default="Koramangala, Bengaluru", max_length=120)
    lat: float = Field(default=12.935, ge=12.80, le=13.15)
    lon: float = Field(default=77.62, ge=77.40, le=77.85)
    location_source: Literal["GPS", "EXIF", "USER_SELECTED", "GEOCODED", "SIMULATED_STATIC_PLACE_MATCH", "SIMULATED"] = "SIMULATED"


class AgentRunInput(BaseModel):
    incident_id: str


class ActorInput(BaseModel):
    actor: str = Field(default="local_operator", min_length=1, max_length=80)
    role: Literal["ADMIN", "COMMANDER", "OPERATOR", "VIEWER"] = "OPERATOR"


class VoiceCommandInput(BaseModel):
    transcript: str = Field(min_length=1, max_length=1000)


class CommunicationInput(BaseModel):
    incident_id: str = Field(min_length=8, max_length=40)
    actor: str = Field(default="local_operator", min_length=1, max_length=80)
    role: Literal["ADMIN", "COMMANDER", "OPERATOR", "VIEWER"] = "OPERATOR"


class CommunicationEditInput(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=1, max_length=12000)
    actor: str = Field(default="demo_commander", min_length=1, max_length=80)
    role: Literal["ADMIN", "COMMANDER", "OPERATOR", "VIEWER"] = "COMMANDER"


class CommunicationActorInput(BaseModel):
    actor: str = Field(default="demo_commander", min_length=1, max_length=80)
    role: Literal["ADMIN", "COMMANDER", "OPERATOR", "VIEWER"] = "COMMANDER"


class CameraInput(BaseModel):
    camera_id: str = Field(min_length=3, max_length=40, pattern="^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=100)
    location_name: str = Field(min_length=2, max_length=120)
    lat: float = Field(ge=12.80, le=13.15)
    lon: float = Field(ge=77.40, le=77.85)


class CameraObservationInput(BaseModel):
    incident_type: str = Field(default="collision", min_length=2, max_length=40)
    severity: str = Field(default="high", pattern="^(low|moderate|high|critical)$")
    description: str = Field(min_length=3, max_length=1500)
    detection_type: str = Field(min_length=3, max_length=60)


class SimulationInput(BaseModel):
    event: str = Field(pattern="^(road_block|resource_failure|hospital_capacity|weather_change|new_incident)$")
    target_id: str | None = None
    value: float | None = None
    actor: str = Field(default="local_operator", min_length=1, max_length=80)
    role: Literal["ADMIN", "COMMANDER", "OPERATOR", "VIEWER"] = "OPERATOR"


class RoadIncidentInput(BaseModel):
    location_name: str = Field(min_length=2, max_length=120)
    lat: float | None = Field(default=None, ge=12.80, le=13.15)
    lon: float | None = Field(default=None, ge=77.40, le=77.85)
    severity: str = Field(default="moderate", pattern="^(low|moderate|high|critical)$")
    description: str = Field(default="Road hazard submitted for human review", max_length=2000)
    location_source: Literal["GPS", "EXIF", "USER_SELECTED", "GEOCODED", "SIMULATED_STATIC_PLACE_MATCH", "SIMULATED"] = "USER_SELECTED"


def reset_state() -> None:
    global _state
    _state = {
        "incidents": [], "road_blocks": [], "resources": [dict(item) for item in DEMO_RESOURCES],
        "hospitals": [dict(item) for item in DEMO_HOSPITALS], "agents": {item["id"]: {"agent": item["id"], "status": "idle", "confidence": None, "last_run": None, "summary": "Waiting for an incident."} for item in AGENT_SPECS},
        "audit": [], "road_analyses": {}, "communication_drafts": [], "cameras": [], "camera_evidence": {}, "scenario": "DEMO", "city": "Bengaluru · KC Valley map extent", "data_state": "SIMULATED",
    }


reset_state()


@kavach_router.get("/api/city/state")
async def city_state():
    return {"city": _state["city"], "data_state": _state["data_state"], "incidents": _state["incidents"], "road_blocks": _state["road_blocks"], "resources": _state["resources"], "hospitals": _state["hospitals"], "road_hazards": list(_state["road_analyses"].values()), "active_incidents": sum(item["status"] not in {"RESOLVED", "FAILED"} for item in _state["incidents"]), "critical_events": sum(item["severity"] == "critical" and item["status"] not in {"RESOLVED", "FAILED"} for item in _state["incidents"]), "agent_count": len(AGENT_SPECS), "audit_count": len(_state["audit"]), "camera_count": len(_state["cameras"]), "online_camera_count": sum(camera["status"] == "ONLINE" for camera in _state["cameras"]), "pending_approvals": sum(draft["status"] == "AWAITING_APPROVAL" for draft in _state["communication_drafts"]) + sum(item["status"] == "AWAITING_APPROVAL" for item in _state["incidents"])}


@kavach_router.get("/api/kavach/status")
async def kavach_status():
    return {"service": "KAVACH", "status": "ready", "data_state": "SIMULATED", "agent_count": len(AGENT_SPECS), "external_actions_enabled": False, "authentication": auth_status()}


@kavach_router.get("/api/auth/status")
async def get_auth_status():
    return auth_status()


@kavach_router.get("/api/voice/providers")
async def get_voice_provider_status():
    from voice import AssemblyAIVoiceProvider, BrowserVoiceProvider, GeminiLiveVoiceProvider, MockVoiceProvider
    gemini = GeminiLiveVoiceProvider().getStatus()
    assembly = AssemblyAIVoiceProvider().getStatus()
    return {"providers": [BrowserVoiceProvider().getStatus(), gemini, assembly, MockVoiceProvider().getStatus()], "selected": "GEMINI" if gemini["configured"] else "ASSEMBLYAI" if assembly["configured"] else "BROWSER"}


_voice_token_issued_at = 0.0
_voice_token_lock = asyncio.Lock()


@kavach_router.post("/api/voice/assemblyai/token")
async def mint_assemblyai_token():
    """Mint a 60-second, single-use browser token without exposing the API key."""
    import os
    import urllib.request
    global _voice_token_issued_at
    key = os.getenv("ASSEMBLYAI_API_KEY", "").strip()
    if not key:
        raise HTTPException(503, "AssemblyAI is not configured; browser speech remains available")
    async with _voice_token_lock:
        now = time.monotonic()
        if now - _voice_token_issued_at < 1.0:
            raise HTTPException(429, "Voice token endpoint is rate limited")
        _voice_token_issued_at = now
    request = urllib.request.Request("https://streaming.assemblyai.com/v3/token?expires_in_seconds=60", headers={"Authorization": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            payload = json.loads(response.read().decode("utf-8"))
        token = payload.get("token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise ValueError("Token response is missing token")
        return {"token": token, "expires_in_seconds": 60, "provider": "AssemblyAI"}
    except Exception as exc:
        raise HTTPException(502, f"AssemblyAI token could not be issued ({type(exc).__name__})") from exc


_gemini_token_issued_at = 0.0
_gemini_token_lock = asyncio.Lock()


@kavach_router.post("/api/voice/gemini/token")
async def mint_gemini_live_token():
    """Create one short-lived, constrained Gemini Live token; never return the API key."""
    import os
    import urllib.request
    global _gemini_token_issued_at
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise HTTPException(503, "Gemini voice is not configured; browser speech remains available")
    async with _gemini_token_lock:
        now = time.monotonic()
        if now - _gemini_token_issued_at < 1.0:
            raise HTTPException(429, "Voice token endpoint is rate limited")
        _gemini_token_issued_at = now
    current = datetime.now(timezone.utc)
    import datetime as datetime_module
    expire_time = (current + datetime_module.timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    new_session_expire = (current + datetime_module.timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    model_name = os.getenv("GEMINI_LIVE_TRANSCRIBE_MODEL", "gemini-3.5-transcribe-live").strip()
    if not model_name.startswith("gemini-") or len(model_name) > 100:
        raise HTTPException(500, "Gemini voice model configuration is invalid")
    body = json.dumps({"uses": 1, "expireTime": expire_time, "newSessionExpireTime": new_session_expire, "liveConnectConstraints": {"model": f"models/{model_name}", "config": {"generationConfig": {"responseModalities": ["TEXT"]}, "inputAudioTranscription": {"languageCodes": [], "customVocabulary": ["KAVACH", "Silk Board", "Koramangala", "Bengaluru", "ambulance", "replan"]}}}}).encode("utf-8")
    request = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/auth_tokens", data=body, headers={"x-goog-api-key": key, "Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    def request_ephemeral_token() -> dict[str, Any]:
        with urllib.request.urlopen(request, timeout=8) as response:
            token_payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(token_payload, dict):
            raise ValueError("Invalid token response")
        return token_payload
    try:
        payload = await asyncio.to_thread(request_ephemeral_token)
        token = payload.get("name") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise ValueError("Token response missing token name")
        return {"token": token, "provider": "Gemini Live Transcription", "model": model_name, "expires_in_seconds": 300, "new_session_expires_in_seconds": 60}
    except Exception as exc:
        raise HTTPException(502, f"Gemini voice token could not be issued ({type(exc).__name__})") from exc


@kavach_router.get("/api/events/stream")
async def event_stream(after: int | None = None):
    async def stream():
        cursor = _event_sequence if after is None else max(0, after)
        while True:
            pending = [event for event in _state["audit"] if int(event.get("sequence", 0)) > cursor]
            for event in pending:
                cursor = int(event["sequence"])
                yield f"id: {cursor}\nevent: kavach\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            if not pending:
                yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@kavach_router.post("/api/voice/command")
async def voice_command(payload: VoiceCommandInput):
    """Turn final STT text into a typed intent. This endpoint never executes it."""
    parsed = parse_voice_command(payload.transcript)
    _event("voice_command_parsed", f"VOICE · {parsed['transcript'][:240]}", intent=parsed["intent"], confidence=parsed["confidence"], confirmation_required=parsed["confirmationRequired"], parser=parsed["parser"])
    return parsed


@kavach_router.get("/api/agents/status")
async def agents_status():
    return {"agents": [{**spec, **_state["agents"].get(spec["id"], {})} for spec in AGENT_SPECS], "data_state": "SIMULATED"}


@kavach_router.get("/api/kavach/incidents")
async def list_kavach_incidents():
    return _state["incidents"]


@kavach_router.post("/api/kavach/incidents", status_code=201)
async def create_kavach_incident(payload: IncidentInput):
    async with _lock:
        now = _now()
        incident = {"incident_id": f"KAV-{uuid.uuid4().hex[:8].upper()}", **payload.model_dump(), "priority": payload.severity, "status": "DETECTED", "created_at": now, "updated_at": now, "data_state": "SIMULATED", "transitions": [{"from": None, "to": "DETECTED", "at": now, "reason": "Incident reported to local demo"}], "agent_outputs": [], "route": None, "recommended_hospital": None}
        _state["incidents"].insert(0, incident)
        _event("incident_created", f"{incident['incident_type']} · {incident['location_name']}", incident_id=incident["incident_id"])
        return incident


@kavach_router.post("/api/agents/run")
async def run_agents(payload: AgentRunInput):
    async with _lock:
        incident = _incident(payload.incident_id)
        if incident["status"] not in {"DETECTED", "TRIAGED", "INVESTIGATING", "REPLANNING"}:
            raise HTTPException(409, f"Agents cannot run while incident is {incident['status']}")
        if incident["status"] == "DETECTED":
            _transition(incident, "TRIAGED", "Deterministic severity and incident type assessment")
        _transition(incident, "INVESTIGATING", "Ten specialized deterministic agents assigned")
        outputs = _run_all_agents(incident)
        gemini_analysis = await asyncio.to_thread(analyze_with_gemini, incident, outputs)
        incident["gemini_analysis"] = gemini_analysis
        _event("gemini_analysis_completed", "Gemini advisory analysis completed" if gemini_analysis["status"] == "AVAILABLE" else "Gemini unavailable; deterministic agent plan retained", incident_id=incident["incident_id"], status=gemini_analysis["status"], mode=gemini_analysis["mode"])
        _transition(incident, "SIMULATING", "Route and resource plan evaluated against the current deterministic city state")
        _transition(incident, "PLANNED", "Specialist findings merged into a route-aware response plan")
        _transition(incident, "AWAITING_APPROVAL", "Plan includes simulated resource allocation and local-only notification draft")
        _event("agents_completed", "Ten agents completed structured investigation", incident_id=incident["incident_id"], agent_count=len(outputs))
        return {"incident": incident, "agents": outputs, "gemini_analysis": gemini_analysis, "plan": {"route": incident["route"], "route_candidates": incident.get("route_candidates", []), "simulation": incident.get("simulation"), "hospital": incident["recommended_hospital"], "notification": incident["local_notification_draft"], "requires_approval": True}}


@kavach_router.post("/api/commands/{incident_id}/approve")
async def approve_command(incident_id: str, payload: ActorInput):
    async with _lock:
        if payload.role not in {"ADMIN", "COMMANDER", "OPERATOR"}:
            raise HTTPException(403, "VIEWER role cannot approve response plans")
        incident = _incident(incident_id)
        if incident["status"] != "AWAITING_APPROVAL":
            raise HTTPException(409, "Only a plan awaiting approval can be approved")
        incident["approved_by"] = payload.actor
        incident["approved_role"] = payload.role
        incident["approved_at"] = _now()
        _transition(incident, "APPROVED", f"Explicit approval recorded from {payload.actor}")
        return {"status": incident["status"], "approved_by": payload.actor, "incident_id": incident_id}


@kavach_router.post("/api/kavach/incidents/{incident_id}/prioritize")
async def prioritize_incident(incident_id: str, payload: ActorInput):
    async with _lock:
        if payload.role == "VIEWER":
            raise HTTPException(403, "VIEWER role is read-only")
        incident = _incident(incident_id)
        if incident["status"] in {"RESOLVED", "FAILED"}:
            raise HTTPException(409, "A closed incident cannot be prioritized")
        previous = incident.get("priority", incident["severity"])
        incident["priority"] = "critical"
        incident["severity"] = "critical"
        incident.setdefault("priority_history", []).append({"from": previous, "to": "critical", "actor": payload.actor, "at": _now()})
        _event("incident_prioritized", "Incident priority raised to critical", incident_id=incident_id, actor=payload.actor)
        return {"incident": incident, "changed": previous != "critical", "data_state": "SIMULATED"}


@kavach_router.post("/api/commands/{incident_id}/replan")
async def replan_command(incident_id: str, payload: ActorInput):
    async with _lock:
        if payload.role == "VIEWER":
            raise HTTPException(403, "VIEWER role cannot create or replan response recommendations")
        incident = _incident(incident_id)
        if not incident.get("route"):
            raise HTTPException(409, "Run an investigation before replanning")
        if incident["status"] not in {"RESOLVED", "FAILED", "AWAITING_APPROVAL", "APPROVED"}:
            raise HTTPException(409, f"Incident cannot be replanned while {incident['status']}")
        _transition(incident, "REPLANNING", f"Operator {payload.actor} requested route and response reassessment")
        _transition(incident, "INVESTIGATING", "Specialists re-read the current simulated city state")
        outputs = _run_all_agents(incident)
        _transition(incident, "SIMULATING", "Updated route/resource recommendation evaluated")
        _transition(incident, "PLANNED", "Updated response plan calculated")
        _transition(incident, "AWAITING_APPROVAL", "Revised plan requires fresh approval")
        _event("replan_completed", "Operator-requested response plan recalculated", incident_id=incident_id, trace_id=incident.get("trace_id"), actor=payload.actor, route=incident["route"])
        return {"incident": incident, "agents": outputs, "replanned": True, "data_state": "SIMULATED"}


@kavach_router.post("/api/commands/{incident_id}/execute")
async def execute_command(incident_id: str, payload: ActorInput):
    async with _lock:
        if payload.role not in {"ADMIN", "COMMANDER"}:
            raise HTTPException(403, "Execution requires COMMANDER or ADMIN role")
        incident = _incident(incident_id)
        if incident["status"] != "APPROVED":
            raise HTTPException(409, "Execution requires an approved plan")
        _transition(incident, "EXECUTING", f"Local demo execution started by {payload.actor}")
        allocated = next((r for r in _state["resources"] if r["type"] == "ambulance" and r["status"] == "available"), None)
        if allocated:
            allocated["status"] = "deployed"
            allocated["incident_id"] = incident_id
        incident["executed_actions"] = [{"type": "resource_reservation", "resource_id": allocated["id"] if allocated else None, "external_side_effect": False}, {"type": "notification_draft", "sent": False, "external_side_effect": False}]
        _transition(incident, "VERIFYING", "Local state changes checked")
        verified = bool(allocated) and incident.get("route", {}).get("status") == "calculated"
        incident["verification"] = {"passed": verified, "checks": ["approval recorded", "resource state updated" if allocated else "no resource available", "route exists" if incident.get("route", {}).get("status") == "calculated" else "route unavailable"], "at": _now()}
        _transition(incident, "RESOLVED" if verified else "FAILED", "Local response state verified" if verified else "Verification failed; operator review required")
        _event("execution_verified", f"Local action verification {'passed' if verified else 'failed'}", incident_id=incident_id, actor=payload.actor)
        return {"incident": incident, "external_actions_sent": False, "data_state": "SIMULATED"}


@kavach_router.post("/api/simulation/inject")
async def inject_simulation(payload: SimulationInput):
    async with _lock:
        if payload.role == "VIEWER":
            raise HTTPException(403, "VIEWER role cannot modify the simulated city")
        if payload.event == "road_block":
            candidates = [i for i in _state["incidents"] if i.get("route", {}).get("nodes") and i["status"] in {"RESOLVED", "FAILED", "AWAITING_APPROVAL"}]
            if not candidates:
                candidates = [i for i in _state["incidents"] if i.get("route", {}).get("coordinates")]
            if not candidates:
                raise HTTPException(409, "Run agents first so a road-graph route exists")
            incident = candidates[0]
            previous_route = incident.get("route") or {}
            previous_nodes = list(previous_route.get("nodes", []))
            previous_distance = previous_route.get("distance_km")
            nodes = incident["route"].get("nodes", [])
            node_id = nodes[len(nodes) // 2] if nodes else None
            point = None
            if node_id is not None:
                try:
                    from api import G
                    point = {"lon": float(G.nodes[node_id]["x"]), "lat": float(G.nodes[node_id]["y"])}
                except (ImportError, KeyError):
                    point = None
            closure = {"block_id": f"DEMO-BLOCK-{uuid.uuid4().hex[:6].upper()}", "incident_id": incident["incident_id"], "node_id": node_id, **(point or {}), "active": True, "data_state": "SIMULATED", "created_at": _now()}
            _state["road_blocks"].append(closure)
            _event("road_block_injected", "A road closure was injected into the scenario", incident_id=incident["incident_id"], block_id=closure["block_id"], node_id=node_id)
            failure_verified = node_id is not None and node_id in previous_nodes
            _event("failure_detected", "Selected route invalidated by a simulated road closure" if failure_verified else "Road closure injected; selected route membership could not be verified", incident_id=incident["incident_id"], block_id=closure["block_id"], failure_verified=failure_verified, route_node=node_id)
        elif payload.event == "resource_failure":
            resource = next((r for r in _state["resources"] if r["id"] == payload.target_id), None) if payload.target_id else next((r for r in _state["resources"] if r["status"] == "available"), None)
            if not resource:
                raise HTTPException(404, "No matching available demo resource")
            resource["status"] = "unavailable"
            _event("resource_failure", f"{resource['name']} marked unavailable in demo", resource_id=resource["id"])
        elif payload.event == "hospital_capacity":
            hospital = next((h for h in _state["hospitals"] if h["id"] == payload.target_id), None) if payload.target_id else _state["hospitals"][0]
            hospital["beds_available"] = max(0, int(payload.value if payload.value is not None else 0))
            if hospital["beds_available"] == 0:
                hospital["status"] = "unavailable"
            _event("hospital_capacity", f"{hospital['name']} capacity changed in demo", hospital_id=hospital["id"], beds_available=hospital["beds_available"])
        elif payload.event == "weather_change":
            _state["weather"] = {"intensity": min(max(payload.value if payload.value is not None else 0.7, 0.0), 1.0), "data_state": "SIMULATED", "updated_at": _now()}
            _event("weather_change", "Simulated weather changed", weather=_state["weather"])
        elif payload.event == "new_incident":
            now = _now()
            incident = {"incident_id": f"KAV-{uuid.uuid4().hex[:8].upper()}", "incident_type": "collision", "severity": "high", "description": "Injected deterministic secondary incident", "location_name": "HSR Layout, Bengaluru", "lat": 12.918, "lon": 77.644, "location_source": "SIMULATED", "status": "DETECTED", "created_at": now, "updated_at": now, "data_state": "SIMULATED", "transitions": [{"from": None, "to": "DETECTED", "at": now, "reason": "Secondary incident injected into local simulation"}], "agent_outputs": [], "route": None, "recommended_hospital": None}
            _state["incidents"].insert(0, incident)
            _event("incident_created", "Secondary simulated collision injected", incident_id=incident["incident_id"])
            return {"event": payload.event, "replanned": False, "incident": incident, "data_state": "SIMULATED"}
        else:
            raise HTTPException(422, "Unsupported simulation event")

        targets = [i for i in _state["incidents"] if i["status"] in {"RESOLVED", "FAILED", "AWAITING_APPROVAL", "APPROVED"}]
        if not targets:
            return {"event": payload.event, "replanned": False, "data_state": "SIMULATED"}
        incident = targets[0]
        _transition(incident, "REPLANNING", "City state changed; previous route/plan may be stale")
        for resource in _state["resources"]:
            if resource.get("incident_id") == incident["incident_id"]:
                resource["status"] = "available"
                resource.pop("incident_id", None)
        _transition(incident, "INVESTIGATING", "Agents re-read changed road/resource/hospital state")
        _run_all_agents(incident)
        _transition(incident, "SIMULATING", "Updated route and resource plan evaluated against changed city state")
        _transition(incident, "PLANNED", "Route and resource recommendation recalculated against current scenario")
        _transition(incident, "AWAITING_APPROVAL", "Changed plan requires fresh operator approval")
        route_change = {"previous_distance_km": previous_distance if payload.event == "road_block" else None, "new_distance_km": incident["route"].get("distance_km"), "path_changed": previous_nodes != incident["route"].get("nodes", []) if payload.event == "road_block" else None, "failure_verified": failure_verified if payload.event == "road_block" else None}
        _event("replan_completed", f"New route status: {incident['route']['status']}", incident_id=incident["incident_id"], route=incident["route"], route_change=route_change, actor=payload.actor)
        return {"event": payload.event, "replanned": True, "failure_verified": route_change["failure_verified"], "route_change": route_change, "incident": incident, "data_state": "SIMULATED"}


@kavach_router.post("/api/simulation/reset")
async def reset_simulation(payload: ActorInput = ActorInput()):
    async with _lock:
        if payload.role == "VIEWER":
            raise HTTPException(403, "VIEWER role cannot reset the simulated city")
        reset_state()
        _event("scenario_reset", "Deterministic city scenario reset")
        return {"status": "reset", "data_state": "SIMULATED"}


@kavach_router.get("/api/audit")
async def audit_log():
    return list(reversed(_state["audit"]))


@kavach_router.get("/api/notifications/prepare")
async def notification_preview():
    return {**communication_status(), "drafts": [incident.get("local_notification_draft") for incident in _state["incidents"] if incident.get("local_notification_draft")]}


@kavach_router.post("/api/communications/send")
async def send_communication(payload: CommunicationInput):
    async with _lock:
        if payload.role not in {"ADMIN", "COMMANDER"}:
            raise HTTPException(403, "Sending a notification requires COMMANDER or ADMIN role")
        incident = _incident(payload.incident_id)
        if incident["status"] != "APPROVED":
            raise HTTPException(409, "A response plan must be approved before sending or recording its notification")
        event = {"event": "EMERGENCY_INCIDENT", "incidentId": incident["incident_id"], "severity": incident["severity"], "location": {"name": incident["location_name"], "lat": incident["lat"], "lon": incident["lon"], "source": incident.get("location_source", "SIMULATED")}, "recommendedActions": incident.get("agent_outputs", []), "requiresApproval": True, "dataState": "SIMULATED", "createdAt": _now()}
        result = await asyncio.to_thread(send_approved_event, event)
        _event("communication_result", f"Communication result: {result['status']}", incident_id=incident["incident_id"], actor=payload.actor, provider=result["provider"], external_delivery=result["externalDelivery"])
        incident["communication_result"] = result
        return result


def _communication_draft(draft_id: str) -> dict[str, Any]:
    draft = next((item for item in _state["communication_drafts"] if item["id"] == draft_id), None)
    if draft is None:
        raise HTTPException(404, "Communication draft not found")
    return draft


@kavach_router.get("/api/communications")
async def list_communications(incident_id: str | None = None):
    drafts = _state["communication_drafts"]
    if incident_id:
        drafts = [item for item in drafts if item["incident_id"] == incident_id]
    return {"drafts": list(reversed(drafts)), "provider": email_provider_status()}


@kavach_router.put("/api/communications/{draft_id}")
async def edit_communication(draft_id: str, payload: CommunicationEditInput):
    if payload.role not in {"ADMIN", "COMMANDER"}:
        raise HTTPException(403, "Only COMMANDER or ADMIN can edit a communication draft")
    draft = _communication_draft(draft_id)
    if draft["status"] != "AWAITING_APPROVAL":
        raise HTTPException(409, "Only a draft awaiting approval can be edited")
    draft.update({"subject": payload.subject.strip(), "body": payload.body.strip(), "updated_at": _now()})
    _event("communication_draft_edited", f"{draft['department']} email draft edited for review", incident_id=draft["incident_id"], draft_id=draft_id, actor=payload.actor, mode=draft["mode"])
    return draft


@kavach_router.post("/api/communications/{draft_id}/approve")
async def approve_communication(draft_id: str, payload: CommunicationActorInput):
    if payload.role not in {"ADMIN", "COMMANDER"}:
        raise HTTPException(403, "Approving external communication requires COMMANDER or ADMIN")
    draft = _communication_draft(draft_id)
    if draft["status"] != "AWAITING_APPROVAL":
        raise HTTPException(409, "Communication draft is not awaiting approval")
    if not draft.get("recipient"):
        raise HTTPException(409, f"No {draft['department']} test recipient is configured")
    draft.update({"status": "APPROVED", "approved_at": _now(), "approved_by": payload.actor, "updated_at": _now()})
    _event("communication_approved", f"{draft['department']} email approved by {payload.actor}", incident_id=draft["incident_id"], draft_id=draft_id, actor=payload.actor, mode=draft["mode"])
    return draft


@kavach_router.post("/api/communications/{draft_id}/reject")
async def reject_communication(draft_id: str, payload: CommunicationActorInput):
    if payload.role not in {"ADMIN", "COMMANDER"}:
        raise HTTPException(403, "Rejecting external communication requires COMMANDER or ADMIN")
    draft = _communication_draft(draft_id)
    if draft["status"] != "AWAITING_APPROVAL":
        raise HTTPException(409, "Communication draft is not awaiting a decision")
    draft.update({"status": "REJECTED", "updated_at": _now()})
    _event("communication_rejected", f"{draft['department']} email rejected", incident_id=draft["incident_id"], draft_id=draft_id, actor=payload.actor)
    return draft


@kavach_router.post("/api/communications/{draft_id}/send")
async def send_communication_draft(draft_id: str, payload: CommunicationActorInput):
    if payload.role not in {"ADMIN", "COMMANDER"}:
        raise HTTPException(403, "Sending external communication requires COMMANDER or ADMIN")
    draft = _communication_draft(draft_id)
    if draft["status"] != "APPROVED":
        raise HTTPException(409, "The communication must be explicitly approved before send")
    if email_provider_status()["status"] != "READY":
        raise HTTPException(503, "SMTP is not ready. Draft remains approved and unsent.")
    draft.update({"status": "SENDING", "updated_at": _now()})
    _event("communication_sending", f"Approved {draft['department']} email is being submitted to SMTP", incident_id=draft["incident_id"], draft_id=draft_id, actor=payload.actor, provider=draft["provider"])
    result = await asyncio.to_thread(send_configured_email, draft["department"], draft["recipient"], draft["subject"], draft["body"])
    stamp = _now()
    draft.update({"status": "SENT" if result["status"] == "SENT" else "FAILED", "updated_at": stamp, "sent_at": stamp if result["status"] == "SENT" else None, "smtp_result": result})
    _event("communication_sent" if result["status"] == "SENT" else "communication_failed", "Email accepted by SMTP server" if result["status"] == "SENT" else f"Email was not sent: {result.get('reason', result['status'])}", incident_id=draft["incident_id"], draft_id=draft_id, actor=payload.actor, provider=result["provider"], accepted_by_smtp=result.get("acceptedBySmtp", False), delivery_verified=False)
    return draft


@kavach_router.post("/api/communications/{draft_id}/simulate-send")
async def simulate_communication_send(draft_id: str, payload: CommunicationActorInput):
    if payload.role not in {"ADMIN", "COMMANDER"}:
        raise HTTPException(403, "Simulating an email action requires COMMANDER or ADMIN")
    if not __import__("os").getenv("KAVACH_DEMO_MODE", "true").casefold() in {"1", "true", "yes", "on"}:
        raise HTTPException(403, "Simulated email is only available in demo mode")
    draft = _communication_draft(draft_id)
    if draft["status"] != "APPROVED":
        raise HTTPException(409, "The communication must be explicitly approved first")
    draft.update({"status": "SIMULATED", "updated_at": _now(), "sent_at": None, "smtp_result": {"status": "SIMULATED_NO_EXTERNAL_DELIVERY", "provider": "KAVACH_DEMO_SIMULATOR", "deliveryVerified": False}})
    _event("communication_simulated_send", f"Approved {draft['department']} email recorded by demo simulator; no email was sent", incident_id=draft["incident_id"], draft_id=draft_id, actor=payload.actor, external_delivery=False, data_state="SIMULATED")
    return draft


@kavach_router.get("/api/cameras")
async def list_cameras():
    return {"cameras": _state["cameras"], "vision": {"status": "UNAVAILABLE", "provider": "No licensed camera detection model configured"}}


@kavach_router.post("/api/cameras")
async def register_camera(payload: CameraInput):
    existing = next((camera for camera in _state["cameras"] if camera["camera_id"] == payload.camera_id), None)
    if existing:
        raise HTTPException(409, "Camera ID is already registered")
    camera = {**payload.model_dump(), "status": "OFFLINE", "stream_type": "LOCAL_WEBCAM", "vision_status": "UNAVAILABLE", "created_at": _now(), "last_frame_at": None, "data_state": "LOCAL"}
    _state["cameras"].append(camera)
    _event("camera_registered", f"Local camera {camera['name']} registered", camera_id=camera["camera_id"], location=camera["location_name"], source="LOCAL_WEBCAM")
    return camera


@kavach_router.get("/api/cameras/{camera_id}")
async def get_camera(camera_id: str):
    camera = next((item for item in _state["cameras"] if item["camera_id"] == camera_id), None)
    if camera is None:
        raise HTTPException(404, "Camera not found")
    return camera


@kavach_router.post("/api/cameras/{camera_id}/start")
async def start_camera(camera_id: str):
    camera = await get_camera(camera_id)
    camera.update({"status": "ONLINE", "last_frame_at": _now(), "vision_status": "STANDBY_MODEL_UNAVAILABLE"})
    _event("camera_connected", f"Local webcam {camera['name']} connected; AI vision unavailable", camera_id=camera_id, vision="UNAVAILABLE")
    return camera


@kavach_router.post("/api/cameras/{camera_id}/stop")
async def stop_camera(camera_id: str):
    camera = await get_camera(camera_id)
    camera.update({"status": "OFFLINE", "vision_status": "UNAVAILABLE"})
    _event("camera_disconnected", f"Local webcam {camera['name']} disconnected", camera_id=camera_id)
    return camera


@kavach_router.delete("/api/cameras/{camera_id}")
async def delete_camera(camera_id: str):
    camera = await get_camera(camera_id)
    _state["cameras"].remove(camera)
    _event("camera_removed", f"Camera {camera['name']} removed", camera_id=camera_id)
    return {"deleted": camera_id}


@kavach_router.post("/api/cameras/{camera_id}/observations/confirm", status_code=201)
async def confirm_camera_observation(camera_id: str, file: UploadFile = File(...), incident_type: str = Form(default="collision"), severity: str = Form(default="high"), description: str = Form(default=""), detection_type: str = Form(default="OPERATOR_REPORTED_EVENT")):
    import base64
    import hashlib
    from io import BytesIO
    camera = await get_camera(camera_id)
    if camera["status"] != "ONLINE":
        raise HTTPException(409, "Start the local webcam before submitting a confirmed observation")
    image_bytes = await file.read(5 * 1024 * 1024 + 1)
    if len(image_bytes) > 5 * 1024 * 1024:
        raise HTTPException(413, "Camera evidence must be 5 MiB or smaller")
    try:
        from PIL import Image
        with Image.open(BytesIO(image_bytes)) as frame:
            frame.verify()
    except Exception as exc:
        raise HTTPException(415, "Camera evidence must be a decodable image") from exc
    evidence_id = f"CAM-EV-{uuid.uuid4().hex[:10].upper()}"
    _state["camera_evidence"][evidence_id] = {"id": evidence_id, "camera_id": camera_id, "captured_at": _now(), "sha256": hashlib.sha256(image_bytes).hexdigest(), "image_data": f"data:{file.content_type or 'image/jpeg'};base64,{base64.b64encode(image_bytes).decode('ascii')}"}
    payload = IncidentInput(incident_type=incident_type, severity=severity, description=description or "Operator confirmed an event from a local webcam frame", location_name=camera["location_name"], lat=camera["lat"], lon=camera["lon"], location_source="USER_SELECTED")
    incident = await create_kavach_incident(payload)
    incident.update({"source": "CAMERA", "source_id": camera_id, "camera_evidence_id": evidence_id, "camera_detection": {"type": detection_type, "status": "OPERATOR_CONFIRMED", "model": None, "confidence": None, "captured_at": _state['camera_evidence'][evidence_id]['captured_at'], "data_state": "USER_CONFIRMED"}})
    _event("vision_confirmation", f"Operator confirmed {detection_type} from a local webcam frame; no AI detection model ran", incident_id=incident["incident_id"], camera_id=camera_id, evidence_id=evidence_id, model="UNAVAILABLE", confidence=None, source="HUMAN_OPERATOR")
    await run_agents(AgentRunInput(incident_id=incident["incident_id"]))
    camera["last_frame_at"] = _state["camera_evidence"][evidence_id]["captured_at"]
    return {"incident": incident, "evidence": {key: value for key, value in _state["camera_evidence"][evidence_id].items() if key != "image_data"}, "pipeline_started": True}


@kavach_router.get("/api/cameras/evidence/{evidence_id}")
async def get_camera_evidence(evidence_id: str):
    evidence = _state["camera_evidence"].get(evidence_id)
    if not evidence:
        raise HTTPException(404, "Camera evidence not found")
    return evidence


def _surface_cues(frame: Any) -> list[dict[str, Any]]:
    """Return measurable contrast regions for a person to inspect; no defect classification."""
    import cv2
    import numpy as np

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    if min(height, width) < 64:
        return []
    global_mean = float(gray.mean())
    block_w, block_h = max(32, width // 8), max(32, height // 6)
    cues = []
    for y in range(0, height - block_h + 1, block_h):
        for x in range(0, width - block_w + 1, block_w):
            patch = gray[y:y + block_h, x:x + block_w]
            mean = float(patch.mean())
            texture = float(patch.std())
            delta = global_mean - mean
            if delta >= 18 and texture >= 12:
                cues.append({"bbox_px": [x, y, x + block_w, y + block_h], "brightness_delta": round(delta, 1), "texture_stddev": round(texture, 1), "interpretation": "darker textured region; could be shadow, stain, patch, or surface damage"})
    cues.sort(key=lambda item: (item["brightness_delta"] * item["texture_stddev"]), reverse=True)
    return cues[:8]


def _exif_gps(image_bytes: bytes) -> dict[str, float] | None:
    try:
        from PIL import Image

        image = Image.open(__import__("io").BytesIO(image_bytes))
        exif = image.getexif()
        gps = exif.get_ifd(34853) if exif else {}
        if not gps:
            return None
        latitude = gps.get(2)
        longitude = gps.get(4)
        if not latitude or not longitude:
            return None
        def degrees(parts: Any) -> float:
            return float(parts[0]) + float(parts[1]) / 60 + float(parts[2]) / 3600
        lat, lon = degrees(latitude), degrees(longitude)
        if gps.get(1) == "S": lat = -lat
        if gps.get(3) == "W": lon = -lon
        return {"lat": lat, "lon": lon}
    except Exception:
        return None


@kavach_router.post("/api/road-analysis")
async def analyze_road_media(file: UploadFile = File(...), ocr_text: str = Form(default=""), ocr_confidence: float | None = Form(default=None), ocr_provider: str = Form(default="")):
    import cv2
    import hashlib
    import numpy as np
    import os
    import tempfile

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Maximum upload size is 20 MiB")
    if not content:
        raise HTTPException(400, "Uploaded file is empty")
    filename = (file.filename or "upload").lower()
    is_video = filename.endswith((".mp4", ".mov", ".avi", ".webm", ".mkv")) or (file.content_type or "").startswith("video/")
    if not is_video and not (file.content_type or "").startswith("image/"):
        raise HTTPException(415, "Upload a supported image or video file")

    frames: list[Any] = []
    dimensions: list[dict[str, int]] = []
    gps = None if is_video else _exif_gps(content)
    if is_video:
        suffix = os.path.splitext(filename)[1] or ".mp4"
        with tempfile.NamedTemporaryFile(prefix="kavach-media-", suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            temp_path = tmp.name
        try:
            capture = cv2.VideoCapture(temp_path)
            if not capture.isOpened():
                raise HTTPException(400, "Video could not be decoded")
            fps = capture.get(cv2.CAP_PROP_FPS) or 1.0
            total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            step = max(1, int(total / 8))
            for index in range(0, total, step):
                capture.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, frame = capture.read()
                if ok:
                    frames.append(frame)
                    dimensions.append({"width": int(frame.shape[1]), "height": int(frame.shape[0]), "frame": index, "time_seconds": round(index / fps, 2)})
                if len(frames) >= 8:
                    break
            capture.release()
        finally:
            try: os.unlink(temp_path)
            except OSError: pass
    else:
        data = np.frombuffer(content, dtype=np.uint8)
        frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if frame is None:
            raise HTTPException(400, "Image could not be decoded")
        frames = [frame]
        dimensions = [{"width": int(frame.shape[1]), "height": int(frame.shape[0])}]
    if not frames:
        raise HTTPException(400, "No decodable image frames found")

    cues = []
    for frame_index, frame in enumerate(frames):
        for cue in _surface_cues(frame):
            cues.append({**cue, "frame_index": frame_index})
    road_model = get_road_damage_provider()
    model_status = road_model.getStatus()
    detections: list[dict[str, Any]] = []
    model_error = model_status.get("error")
    if model_status.get("configured"):
        try:
            for frame_index, frame in enumerate(frames):
                for detection in road_model.infer(frame):
                    severity = derive_damage_severity(detection, int(frame.shape[1]), int(frame.shape[0]))
                    detections.append({**detection, **severity, "frameIndex": frame_index, "source": road_model.name, "mode": "LIVE"})
            model_error = None
        except Exception as exc:
            model_error = f"MODEL_INFERENCE_FAILED:{type(exc).__name__}"
            detections = []
    if not isinstance(ocr_text, str):
        ocr_text = ""
    if not isinstance(ocr_confidence, (int, float)):
        ocr_confidence = None
    if not isinstance(ocr_provider, str):
        ocr_provider = ""
    ocr_result = {"text": ocr_text.strip()[:1000], "confidence": round(max(0.0, min(float(ocr_confidence), 100.0)) / 100.0, 3) if ocr_confidence is not None else None, "provider": ocr_provider or ("unknown" if ocr_text.strip() else None), "mode": "LOCAL" if ocr_text.strip() else "UNAVAILABLE"}
    analysis_id = f"ROAD-{uuid.uuid4().hex[:10].upper()}"
    analysis = {
        "analysis_id": analysis_id, "filename": os.path.basename(filename), "media_type": "video" if is_video else "image",
        "sha256": hashlib.sha256(content).hexdigest(), "frames_analyzed": len(frames), "dimensions": dimensions,
        "provider": road_model.name if model_status.get("configured") else "UNAVAILABLE", "model_mode": "LIVE" if model_status.get("configured") and not model_error else "UNAVAILABLE", "model_error": model_error,
        "data_state": "LIVE" if model_status.get("configured") and not model_error else "UNAVAILABLE", "status": "model_inference_complete" if model_status.get("configured") and not model_error else "needs_human_review",
        "classification": detections[0]["damageType"] if detections else None, "pothole_detected": any(item["damageType"] == "POTHOLE" for item in detections) if model_status.get("configured") and not model_error else None,
        "severity": detections[0]["severity"] if detections else None, "severity_reason": detections[0]["reason"] if detections else None, "detections": detections,
        "surface_cues": cues, "cue_count": len(cues), "ocr_text": ocr_text.strip()[:1000],
        "ocr": ocr_result,
        "gps": gps, "location_status": "EXIF_GPS" if gps else "NO_GPS_METADATA",
        "disclaimer": "Model outputs are advisory and require human confirmation. If no license-compatible model is configured, contrast cues are not pothole predictions or road-damage classifications. OCR is uncertain evidence and does not establish location.",
        "created_at": _now(),
    }
    _state["road_analyses"][analysis_id] = analysis
    _event("road_media_analyzed", f"Road media processed; {len(detections)} model detection(s), {len(cues)} non-classifying visual cue(s)", analysis_id=analysis_id, media_type=analysis["media_type"], model_mode=analysis["model_mode"], detection_count=len(detections), data_state=analysis["model_mode"])
    return analysis


@kavach_router.get("/api/road-analysis/{analysis_id}")
async def get_road_analysis(analysis_id: str):
    result = _state["road_analyses"].get(analysis_id)
    if not result:
        raise HTTPException(404, "Road analysis not found")
    return result


@kavach_router.post("/api/road-analysis/{analysis_id}/incident", status_code=201)
async def create_road_incident(analysis_id: str, payload: RoadIncidentInput):
    result = _state["road_analyses"].get(analysis_id)
    if not result:
        raise HTTPException(404, "Road analysis not found")
    if payload.lat is None or payload.lon is None:
        if not result.get("gps"):
            raise HTTPException(422, "This media has no GPS metadata; select/confirm the road location on the map first")
        lat, lon = result["gps"]["lat"], result["gps"]["lon"]
    else:
        lat, lon = payload.lat, payload.lon
    source = "EXIF" if result.get("gps") and payload.location_source == "USER_SELECTED" else payload.location_source
    created = await create_kavach_incident(IncidentInput(incident_type="road_hazard", severity=payload.severity, description=payload.description, location_name=payload.location_name, lat=lat, lon=lon, location_source=source))
    created["image_analysis"] = {"analysis_id": analysis_id, "review_status": "operator_submitted", "surface_cue_count": result["cue_count"], "ocr_text": result["ocr_text"], "ocr_confidence": result.get("ocr", {}).get("confidence"), "damage_detection_count": len(result.get("detections", [])), "model_mode": result.get("model_mode", "UNAVAILABLE"), "gps_status": result["location_status"]}
    _event("road_incident_created", "Operator-confirmed road hazard entered the KAVACH incident queue", analysis_id=analysis_id, incident_id=created["incident_id"])
    affected_incidents = []
    hazard_nodes = _active_hazard_nodes()
    for active in list(_state["incidents"]):
        if active["incident_id"] == created["incident_id"] or active.get("incident_type") in {"road_hazard", "road_damage"} or not active.get("route"):
            continue
        if active.get("status") not in {"AWAITING_APPROVAL", "APPROVED", "EXECUTING", "FAILED", "REPLANNING"}:
            continue
        if not set(active["route"].get("nodes", [])) & hazard_nodes:
            continue
        old_nodes = list(active["route"].get("nodes", []))
        old_distance = active["route"].get("distance_km")
        _event("failure_detected", "Confirmed road hazard intersects an active emergency corridor", incident_id=active["incident_id"], hazard_incident_id=created["incident_id"], road_hazard_id=analysis_id)
        _transition(active, "REPLANNING", "New operator-confirmed road hazard intersects the planned corridor")
        _run_all_agents(active)
        new_nodes = list((active.get("route") or {}).get("nodes", []))
        new_distance = (active.get("route") or {}).get("distance_km")
        active["route_change"] = {"path_changed": old_nodes != new_nodes, "previous_distance_km": old_distance, "new_distance_km": new_distance, "trigger": "ROAD_HAZARD"}
        _event("replan_completed", "Road hazard evidence was evaluated and the emergency route was recalculated", incident_id=active["incident_id"], hazard_incident_id=created["incident_id"], route_change=active["route_change"])
        _transition(active, "AWAITING_APPROVAL", "Road-hazard-adjusted plan requires renewed human approval")
        affected_incidents.append({"incident_id": active["incident_id"], "route_change": active["route_change"], "approval_required": True})
    created["affected_incidents"] = affected_incidents
    return created
