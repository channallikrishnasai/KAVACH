# KAVACH Phase 2 Architecture Audit

Audit date: 2026-09-27. This audit records the checked-in workspace and a live local run; it does not infer production readiness from the demo.

## Verification performed before changes

- Backend `/health` returned `healthy`, `database=simulated_memory`, `stgcn=simulation`, `prediction_provider=SIMULATION`, `demo_mode=true`.
- Frontend `/` returned HTTP 200. Browser accessibility inspection showed the KAVACH 3D map, OSM/CARTO/Mapzen attributions, provider labels, ten agent entries, command input, and demo controls.
- `python -m pytest -q` passed: 7 tests (one PyTorch deprecation warning).
- `npm run lint` and `npm run build` had passed in the prior implementation turn. The existing production build is runnable; map/frontend JavaScript chunks are large.
- `python demo.py` completed the deterministic incident/agents/approval/execution/verification/road-block/replan/reapproval/resolution sequence.
- HTTP smoke checks returned: 8 seeded resources, 5 zones, 2 hospitals, legacy dashboard HTTP 200, and `/simulate` with provider `SIMULATION`/state `SIMULATED`. `/weather` returned a successful live Open-Meteo response during the prior verified request; this can change with network access.

## Architecture and status after Phase 2 changes

| Subsystem | Status | Evidence and current boundary |
|---|---|---|
| Frontend / 3D city view | WORKING / PARTIAL | React, TypeScript, Vite, Deck.gl and MapLibre. Pitched KC Valley view uses bundled footprints/roads/water and no-key third-party basemap/terrain. It is a local extent, not a full-city photogrammetric twin; the OSM snapshot date is unknown. |
| FastAPI and legacy routes | WORKING / PARTIAL | `backend/main.py` combines STGCN/geospatial endpoints, KAVACH routes, and CrisisFlow CRUD routers. `mongomock-motor` keeps legacy CRUD available in volatile local demo mode when MongoDB is down. |
| Database | PARTIAL | Motor/MongoDB and legacy collections/models exist. Local fallback is in-memory and nonpersistent. KAVACH incident, evidence, agent and audit state is currently in process memory, not persisted to those Mongo collections. |
| Event bus / activity stream | PARTIAL | `_event` appends actual state changes to the in-memory audit list; frontend refreshes and renders those events. There is no durable broker, WebSocket or SSE stream. |
| Ten-agent network | WORKING (DETERMINISTIC) | Ten typed specialists produce findings, tool labels, evidence, confidence and recommendations. They use local city/asset state and bundled graph; they are not LLM agents and the summaries do not expose hidden chain-of-thought. |
| Provider system | PARTIAL | `backend/providers.py` provides typed provenance/freshness results for Open-Meteo and configured data.gov.in resource requests. `/api/providers`, `/api/providers/status`, `/api/providers/government/data`, and `/api/weather` expose status. Weather is live when the request succeeds, then cached or simulated; data.gov.in has no configured resource. Operational feeds remain unavailable/simulated. |
| Hospital / emergency inventory | SIMULATED | Three KAVACH facility records and three response resources in the command core; legacy Mongo seed has 2 hospitals and 8 resources. These are demonstration inventory, not live capacity/location. |
| Approval / action executor | PARTIAL | State machine rejects execution before approval, enforces a caller-supplied role policy, and records local simulated resource reservation. Role labels are not identity: authenticated RBAC remains missing. |
| Verification / replanning | WORKING (DETERMINISTIC) | Local state is checked after execute. Road-closure injection blocks a real node in the bundled graph, recalculates a path, and requests fresh approval. Replanning does not represent external world observation. |
| Flood prediction | SIMULATED FALLBACK | STGCN source and weights remain, but required `val_dataset.pt` is absent. Startup reports the unavailable model; `/simulate` computes an explicitly labeled deterministic graph-based surface. |
| Road intelligence | PARTIAL / HUMAN REVIEW | Image/video decoding, local contrast cues, OCR via browser Tesseract.js, EXIF GPS parsing, and map-confirmed incident creation. No damage classifier is enabled; cues are not pothole/crack detections. |
| Voice | PARTIAL | Browser speech recognition/synthesis calls a backend deterministic intent parser. Supported intents route through existing UI lifecycle handlers; no AssemblyAI/Gemini streaming provider is connected. Static location matches are simulated. |
| Communications / n8n | PARTIAL / LOCAL BY DEFAULT | Local adapter records only. Optional n8n webhook adapter requires fixed URL, explicit enable flag, non-demo mode and an approved incident. It is not authenticated for production use; leave disabled. |
| Authentication / RBAC | MISSING | No login/identity store. Approval is a state transition initiated by local UI controls, and the actor string alone does not authenticate or authorize a person. |
| Real data connectors | PARTIAL / MOSTLY MISSING | Bundled OSM snapshot, CARTO basemap, Mapzen AWS terrain, Open-Meteo and a generic credentialed data.gov.in resource connector are present. No resource ID is selected; Bengaluru open data, traffic, ambulance, hospital, fire and police operational feeds are not connected. |
| API/configuration | PARTIAL | Root/backend `.env` is ignored; backend `.env.example` names optional provider settings. No live operational credentials are present. |
| Tests | WORKING | Expanded backend suite: 23 passed; Python compileall, frontend lint, frontend production build, CLI lifecycle demo and HTTP smoke checks passed. Vite notes the large map/application chunks; one PyTorch deprecation warning is upstream. |
| External OPERO source | AVAILABLE / AUDITED | Local `D:\The Opero\The Opero` source includes an MIT `LICENSE`. Its README/requirements describe a Gemini action/TTS brain and optional AssemblyAI realtime transcription; its adapter depends on the AssemblyAI SDK, local microphone/audio stack and an AssemblyAI key. No OPERO source/assets/credentials are copied. Its boundaries are useful design patterns only. |

## Runtime components and configuration checked

- Frontend: `frontend/src/App.tsx`, `frontend/src/kavach.css`, `frontend/src/components/MapView.tsx`; Vite development server on port 5173.
- Backend: `backend/main.py`, `backend/kavach_core.py`, `backend/api.py`, existing `backend/routers/` and `backend/models/`; FastAPI on port 8000.
- Core state and audit currently live in the KAVACH module process. Legacy CRUD uses Motor and seeded records; `mongomock-motor` is the dev fallback.
- Existing `.env`/`.env.example` variables include MongoDB URL/name, forecast URL, `DATAGOV_API_KEY`, LLM, messaging and n8n slots. Empty credential settings are not integrations.
- No AssemblyAI or Gemini key is configured. The existing Web Speech API works without an application key where browser/OS support exists.

## Phase 2 implementation summary

The implementation preserves legacy CRUD, bundled geometry/graph, map layers, STGCN code and KAVACH lifecycle. Weather has live/cache/simulated metadata; data.gov.in has a generic connector pending a real resource ID. Browser speech uses a deterministic backend parser. Agent traces/evidence and local notification logging are explicit. External dispatch remains out of scope and is not enabled. Role checks are policy gates only because no login/identity system exists. See [REAL_DATA_STATUS.md](REAL_DATA_STATUS.md), [VOICE_ARCHITECTURE.md](VOICE_ARCHITECTURE.md), [AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md), and [PHASE2_IMPLEMENTATION_REPORT.md](PHASE2_IMPLEMENTATION_REPORT.md).
