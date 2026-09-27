"""Voice-provider status and deterministic, audited command normalization."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class VoiceProvider:
    name = "VoiceProvider"

    def getStatus(self) -> dict[str, Any]:
        raise NotImplementedError

    def transcribe(self, transcript: str) -> str:
        return " ".join(transcript.strip().split())


class BrowserVoiceProvider(VoiceProvider):
    name = "Browser Web Speech API"

    def getStatus(self) -> dict[str, Any]:
        return {"name": self.name, "status": "available", "mode": "LOCAL", "configured": True, "requiresAuth": False, "error": None, "capabilities": ["browser_microphone", "browser_speech_recognition", "browser_speech_synthesis"]}


class AssemblyAIVoiceProvider(VoiceProvider):
    name = "AssemblyAI Streaming STT"

    def getStatus(self) -> dict[str, Any]:
        configured = bool(os.getenv("ASSEMBLYAI_API_KEY", "").strip())
        return {"name": self.name, "status": "available" if configured else "NOT_CONFIGURED", "mode": "LIVE" if configured else "UNAVAILABLE", "configured": configured, "requiresAuth": True, "error": None if configured else "ASSEMBLYAI_API_KEY is not set", "capabilities": ["streaming_transcription", "temporary_browser_token"]}


class GeminiLiveVoiceProvider(VoiceProvider):
    name = "Gemini Live Transcription"

    def getStatus(self) -> dict[str, Any]:
        configured = bool(os.getenv("GEMINI_API_KEY", "").strip())
        return {"name": self.name, "status": "available" if configured else "NOT_CONFIGURED", "mode": "LIVE" if configured else "UNAVAILABLE", "configured": configured, "requiresAuth": True, "error": None if configured else "GEMINI_API_KEY is not set", "capabilities": ["streaming_transcription", "ephemeral_browser_token", "command_transcription"]}


class MockVoiceProvider(VoiceProvider):
    name = "MockVoiceProvider"

    def getStatus(self) -> dict[str, Any]:
        return {"name": self.name, "status": "available", "mode": "SIMULATED", "configured": True, "requiresAuth": False, "error": None, "capabilities": ["test_transcripts"]}


_PLACES: tuple[tuple[str, float, float], ...] = (
    ("Silk Board", 12.9170, 77.6230),
    ("Koramangala", 12.9350, 77.6200),
    ("HSR Layout", 12.9180, 77.6440),
    ("Bellandur", 12.9250, 77.6680),
    ("Sarjapur Road", 12.9100, 77.6740),
)


def parse_voice_command(transcript: str) -> dict[str, Any]:
    text = " ".join(transcript.strip().split())
    normalized = re.sub(r"^kavach[,: ]+", "", text, flags=re.I).casefold()
    place = next((item for item in _PLACES if item[0].casefold() in normalized), None)
    location: dict[str, Any] | None = None
    if place:
        location = {"name": place[0], "text": place[0], "lat": place[1], "lon": place[2], "lng": place[2], "locationSource": "SIMULATED_STATIC_PLACE_MATCH", "confirmed": False}
    else:
        match = re.search(r"\bnear\s+([\w -]{2,80}?)(?:[,.?!]|$)", text, re.I)
        if match:
            label = match.group(1).strip()
            location = {"name": label, "text": label, "lat": None, "lon": None, "lng": None, "locationSource": "UNRESOLVED", "confirmed": False}

    rules: tuple[tuple[str, tuple[str, ...], float, bool], ...] = (
        ("RESET_DEMO", ("reset demo", "restart demo", "reset the scenario"), 0.97, False),
        ("APPROVE_PLAN", ("approve", "authorize", "authorise", "approve the plan"), 0.96, True),
        ("VERIFY_INCIDENT", ("verify", "check resolution", "confirm resolved"), 0.9, False),
        ("REPLAN", ("replan", "reroute", "route again", "block the current route", "what changed"), 0.93, True),
        ("SIMULATE_RESPONSE", ("simulate sending an ambulance", "simulate ambulance", "simulate response", "simulate the response", "ambulance simulation", "dispatch ambulance"), 0.92, True),
        ("EXECUTE_RESPONSE", ("execute", "carry out the approved plan", "execute response"), 0.95, True),
        ("INVESTIGATE_INCIDENT", ("investigate", "major accident", "traffic accident", "collision", "fire incident"), 0.9, True),
        ("CREATE_RESPONSE_PLAN", ("create an emergency response plan", "create response plan", "prepare a response", "prepare response", "plan the response"), 0.91, True),
        ("PRIORITIZE_INCIDENT", ("prioritize", "prioritise", "raise priority"), 0.9, True),
        ("FIND_HOSPITAL", ("hospital", "medical capacity", "emergency capacity", "beds available"), 0.91, False),
        ("FIND_AMBULANCE", ("find an ambulance", "available ambulance", "nearest ambulance"), 0.9, False),
        ("FIND_FIRE_RESOURCE", ("fire station", "fire stations", "fire resources", "fire engine"), 0.9, False),
        ("FIND_POLICE_RESOURCE", ("police station", "police resource", "police unit", "police jurisdiction"), 0.9, False),
        ("CALCULATE_ROUTE", ("fastest emergency corridor", "fastest route", "best route", "emergency corridor", "calculate the route"), 0.92, False),
        ("CHECK_ROUTE", ("route blocked", "check whether the route", "check if the route", "is the route blocked"), 0.9, False),
        ("SHOW_DELAYS", ("what is delaying", "delaying the response", "response delay", "delays"), 0.88, False),
        ("ANALYZE_ROAD", ("analyze this road", "analyse this road", "analyze road", "analyse road", "road hazards", "pothole", "road damage", "road hazard"), 0.88, False),
        ("GET_AGENT_STATUS", ("agent status", "which agents", "what are the agents"), 0.9, False),
        ("GET_CITY_STATUS", ("city situation", "what is happening", "current situation", "city status", "status of the city", "emergency status"), 0.94, False),
    )
    intent = "UNKNOWN"
    confidence = 0.0
    requires_approval = False
    matches: list[tuple[str, float, bool]] = []
    for candidate, phrases, score, approval in rules:
        if any(phrase in normalized for phrase in phrases):
            matches.append((candidate, score, approval))
    if matches:
        matches.sort(key=lambda item: item[1], reverse=True)
        if len(matches) > 1:
            intent, confidence = "AMBIGUOUS", 0.0
        else:
            intent, confidence, requires_approval = matches[0]

    incident_type = None
    if any(term in normalized for term in ("accident", "collision", "crash")):
        incident_type = "ACCIDENT"
    elif "fire" in normalized:
        incident_type = "FIRE"
    elif any(term in normalized for term in ("flood", "waterlogging")):
        incident_type = "FLOOD"
    elif any(term in normalized for term in ("pothole", "road damage", "road hazard", "crack")):
        incident_type = "ROAD_DAMAGE"
    severity = "CRITICAL" if any(term in normalized for term in ("critical", "major", "serious")) else "HIGH"
    confirmation = intent in {"INVESTIGATE_INCIDENT", "SIMULATE_RESPONSE"} and (location is None or not location.get("lat"))
    if intent == "AMBIGUOUS":
        confirmation = True
    public_intent = {"APPROVE_RESPONSE": "APPROVE_PLAN", "REPLAN_ROUTE": "REPLAN", "SIMULATE_AMBULANCE": "SIMULATE_RESPONSE", "FIND_HOSPITALS": "FIND_HOSPITAL", "FIND_FIRE_STATIONS": "FIND_FIRE_RESOURCE", "FASTEST_CORRIDOR": "CALCULATE_ROUTE", "ROAD_HAZARDS": "ANALYZE_ROAD", "CITY_SITUATION": "GET_CITY_STATUS"}.get(intent, intent)
    return {
        "transcript": text, "command": public_intent.lower(), "intent": public_intent, "legacyIntent": intent,
        "incident_type": incident_type, "incidentType": incident_type,
        "location": location, "priority": severity.lower(), "severity": severity,
        "requestedAction": intent if requires_approval else None,
        "confidence": confidence, "parser": "KAVACH_DETERMINISTIC_INTENT_RULES",
        "requiresApproval": requires_approval, "confirmationRequired": confirmation,
    }
