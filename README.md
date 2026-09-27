# KAVACH

**City emergency coordination demo**

KAVACH is a local-first emergency operations prototype based on the CrisisFlow repository. It combines a Bengaluru city map, deterministic incident-response automation, route and resource recommendations, camera evidence intake, voice commands, and approval-gated communications.

> **Demo only.** KAVACH is not a production emergency dispatch system. Inventory, response resources, hospital capacity, and most city conditions are seeded or simulated. Never use it to direct a real emergency response.

## Feature status

| Area | What the demo does | Data/action boundary |
|---|---|---|
| Command map | Interactive 2D/3D Bengaluru map with buildings, roads, incident markers, and event status | Bundled map snapshot; not photogrammetry; map dates and live-data limits are shown in the UI |
| Incident intake | Create an incident from the report form or an operator-confirmed camera observation | Known demo locations use fixed coordinates; incidents are held in process memory |
| Agent automation | Ten deterministic specialists assess the report, calculate local routes, recommend resources, and prepare communication drafts | Recommendations use simulated/demo inventory and always require approval |
| Gemini advisory | Optional server-side advisory for hazards, uncertainties, and a short summary | Key remains backend-only; advice cannot dispatch, choose authorized resources, or approve actions; local agent plan continues if unavailable |
| Voice commands | Browser voice or optional Gemini Live transcription; deterministic intent parsing | High-impact actions require explicit operator approval; voice output uses browser speech |
| Camera | Local webcam frame capture and operator confirmation | Automatic vision detection is unavailable unless a supported licensed model is installed; no false detections are shown |
| Communications | Review, edit, approve, reject, or simulate sending emails | SMTP is disabled by default; actual send needs configured fixed recipients and explicit approval/send |
| Event/audit stream | SSE events for incident state changes and agent outcomes | In-memory audit history; it resets when the backend restarts |

## Automated workflows

| Trigger | Automated steps | Human checkpoint | Visible result |
|---|---|---|---|
| **Activate KAVACH** on the incident form | Create incident → assign ten specialists → compute a road-graph route and resource recommendation → draft department messages → publish audit events | Response plan pauses at `AWAITING_APPROVAL` | Incident list, map focus, agent findings, route/hospital recommendation, communication drafts, and approval button |
| Confirm a camera observation | Capture JPEG → hash and store evidence in process memory → create a camera-sourced incident → run the same incident workflow | Operator must confirm the observed event; plan approval remains explicit | Evidence frame, incident provenance, agents, route plan, and approval status |
| Request replan / add a road block | Update simulated road state → recalculate specialist findings and routes → regenerate draft communications | Revised plan returns to `AWAITING_APPROVAL` | New route, changed audit events, fresh approval step |
| Review a communication | Edit and save draft → approve or reject; simulate-send records a local demo outcome | Actual SMTP send needs approval and a second explicit send action | Draft status and clear indication when no email was sent |
| Submit a voice command | Transcribe → deterministic intent/location parse → route to supported local workflow | Ambiguous location and high-impact actions require confirmation | Transcript, normalized intent, and resulting local action/event |
| Gemini unavailable | Keep deterministic agents, plan, and approval flow operating | No model-provided action is executed | Gemini fallback status; local workflow remains usable |

## Run locally on Windows

Requirements: Python 3.11+, Node.js 20+, and npm. The local demo needs no API key or MongoDB server.

Open two PowerShell terminals from the repository root.

