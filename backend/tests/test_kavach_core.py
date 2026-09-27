import asyncio
import json
from io import BytesIO
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np
import pytest
from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import Headers, UploadFile

import kavach_core as core
from providers import ProviderResult, WeatherProvider, fetch_government_resource
from providers_v3 import DataGovProvider, RoadDamageModelProvider, provider_status_rows
from road_ai import derive_damage_severity
from voice import parse_voice_command


def run(coro):
    return asyncio.run(coro)


async def make_investigated_incident():
    core.reset_state()
    incident = await core.create_kavach_incident(core.IncidentInput(
        incident_type="collision", severity="critical", description="unit scenario",
        location_name="Koramangala, Bengaluru", lat=12.935, lon=77.62,
    ))
    result = await core.run_agents(core.AgentRunInput(incident_id=incident["incident_id"]))
    return incident, result


def test_ten_specialists_produce_structured_findings_and_plan_requires_approval():
    incident, result = run(make_investigated_incident())
    assert len(result["agents"]) == 10
    assert {agent["agent"] for agent in result["agents"]} == {spec["id"] for spec in core.AGENT_SPECS}
    assert all(agent["findings"] and agent["evidence"] and 0 <= agent["confidence"] <= 1 for agent in result["agents"])
    assert incident["status"] == "AWAITING_APPROVAL"
    assert result["plan"]["requires_approval"] is True
    assert result["plan"]["notification"]["sent"] is False


def test_execution_is_blocked_until_approved_then_local_action_verifies():
    incident, _ = run(make_investigated_incident())
    incident_id = incident["incident_id"]
    with pytest.raises(HTTPException) as error:
        run(core.execute_command(incident_id, core.ActorInput(actor="commander", role="COMMANDER")))
    assert error.value.status_code == 409

    approved = run(core.approve_command(incident_id, core.ActorInput(actor="operator")))
    executed = run(core.execute_command(incident_id, core.ActorInput(actor="commander", role="COMMANDER")))
    assert approved["status"] == "APPROVED"
    assert executed["incident"]["status"] == "RESOLVED"
    assert executed["incident"]["verification"]["passed"] is True
    assert executed["external_actions_sent"] is False


def test_road_closure_changes_network_route_and_reopens_approval():
    incident, result = run(make_investigated_incident())
    before = result["incident"]["route"]
    assert before["provider"] == "BUNDLED_OSM_NETWORKX"
    incident_id = incident["incident_id"]
    run(core.approve_command(incident_id, core.ActorInput(actor="operator")))
    run(core.execute_command(incident_id, core.ActorInput(actor="commander", role="COMMANDER")))
    replan = run(core.inject_simulation(core.SimulationInput(event="road_block")))
    after = replan["incident"]["route"]
    assert replan["replanned"] is True
    assert replan["incident"]["status"] == "AWAITING_APPROVAL"
    assert after["provider"] == "BUNDLED_OSM_NETWORKX"
    assert after["nodes"] != before["nodes"]
    assert len(core._state["road_blocks"]) == 1
    assert core._state["audit"][-1]["type"] == "replan_completed"


