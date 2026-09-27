# KAVACH

**City emergency coordination demo**

KAVACH is a local-first emergency operations prototype based on the CrisisFlow repository. It combines an interactive Bengaluru map, a deterministic incident workflow, specialist agents, route and resource recommendations, camera evidence intake, voice commands, and approval-gated communications.

> **Operational status:** This is a demonstration and engineering prototype, not a production emergency dispatch system. Inventory, response resources, hospital capacity, and most city conditions are seeded or simulated. Do not use it to direct real emergency response.

## What works in this checkout

- **Command dashboard:** interactive 2D/3D map, incident intake, selected-incident details, event stream, status panels, and map-based location selection.
- **Incident workflow:** reports and operator-confirmed camera observations create incidents; ten deterministic agents evaluate the current local dataset, calculate a route and resource recommendation, create communication drafts, and leave the plan awaiting explicit approval.
- **Gemini advisory:** when `GEMINI_API_KEY` is configured, the backend sends a minimal incident summary and specialist findings to Gemini and displays its advisory. Gemini cannot dispatch resources, choose the approved route, or authorize communications. If the provider is unavailable, the deterministic workflow continues.
- **Voice:** browser speech recognition works without a key; optional Gemini Live transcription uses a short-lived backend-minted token. Transcribed commands are parsed by deterministic rules, and sensitive actions still require operator confirmation/approval. Speech output uses the browser.
- **Camera:** local browser-camera frame capture and operator confirmation are supported. Automatic visual event detection is unavailable unless a compatible, licensed model is installed and configured; the UI does not claim detections it has not made.
- **Communications:** drafts can be reviewed, edited, approved, rejected, or simulated. Actual email is disabled until SMTP settings and fixed department recipients are configured; it requires approval and an additional explicit send action.
- **Audit and state:** backend events stream over SSE; this development build stores operational state and uploaded evidence in process memory.

## Quick start on Windows

Requirements: Python 3.11 or newer, Node.js 20 or newer, and npm. No API key or MongoDB server is required for the default local demo.