**Terminal 1 — backend**

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
$env:API_PORT = '8001'
python main.py
```

**Terminal 2 — frontend**

```powershell
cd frontend
npm ci
$env:KAVACH_API_PROXY_TARGET = 'http://127.0.0.1:8001'
npm run dev -- --host 127.0.0.1
```

Open the Vite URL shown in the terminal (usually [http://127.0.0.1:5173](http://127.0.0.1:5173)). Vite selects the next available port when 5173 is occupied. Its development proxy sends `/api` and map-data requests to the backend without cross-origin browser errors. The backend health endpoint is [http://127.0.0.1:8001/health](http://127.0.0.1:8001/health); API documentation is at `/docs`.

## Gemini setup

Put a Google AI Studio API key in the ignored `backend/.env`, never in frontend source or a committed file. Restart the backend after changing it.

```dotenv
GEMINI_API_KEY=your_google_ai_studio_key
GEMINI_AGENT_MODEL=gemini-3.8-flash
GEMINI_LIVE_TRANSCRIBE_MODEL=gemini-3.5-transcribe-live
```

The key enables optional incident advisory analysis and a short-lived token flow for Gemini Live speech transcription. Browser speech remains available without Gemini. Model availability, quotas, and any free tier are set by Google and can change; review [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) and [Live API documentation](https://ai.google.dev/gemini-api/docs/live). Gemini receives bounded report fields and specialist summaries; do not submit personal or sensitive information.

## Demo case: collision at Silk Board

1. Open **Report Incident**. Select **Major accident**, **Silk Board**, and **Critical**. Use the default demo description or write: “Two-vehicle collision; lane obstruction reported.”
2. Click **Activate KAVACH**. Wait for the agent workflow to finish. The modal closes and the map focuses on the incident; the incident list, specialist findings, route recommendation, and response-plan card become visible.
3. Show the ten specialists and the recommended hospital/route. Explain that resources and capacities are demo data.
4. Click **Approve Plan** to demonstrate the human checkpoint. This does not contact responders.
5. Click **Road Block · Replan** and show the route reassessment and fresh approval requirement.
6. Open the generated police or hospital draft and click **Simulate Send · No Email Sent**. This makes no external communication.

**Short talk track:** “KAVACH turns an incident report into a route-aware response recommendation, coordinates ten local specialists, and holds the plan for operator approval. A simulated closure triggers a new plan; communications stay as drafts unless explicitly approved.”

## Second demo: operator-confirmed camera report

1. Click **Connect Camera** and grant browser camera access if you want to use a webcam.
2. Select **Road hazard**, describe an event you can personally see, and click **Confirm Event and Activate KAVACH**.
3. Show the captured frame and the new camera-sourced incident. Point out that KAVACH is not claiming automatic AI detection.
4. Review the response plan and use the same approval and simulated-message flow.

A webcam is optional. Use the collision workflow for a no-hardware presentation.

## Optional email setup

Email stays disabled by default. To test real email, configure `KAVACH_EMAIL_ENABLED=true`, SMTP host/port/TLS, sender credentials, and fixed department recipient variables (`KAVACH_POLICE_EMAIL`, `KAVACH_HOSPITAL_EMAIL`, `KAVACH_FIRE_EMAIL`, `KAVACH_TRAFFIC_EMAIL`, `KAVACH_MUNICIPAL_EMAIL`) in `backend/.env`. Use a test mailbox. A successful SMTP response means the mail server accepted the message; it does not prove recipient delivery. Never enable real SMTP in a public demo without intended test recipients.

## Render deployment

The repository includes [`render.yaml`](render.yaml) defining a free static frontend and free Python API service. To create them, sign in to Render, choose **New → Blueprint**, and connect this repository. The API service requests `GEMINI_API_KEY` as a secret during initial Blueprint setup; the key is not stored in Git. The frontend build uses the API service URL configured in the Blueprint. The expected addresses are `https://kavach-web.onrender.com` and `https://kavach-api.onrender.com`; Render assigns these only after creating the services, and a name conflict may change them.

Free web services can sleep when idle and take time to start on the next request. The app uses in-memory incident state, so a backend restart clears demo incidents and evidence. The free service has limited CPU and memory; model imports or build limits may require a smaller dependency set or a paid instance. Follow the health check and Render build logs after creation. Official setup details: [Render web services](https://render.com/docs/web-services), [Blueprints](https://render.com/docs/blueprint-spec), and [Render free deploy guide](https://render.com/docs/your-first-deploy).

## Validation

Backend tests:

```powershell
cd backend
.\venv\Scripts\Activate.ps1
python -m pytest -q
```

Frontend checks:

```powershell
cd frontend
npm run lint
npm run build
```

## Architecture

| Path | Responsibility |
|---|---|
| `backend/main.py` | FastAPI app, CORS, health, optional database startup |
| `backend/kavach_core.py` | Deterministic incident state machine, specialist orchestration, route planning, camera intake, communications, and event stream |
| `backend/gemini_agents.py` | Optional Gemini advisory; never dispatches or approves actions |
| `backend/providers_v3.py` | Provider contracts and city-data adapters |
| `backend/voice.py` | Provider status and deterministic command parsing |
| `frontend/src/App.tsx` | KAVACH command dashboard and response workflow |
| `frontend/src/voice/geminiLive.ts` | Browser audio stream using a backend-minted ephemeral token |
| `render.yaml` | Render frontend/API Blueprint |

## Safety, privacy, and known limits

- Incident state, evidence, and audit data are held in process memory and are lost on restart.
- Bundled roads and demo inventory do not establish current operational availability. Check each provider's status and provenance in the interface.
- The demo role selector is not trusted authentication. There is no production identity provider, tenant isolation, or server-enforced agency authorization.
- Gemini output is untrusted advisory text. It cannot select or dispatch resources, approve plans, or send messages.
- Email is external once enabled. Fixed recipients, human approval, and a second send step are required.
- Camera observations are operator-confirmed. A compatible vision model is not included by default.
- Free hosting is for supervised demonstrations only, with cold starts and limited resources. Do not connect this build to a real dispatch system.

See [API_KEYS_REQUIRED.md](API_KEYS_REQUIRED.md), [DEMO_SCRIPT.md](DEMO_SCRIPT.md), [SECURITY.md](SECURITY.md), [DATA_SOURCES.md](DATA_SOURCES.md), [CAMERA_ARCHITECTURE.md](CAMERA_ARCHITECTURE.md), and [EMAIL_ARCHITECTURE.md](EMAIL_ARCHITECTURE.md) for implementation detail.