def test_road_upload_reports_visual_cues_without_claiming_pothole_classification():
    image = np.full((240, 320, 3), 180, dtype=np.uint8)
    image[80:150, 90:170] = 45
    image[80:150, 90:170] += np.random.default_rng(7).integers(0, 30, (70, 80, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    upload = UploadFile(filename="surface.jpg", file=BytesIO(encoded.tobytes()), headers=Headers({"content-type": "image/jpeg"}))
    result = run(core.analyze_road_media(upload, "SLOW"))
    assert result["status"] == "needs_human_review"
    assert result["classification"] is None
    assert result["pothole_detected"] is None
    assert result["location_status"] == "NO_GPS_METADATA"
    assert result["ocr_text"] == "SLOW"
    assert "not pothole predictions" in result["disclaimer"]


def test_road_report_requires_confirmed_location_when_media_has_no_gps():
    core.reset_state()
    core._state["road_analyses"]["ROAD-TEST"] = {"analysis_id": "ROAD-TEST", "gps": None, "cue_count": 0, "ocr_text": "", "location_status": "NO_GPS_METADATA"}
    with pytest.raises(HTTPException) as error:
        run(core.create_road_incident("ROAD-TEST", core.RoadIncidentInput(location_name="Koramangala")))
    assert error.value.status_code == 422
    report = run(core.create_road_incident("ROAD-TEST", core.RoadIncidentInput(location_name="Koramangala", lat=12.935, lon=77.62)))
    assert report["incident_type"] == "road_hazard"
    assert report["image_analysis"]["gps_status"] == "NO_GPS_METADATA"


def test_http_api_runs_incident_approval_execution_and_replanning_loop():
    core.reset_state()
    app = FastAPI()
    app.include_router(core.kavach_router)
    client = TestClient(app)
    created = client.post("/api/kavach/incidents", json={"incident_type": "collision", "severity": "high"})
    assert created.status_code == 201
    incident_id = created.json()["incident_id"]
    investigation = client.post("/api/agents/run", json={"incident_id": incident_id})
    assert investigation.status_code == 200
    assert len(investigation.json()["agents"]) == 10
    assert client.post(f"/api/commands/{incident_id}/execute", json={"actor": "tester", "role": "COMMANDER"}).status_code == 409
    assert client.post(f"/api/commands/{incident_id}/approve", json={"actor": "viewer", "role": "VIEWER"}).status_code == 403
    assert client.post(f"/api/commands/{incident_id}/approve", json={"actor": "tester"}).status_code == 200
    executed = client.post(f"/api/commands/{incident_id}/execute", json={"actor": "tester", "role": "COMMANDER"})
    assert executed.json()["incident"]["verification"]["passed"] is True
    replan = client.post("/api/simulation/inject", json={"event": "road_block"})
    assert replan.json()["replanned"] is True
    assert replan.json()["incident"]["status"] == "AWAITING_APPROVAL"
    assert replan.json()["failure_verified"] is True
    assert replan.json()["route_change"]["path_changed"] is True


@pytest.mark.parametrize(("phrase", "intent"), [
    ("Investigate a major accident near Silk Board.", "INVESTIGATE_INCIDENT"),
    ("Find the nearest hospitals with available emergency capacity.", "FIND_HOSPITAL"),
    ("Find the fastest emergency corridor.", "CALCULATE_ROUTE"),
    ("Check whether the route is blocked.", "CHECK_ROUTE"),
    ("Simulate sending an ambulance.", "SIMULATE_RESPONSE"),
    ("Show me what is delaying the response.", "SHOW_DELAYS"),
    ("Prioritize this incident.", "PRIORITIZE_INCIDENT"),
    ("Find nearby fire stations.", "FIND_FIRE_RESOURCE"),
    ("Check road hazards around this route.", "ANALYZE_ROAD"),
    ("Create an emergency response plan.", "CREATE_RESPONSE_PLAN"),
    ("Approve the proposed response.", "APPROVE_PLAN"),
    ("Replan the route.", "REPLAN"),
    ("Read me the current city situation.", "GET_CITY_STATUS"),
    ("Find an available ambulance.", "FIND_AMBULANCE"),
    ("Find nearby police resources.", "FIND_POLICE_RESOURCE"),
    ("Analyze this road.", "ANALYZE_ROAD"),
    ("What are the agents doing?", "GET_AGENT_STATUS"),
    ("Verify the incident.", "VERIFY_INCIDENT"),
    ("Simulate the response.", "SIMULATE_RESPONSE"),
])
def test_voice_intents_are_structured_and_silk_board_is_location_tagged(phrase, intent):
    command = parse_voice_command(phrase)
    assert command["intent"] == intent
    assert command["parser"] == "KAVACH_DETERMINISTIC_INTENT_RULES"
    if intent == "INVESTIGATE_INCIDENT":
        assert command["location"]["name"] == "Silk Board"
        assert command["location"]["locationSource"] == "SIMULATED_STATIC_PLACE_MATCH"


def test_viewer_cannot_approve_or_execute():
    incident, _ = run(make_investigated_incident())
    incident_id = incident["incident_id"]
    with pytest.raises(HTTPException) as approve_error:
        run(core.approve_command(incident_id, core.ActorInput(actor="viewer", role="VIEWER")))
    assert approve_error.value.status_code == 403
    run(core.approve_command(incident_id, core.ActorInput(actor="operator", role="OPERATOR")))
    with pytest.raises(HTTPException) as execute_error:
        run(core.execute_command(incident_id, core.ActorInput(actor="viewer", role="VIEWER")))
    assert execute_error.value.status_code == 403


def test_notification_requires_approval_and_local_provider_never_delivers_externally(monkeypatch):
    monkeypatch.delenv("N8N_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("KAVACH_EXTERNAL_ACTIONS_ENABLED", "false")
    incident, _ = run(make_investigated_incident())
    incident_id = incident["incident_id"]
    app = FastAPI()
    app.include_router(core.kavach_router)
    client = TestClient(app)
    denied = client.post("/api/communications/send", json={"incident_id": incident_id, "actor": "commander", "role": "COMMANDER"})
    assert denied.status_code == 409
    client.post(f"/api/commands/{incident_id}/approve", json={"actor": "operator", "role": "OPERATOR"})
    result = client.post("/api/communications/send", json={"incident_id": incident_id, "actor": "commander", "role": "COMMANDER"})
    assert result.status_code == 200
    assert result.json()["provider"] == "LOCAL_EVENT_WEBHOOK"
    assert result.json()["externalDelivery"] is False


def test_datagov_provider_reports_not_configured_and_supports_query_pagination_and_cache(monkeypatch):
    monkeypatch.setenv("DATAGOV_API_KEY", "test-key-do-not-disclose")
    monkeypatch.setenv("DATAGOV_RESOURCE_ID", "12345678-1234-1234-1234-123456789012")
    provider = DataGovProvider()
    provider._last_request_at = -100
    calls = []

    class Response:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return json.dumps(self.payload).encode()

    def fake_open(request, timeout):
        parsed = urlparse(request.full_url)
        params = parse_qs(parsed.query)
        calls.append(params)
        offset = int(params["offset"][0])
        rows = [{"id": "a"}, {"id": "b"}] if offset == 0 else [{"id": "c"}]
        return Response({"records": rows, "total": 3})

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    result = provider.fetch({"limit": 2, "filters[state]": "Karnataka"})
    assert result.mode == "LIVE"
    assert len(result.data["records"]) == 3
    assert len(calls) == 2
    assert calls[0]["api-key"] == ["test-key-do-not-disclose"]
    assert "test-key-do-not-disclose" not in json.dumps(result.provenance)
    assert provider.fetch({"limit": 2, "filters[state]": "Karnataka"}).mode == "CACHED"
    status = provider.getStatus()
    assert status["configured"] is True and status["lastUpdated"]

    monkeypatch.setenv("DATAGOV_API_KEY", "")
    unconfigured = DataGovProvider()
    assert unconfigured.getStatus()["status"] == "NOT_CONFIGURED"
    assert unconfigured.fetch().mode == "UNAVAILABLE"


@pytest.mark.parametrize("payload", [b"not json", b"[]", b'{"records":null}'])
def test_datagov_malformed_response_is_not_live(monkeypatch, payload):
    monkeypatch.setenv("DATAGOV_API_KEY", "test-key")
    monkeypatch.setenv("DATAGOV_RESOURCE_ID", "12345678-1234-1234-1234-123456789012")
    provider = DataGovProvider(); provider._last_request_at = -100
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return payload
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    assert provider.fetch().mode == "UNAVAILABLE"


def test_provider_contract_and_road_model_license_gate(monkeypatch, tmp_path):
    statuses = provider_status_rows()
    assert statuses and all({"name", "type", "status", "mode", "source", "lastUpdated", "freshness", "requiresAuth", "configured", "error", "capabilities"} <= set(item) for item in statuses)
    model_path = tmp_path / "model.onnx"
    model_path.write_bytes(b"placeholder")
    monkeypatch.setenv("ROAD_DAMAGE_MODEL_PATH", str(model_path))

    class Metadata:
        custom_metadata_map = {"license": "AGPL-3.0 License"}
    class Input:
        name = "images"; shape = [1, 3, 640, 640]
    class Session:
        def get_modelmeta(self): return Metadata()
        def get_inputs(self): return [Input()]
    monkeypatch.setattr("onnxruntime.InferenceSession", lambda *args, **kwargs: Session())
    provider = RoadDamageModelProvider()
    assert provider.getStatus()["mode"] == "UNAVAILABLE"
    assert provider.getStatus()["error"] == "MODEL_LICENSE_UNVERIFIED_OR_INCOMPATIBLE"


def test_road_severity_is_explainable_and_requires_model_detection():
    result = derive_damage_severity({"confidence": 0.92, "boundingBox": [0, 0, 320, 240]}, 320, 240)
    assert result["severity"] == "HIGH"
    assert "Pixel area is not physical defect size" in result["reason"]
    assert derive_damage_severity({}, 320, 240)["severity"] == "LOW"


def test_role_and_voice_authentication_status_are_never_misrepresented():
    status = run(core.get_auth_status())
    assert status["mode"]["label"] == "DEMO AUTHENTICATION · NOT AN IDENTITY"
    assert status["mode"]["authenticated"] is False


def test_voice_unknown_and_ambiguous_phrases_never_become_actions():
    assert parse_voice_command("something unusual please")["intent"] == "UNKNOWN"
    ambiguous = parse_voice_command("Investigate the accident and find a hospital")
    assert ambiguous["intent"] == "AMBIGUOUS"
    assert ambiguous["confirmationRequired"] is True


def test_commander_selects_only_relevant_specialists_for_fire_and_road_damage():
    core.reset_state()
    fire = run(core.create_kavach_incident(core.IncidentInput(incident_type="fire", severity="high")))
    fire_results = run(core.run_agents(core.AgentRunInput(incident_id=fire["incident_id"])))
    fire_ids = {agent["agent"] for agent in fire_results["agents"]}
    assert "fire" in fire_ids and "medical" in fire_ids and "road_intelligence" not in fire_ids
    core.reset_state()
    road = run(core.create_kavach_incident(core.IncidentInput(incident_type="road_hazard", severity="moderate")))
    road_results = run(core.run_agents(core.AgentRunInput(incident_id=road["incident_id"])))
    road_ids = {agent["agent"] for agent in road_results["agents"]}
    assert "road_intelligence" in road_ids and "medical" not in road_ids and "fire" not in road_ids


def test_provider_fallbacks_are_explicit_and_government_is_unavailable_without_credentials(monkeypatch):
    monkeypatch.setenv("DATAGOV_API_KEY", "")
    monkeypatch.setenv("DATAGOV_RESOURCE_ID", "")
    government = fetch_government_resource().as_dict()
    assert government["freshness"] == "UNAVAILABLE"

    monkeypatch.setenv("WEATHER_API_URL", "https://weather.invalid/provider")
    def unavailable(*args, **kwargs):
        raise OSError("offline")
    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    provider = WeatherProvider()
    first = provider.fetch()
    assert first.freshness == "SIMULATED"
    cached_provider = WeatherProvider()
    cached_provider._cached = ProviderResult("Open-Meteo", "2026-09-27T00:00:00+00:00", "LIVE", 0.98, {"rain_mm": 1.0, "intensity": 0.05}, {"url": "https://open-meteo.com"})
    import time
    cached_provider._cached_at = time.monotonic() - 120
    second = cached_provider.fetch()
    assert second.freshness == "CACHED"
    assert second.confidence < first.confidence + 0.6


def test_final_demo_case_manual_incident_to_plan_approval_and_simulated_email(monkeypatch):
    core.reset_state()
    monkeypatch.setenv("KAVACH_DEMO_MODE", "true")
    monkeypatch.setenv("KAVACH_EMAIL_ENABLED", "false")
    monkeypatch.setenv("KAVACH_POLICE_EMAIL", "police-demo@example.test")
    monkeypatch.setenv("KAVACH_HOSPITAL_EMAIL", "hospital-demo@example.test")
    app = FastAPI(); app.include_router(core.kavach_router)
    client = TestClient(app)
    created = client.post("/api/kavach/incidents", json={"incident_type": "collision", "severity": "critical", "description": "Multi-vehicle collision, possible injuries", "location_name": "Silk Board, Bengaluru", "lat": 12.917, "lon": 77.623, "location_source": "SIMULATED_STATIC_PLACE_MATCH"})
    assert created.status_code == 201
    incident_id = created.json()["incident_id"]
    investigated = client.post("/api/agents/run", json={"incident_id": incident_id})
    assert investigated.status_code == 200 and investigated.json()["incident"]["status"] == "AWAITING_APPROVAL"
    drafts = client.get(f"/api/communications?incident_id={incident_id}").json()["drafts"]
    assert {draft["department"] for draft in drafts} == {"POLICE", "HOSPITAL"}
    assert all(draft["status"] == "AWAITING_APPROVAL" for draft in drafts)
    police = next(draft for draft in drafts if draft["department"] == "POLICE")
    assert client.post(f"/api/communications/{police['id']}/send", json={"actor": "demo_commander", "role": "COMMANDER"}).status_code == 409
    approved = client.post(f"/api/communications/{police['id']}/approve", json={"actor": "demo_commander", "role": "COMMANDER"})
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED"
    simulated = client.post(f"/api/communications/{police['id']}/simulate-send", json={"actor": "demo_commander", "role": "COMMANDER"})
    assert simulated.status_code == 200 and simulated.json()["status"] == "SIMULATED"
    assert simulated.json()["smtp_result"]["status"] == "SIMULATED_NO_EXTERNAL_DELIVERY"
    assert any(event["type"] == "communication_simulated_send" for event in core._state["audit"])


def test_final_demo_case_local_camera_evidence_creates_incident_and_starts_agents():
    core.reset_state()
    app = FastAPI(); app.include_router(core.kavach_router)
    client = TestClient(app)
    camera = client.post("/api/cameras", json={"camera_id": "CAM-SB-01", "name": "Silk Board webcam", "location_name": "Silk Board, Bengaluru", "lat": 12.917, "lon": 77.623})
    assert camera.status_code == 200
    assert client.post("/api/cameras/CAM-SB-01/start").json()["status"] == "ONLINE"
    ok, encoded = cv2.imencode(".jpg", np.zeros((80, 120, 3), dtype=np.uint8))
    assert ok
    result = client.post("/api/cameras/CAM-SB-01/observations/confirm", data={"incident_type": "collision", "severity": "critical", "description": "Operator confirms possible collision in frame", "detection_type": "OPERATOR_CONFIRMED_CAMERA_REPORT"}, files={"file": ("frame.jpg", encoded.tobytes(), "image/jpeg")})
    assert result.status_code == 201
    incident = result.json()["incident"]
    assert incident["source"] == "CAMERA" and incident["camera_detection"]["status"] == "OPERATOR_CONFIRMED"
    assert incident["camera_detection"]["confidence"] is None and incident["status"] == "AWAITING_APPROVAL"
    evidence = client.get(f"/api/cameras/evidence/{incident['camera_evidence_id']}")
    assert evidence.status_code == 200 and evidence.json()["image_data"].startswith("data:image/jpeg;base64,")
    assert any(event["type"] == "vision_confirmation" for event in core._state["audit"])


def test_gemini_voice_uses_constrained_ephemeral_token_without_disclosing_api_key(monkeypatch):
    core.reset_state()
    monkeypatch.setenv("GEMINI_API_KEY", "never-return-this-test-key")
    core._gemini_token_issued_at = 0
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return b'{"name":"ephemeral-test-token"}'

    def fake_open(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["key"] = request.get_header("X-goog-api-key")
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    app = FastAPI(); app.include_router(core.kavach_router)
    client = TestClient(app)
    response = client.post("/api/voice/gemini/token")
    assert response.status_code == 200 and "never-return-this-test-key" not in response.text
    assert response.json()["token"] == "ephemeral-test-token"
    assert captured["key"] == "never-return-this-test-key"
    constraints = captured["body"]["liveConnectConstraints"]
    assert constraints["model"] == "models/gemini-3.5-transcribe-live"
    assert constraints["config"]["inputAudioTranscription"]["languageCodes"] == []


def test_email_smtp_only_uses_configured_recipient_and_reports_smtp_acceptance(monkeypatch):
    from email_service import send_configured_email
    monkeypatch.setenv("KAVACH_EMAIL_ENABLED", "true")
    monkeypatch.setenv("KAVACH_EMAIL_HOST", "smtp.gmail.com")
    monkeypatch.setenv("KAVACH_EMAIL_PORT", "465")
    monkeypatch.setenv("KAVACH_EMAIL_SECURE", "true")
    monkeypatch.setenv("KAVACH_EMAIL_USER", "sender@example.test")
    monkeypatch.setenv("KAVACH_EMAIL_APP_PASSWORD", "never-log-this")
    monkeypatch.setenv("KAVACH_POLICE_EMAIL", "police@example.test")
    seen = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout): seen.update({"host": host, "port": port, "timeout": timeout})
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def login(self, user, password): seen.update({"user": user, "password": password})
        def send_message(self, message): seen["recipient"] = message["To"]; return {}

    monkeypatch.setattr("email_service.smtplib.SMTP_SSL", FakeSMTP)
    result = send_configured_email("POLICE", "police@example.test", "KAVACH test", "Test body")
    assert result["status"] == "SENT" and result["acceptedBySmtp"] is True and result["deliveryVerified"] is False
    assert seen["recipient"] == "police@example.test" and seen["password"] == "never-log-this"
    assert send_configured_email("POLICE", "attacker@example.test", "wrong", "wrong")["status"] == "BLOCKED"


def test_gemini_incident_advisory_is_structured_and_cannot_leak_server_key(monkeypatch):
    from gemini_agents import analyze_incident
    monkeypatch.setenv("GEMINI_API_KEY", "never-return-this-test-key")
    captured = {}

    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self, _limit):
            return json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps({
                "summary": "Verify the reported collision with an operator.",
                "hazards_to_check": ["Check for blocked lanes"],
                "data_uncertainties": ["Camera confirmation is unavailable"],
                "candidate_message": "Please review the scene.",
            })}]}}]}).encode()

    def fake_open(request, timeout):
        captured["headers"] = dict(request.header_items())
        captured["body"] = request.data.decode()
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    result = analyze_incident({"incident_type": "collision", "severity": "high", "location_name": "Demo", "description": "test"},
                              [{"agent": "traffic", "findings": ["A lane needs review"]}])
    assert result["status"] == "AVAILABLE" and result["classification"] == "MODEL_SUGGESTION"
    assert result["hazards_to_check"] == ["Check for blocked lanes"]
    assert "never-return-this-test-key" not in json.dumps(result)
    assert "never-return-this-test-key" not in captured["body"]
    assert captured["headers"].get("X-goog-api-key") == "never-return-this-test-key"


def test_gemini_incident_advisory_falls_back_when_key_missing(monkeypatch):
    from gemini_agents import analyze_incident
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = analyze_incident({"incident_type": "fire"}, [])
    assert result["status"] == "UNAVAILABLE" and result["mode"] == "LOCAL_FALLBACK"
