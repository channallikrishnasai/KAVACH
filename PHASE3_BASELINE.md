# KAVACH Phase 3 Baseline

Baseline audit date: 2026-09-27. Checks were run against the existing Phase 2 checkout before Phase 3 code changes.

## Verification

| Check | Result | Evidence |
|---|---|---|
| Backend tests | PASS | `backend/venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`: 23 passed, 1 upstream PyTorch deprecation warning; 136.08 s. |
| Python compilation | PASS | `backend/venv/Scripts/python.exe -m compileall -q .` completed successfully. |
| Frontend lint | PASS | `npm run lint` from `frontend`. |
| Frontend build | PASS | `npm run build` from `frontend`; Vite notes large MapLibre/application chunks. |
| Backend startup | PASS | Existing service on `127.0.0.1:8000` returned `/health` healthy, in-memory demo database, STGCN simulation. Fresh venv launch had also completed on port 8001 in Phase 2. |
| Frontend startup/UI | PASS | `127.0.0.1:5173` returned HTTP 200; inspected app showed KAVACH 3D OSM building extrusions, attribution, ten agents, incident panel, road media upload and voice command bar. UI states that it is not photogrammetry and its snapshot date is unknown. |
| End-to-end demo | PASS | `backend/venv/Scripts/python.exe demo.py`: ten specialists, route generated, approval-gated local execute/verify, road closure changed route from 0.45 km to 0.62 km, fresh approval and final resolution. It explicitly reported simulated records and no external actions. |
| Provider status | PARTIAL | Current checkout exposes Open-Meteo and provider status code; prior Phase 2 check returned live weather. The already-running baseline process did not expose `/api/providers/government/data` (404), consistent with its pre-Phase 2 startup image. |

## Provider and feature state

| Capability | Baseline mode | Baseline limitation |
|---|---|---|
| Weather | LIVE/CACHED/SIMULATED | Open-Meteo call; no durable cache and provider status contract is incomplete. |
| Bengaluru roads/routing | CACHED | Bundled OSM graph; no live traffic or closure feed. |
| Hospital inventory/capacity | SIMULATED | Seeded local facility/capacity list; not an operational capacity source. |
| Ambulance/fire/police resources | SIMULATED | Seeded local resources and availability. |
| Government data | UNAVAILABLE | Generic data.gov.in connector requires key plus configured resource; lacks query, pagination, rate limiting and cache behavior. |
| Road damage AI | UNAVAILABLE | Browser image/video/OCR cues only; no licensed detector installed. |
| Voice | LOCAL / PARTIAL | Browser Web Speech plus deterministic phrase parser. No AssemblyAI streaming provider. |
| Authentication | DEMO ONLY | Caller-supplied role labels; no authenticated identity. |
| External actions | DISABLED BY DEFAULT | Local notification event adapter; no real emergency dispatch. |
| STGCN | SIMULATED | `val_dataset.pt` is absent; artifact remains optional. |

## Inspection scope

Reviewed the existing provider module, voice parser, communications adapter, ten-agent contracts and routing/state/approval functions, FastAPI routes, and MapLibre/Deck.gl map component. Phase 3 work starts from these components and preserves the existing demo and CrisisFlow API surface.
