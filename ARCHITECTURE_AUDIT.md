# KAVACH Architecture Audit

Audit date: 2026-09-27. Workspace: extracted CrisisFlow source under `D:\CrisisFlow-main`. The linked `channallikrishnasai/KAVACH` repository currently contains only `LICENSE` (Apache-2.0) and an 8-byte `README.md`; it has no code to integrate.

## Existing architecture

- **Frontend:** React 19, TypeScript, Vite 8, Deck.gl 9, MapLibre 5. The KAVACH command view makes the pitched 3D KC Valley map central, with OSM-derived building extrusions, water, routes, closure markers and Mapzen Terrarium terrain. Visible map attribution is retained. A legacy CrisisFlow operations view remains available.
- **Backend:** FastAPI in `backend/main.py`, with optional STGCN/geospatial routes in `backend/api.py`, KAVACH incident/agent/simulation APIs in `backend/kavach_core.py`, and the original CRUD routers under `backend/routers/`. Startup command: `python main.py`.
- **Data store:** Motor/MongoDB when configured; local startup falls back to `mongomock-motor` in-memory persistence if MongoDB is unavailable. The fallback is reset on restart and is for development/demo only.
- **Flood model:** PyTorch/PyG model weights and checkpoint are present. Importing `api.py` unconditionally loads missing `backend/val_dataset.pt`; there is no dataset builder or download workflow. `dataset_meta.json` is metadata only. `train.py` consumes both train and validation datasets; it does not generate them.
- **Map assets:** `kc_valley_area.osm`, `kc_valley_focused.graphml`, building/water GeoJSON, and `deckgl_basemap.json` are present. The README describes Bengaluru, but the local extract covers the KC Valley basin rather than the whole city.
- **Weather:** `/weather` requests Open-Meteo with cached/simulated fallback and provider provenance; availability depends on network and non-commercial provider terms.
- **Routing:** NetworkX/OSMnx routes over the local GraphML network, including flood penalties and Mongo road-block reads.
- **Incidents/resources/hospitals/road blocks:** Mongo-backed CRUD and role dashboards. `seed.py` creates demo-like records; they should be identified as seeded/demo data, not live city feeds.
- **AI vision:** Road media accepts images and videos, extracts local contrast cues, runs browser-side Tesseract OCR, and requires human confirmation of a map location when GPS metadata is absent. It does not classify potholes/cracks because no detector with verified compatible model and training data license was available.
- **Voice:** Browser speech recognition maps supported spoken commands to the same command handlers as typed commands, and browser speech synthesis reads key outcomes using the browser's available default voice. Browser support and microphone permission vary; there is no provider-backed voice catalog or configurable remote STT/TTS integration.
- **Agents and approvals:** Ten deterministic specialists produce structured findings, evidence, confidence, route and resource recommendations. The API records explicit approval before local simulated execution and verifies local state changes. It is not authenticated multi-user RBAC and cannot dispatch real emergency services.
- **Audit/event stream:** Incident transitions and local actions are recorded in an in-memory event log. No WebSocket/SSE transport is implemented; UI refresh polls the APIs.

## Runtime verification already performed

- Frontend lint and production build succeeded after KAVACH UI/map changes.
- `python main.py` now starts with STGCN explicitly unavailable and a deterministic simulation prediction provider; KAVACH command APIs remain usable.
- With local MongoDB stopped, startup successfully initialized indexes and seeded legacy collections using the in-memory compatibility store.
- `python demo.py` exercised incident creation, ten agents, approval, local execution/verification, injected road closure, route recalculation, renewed approval and final verification.
- Backend automated tests cover agent structure, approval gate, execution, route-changing simulation, road-media cues/GPS requirements, and API lifecycle.

## Current data status

- Local city geometry and road graph: bundled OSM-derived snapshot; static, freshness unknown; ODbL attribution needs to be displayed and source/collection date verified.
- Weather: Open-Meteo endpoint configured; can be live when fetched; otherwise fallback data is visibly labeled. Free endpoint is for non-commercial use and requires attribution.
- Operational incidents/resources/hospitals: local MongoDB only; current seed data is simulated/demo data, not a verified live Bengaluru feed.
- Government/open data: no connector currently exists.
- Traffic/ambulance/fire operational feeds: no verified public live API connector currently exists.
- STGCN: model weights exist, but required input artifact is missing, so the model is not operational in this checkout.

## Dependencies and configuration

- Backend requirements are unpinned (`fastapi`, `uvicorn`, `torch`, `torch-geometric`, OSMnx/geospatial packages, Motor, etc.).
- Frontend has a committed npm lockfile; Node 18+ is documented, though Vite 8 may require a newer supported Node runtime. Verify `node --version` before choosing an install recipe.
- Root `.env` contains MongoDB and Open-Meteo values. No API key is currently present. Frontend defaults to `http://127.0.0.1:8000`.
- No root `.gitignore` was present when audited; the backend ignore file excludes `*.pt`, which explains why model datasets are omitted from Git.

## Migration strategy

1. Keep CrisisFlow CRUD, map data, routing, and STGCN source intact; make the missing STGCN artifact an optional capability and clearly label the deterministic simulation fallback.
2. Make the core local demo boot without MongoDB and without secrets; retain MongoDB as a configurable persistent provider.
3. Add deterministic typed agent orchestration, an auditable incident lifecycle, permission-gated approval/execution, and road-block-triggered route replanning using the existing road graph.
4. Keep external actions disabled by default. Provide notification adapters that prepare local events until a provider is deliberately configured and approved.
5. Upgrade the existing city map in place: start in 3D, retain the Bengaluru/KC Valley OSM geometry, add clear OSM/CARTO attribution and visible data-state labels. Do not claim full-city coverage or live feeds.
6. Add voice through browser speech APIs where available, with typed command fallback. Keep the same server-side authorization path for both.
7. Add road-image ingestion as a separately labeled capability. No detector weights/dataset are bundled yet; do not claim pothole ML until a licensed model is installed and validated.

## Main risks / blockers

- Missing `val_dataset.pt` and undocumented preprocessing lineage block the actual STGCN model.
- MongoDB is not running locally; development uses volatile in-memory Mongo-compatible persistence. Configure MongoDB for persistence.
- A reliable, licensed live Bengaluru traffic/ambulance/fire/hospital source has not been verified. Public static datasets must not be represented as live.
- External messaging and LLM providers require credentials; they are not needed for a deterministic local demo.
- Base map display depends on third-party tile/style hosts unless tiles are self-hosted. The free route is for development/non-commercial demo use and depends on provider terms and attribution.