```powershell
# Terminal 1: backend
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

```powershell
# Terminal 2: frontend
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Open the URL printed by Vite (normally [http://127.0.0.1:5173](http://127.0.0.1:5173)). The backend API is normally at [http://127.0.0.1:8000](http://127.0.0.1:8000), with interactive API documentation at `/docs`.

For the supplied local development environment, set your own API key only in `backend/.env`. The file is ignored by Git. Never place provider keys in frontend source, commit them, or share them in screenshots/logs. Restart the backend after changing environment settings.

### Optional Gemini setup

Set these backend environment variables:

```dotenv
GEMINI_API_KEY=your_google_ai_studio_key
GEMINI_AGENT_MODEL=gemini-3.8-flash
GEMINI_LIVE_TRANSCRIBE_MODEL=gemini-3.5-transcribe-live
```

The same server-side key enables incident advisory analysis and the short-lived token flow for Gemini Live voice transcription. Without it, local deterministic agents and browser speech remain usable. Gemini API access, model availability, quotas, and any free tier are governed by Google and can change; check [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) and [Live API documentation](https://ai.google.dev/gemini-api/docs/live). Do not assume a free quota is suitable for operational use.

### Optional email setup

Email is off by default. To enable SMTP, configure `KAVACH_EMAIL_ENABLED=true`, host/port/TLS, `KAVACH_EMAIL_USER`, `KAVACH_EMAIL_APP_PASSWORD`, and the fixed recipient for each relevant department (`KAVACH_POLICE_EMAIL`, `KAVACH_HOSPITAL_EMAIL`, `KAVACH_FIRE_EMAIL`, `KAVACH_TRAFFIC_EMAIL`, `KAVACH_MUNICIPAL_EMAIL`) in `backend/.env`. Use an app password or dedicated SMTP credential. The UI restricts sending to configured recipients. A successful SMTP response confirms server acceptance only; it does not confirm delivery or receipt.

## Two demo walkthroughs

### 1. Collision response and route replan

1. Open **Report Incident**, choose **Major accident**, **Critical**, **Silk Board**, and enter a short demo description.
2. Activate KAVACH. The backend runs the deterministic specialists, computes a local route/resource recommendation, opens relevant communication drafts, and streams audit events.
3. Review the response plan and optional Gemini advisory. Approve the response plan. This approval is local to this prototype and does not contact responders.
4. Inject a demo road block and request a replan. Review the updated route and draft communications. Use **Simulate send** to demonstrate the mail workflow without sending email.

### 2. Camera-confirmed road hazard

1. Open **Connect Camera** and allow camera access in the browser if using a local webcam.
2. Select **Road hazard**, describe a visible test condition, and submit only what you have personally observed.
3. KAVACH captures a frame, labels the report as operator-confirmed, creates the incident, and starts the response workflow. The UI explicitly reports that automatic vision detection is unavailable.
4. Inspect the stored demo evidence and agent results. Reject or approve the plan as appropriate; use simulated communications for the walkthrough.

Camera access is optional. For a no-hardware demo, use the incident report flow in walkthrough 1 instead.

## Validation

Run backend tests from the repository root:

```powershell
cd backend
.\venv\Scripts\Activate.ps1
python -m pytest -q
```

Run frontend static checks and production build:

```powershell
cd frontend
npm run lint
npm run build
```

## Architecture and API

- `backend/main.py` — FastAPI app, CORS, routers, and startup.
- `backend/kavach_core.py` — local incident state machine, deterministic specialist workflow, route planning, camera intake, communications review, and event stream.
- `backend/gemini_agents.py` — optional server-side Gemini advisory integration. It receives bounded incident fields and specialist summaries only.
- `backend/providers_v3.py` — provider contracts, city data adapters, and capability status.
- `backend/voice.py` — voice provider status and deterministic command parsing.
- `frontend/src/App.tsx` — command dashboard and incident workflows.
- `frontend/src/voice/geminiLive.ts` — optional browser microphone-to-Gemini Live session using an ephemeral token.

Useful endpoints include `GET /api/health`, `GET /api/providers/health`, `GET /api/city/state`, `POST /api/kavach/incidents`, `POST /api/agents/run`, `POST /api/voice/gemini/token`, `GET /api/events/stream`, and `/api/communications`. See the FastAPI docs at `/docs` for the complete schemas and routes.

## Data, privacy, and safety boundaries

- Default demo inventory, locations, capacities, traffic, and route conditions are simulated or bundled snapshots. Provider status and timestamps identify live/cached/unavailable data where implemented; a green UI state is not proof of operational data quality.
- Reports, camera frames, drafts, and incident state are process-memory data in this build. Restarting the backend clears them. There is no production identity provider, role-backed authorization, tenant separation, durable audit store, or tested failover.
- Gemini is an external processor when enabled. The integration sends only incident type, severity, location label, description, and bounded deterministic agent findings. Do not submit personal or sensitive data. Advisory text is untrusted and requires human review.
- The demo role selector and client commands are not a security boundary. API authorization must be replaced with trusted server-side identity before deployment.
- Actual email can contact configured external addresses once SMTP is enabled. Keep it disabled during demos unless you intentionally configure a test mailbox.
- Map tiles and bundled data have their own provider attribution and licensing; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [DATA_SOURCES.md](DATA_SOURCES.md).

## Production readiness

**Prototype readiness: suitable for a supervised local demo. Production emergency-response readiness: not ready.** Before real deployment, KAVACH needs a threat model and security review; authenticated, audited authorization; durable and resilient storage; validated/licensed live operational data; model and route validation against real scenarios; human-factors and accessibility testing; privacy/retention controls; provider failure handling; deployment observability and recovery; and formal acceptance by the responsible emergency agencies. Do not connect this prototype to real dispatch systems.

See [START_KAVACH.md](START_KAVACH.md), [API_KEYS_REQUIRED.md](API_KEYS_REQUIRED.md), [DEMO_SCRIPT.md](DEMO_SCRIPT.md), [SECURITY.md](SECURITY.md), [CAMERA_ARCHITECTURE.md](CAMERA_ARCHITECTURE.md), [EMAIL_ARCHITECTURE.md](EMAIL_ARCHITECTURE.md), and [PHASE_FINAL_IMPLEMENTATION_REPORT.md](PHASE_FINAL_IMPLEMENTATION_REPORT.md) for details.
