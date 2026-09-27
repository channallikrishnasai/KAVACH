# Start KAVACH locally

## Requirements

- Windows 10/11 with Python 3.10+ and Node.js/npm installed.
- `backend\venv` with `backend\requirements.txt` installed and `frontend\node_modules` available.
- No API key or MongoDB is required for the local simulated demo.

## Run the app

In PowerShell terminal 1:

```powershell
Set-Location D:\CrisisFlow-main\backend
.\venv\Scripts\Activate.ps1
python main.py
```

In PowerShell terminal 2:

```powershell
Set-Location D:\CrisisFlow-main\frontend
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173/`. The API is at `http://127.0.0.1:8000`; Swagger is `/docs`.

Optional settings are in `backend\.env.example`; copy it to `backend\.env` if you want to change endpoints or enable providers. No secrets are needed for the free local demo.

When MongoDB is absent, `mongomock-motor` supplies an in-memory compatibility store for legacy CRUD routes. It resets on restart and is not persistent production storage. KAVACH command-loop state is also in memory. Providers and records marked `SIMULATED` are not live emergency information.

## Free provider options

- The bundled OSM graph and building/water footprints require no key; retain OpenStreetMap attribution and comply with ODbL.
- The 3D terrain tiles are served from AWS Terrain Tiles by Mapzen without a key; the map displays attribution. Availability and third-party terms apply.
- Open-Meteo requires no key for eligible non-commercial use: [API terms](https://open-meteo.com/en/terms). It may be unavailable offline and is labeled with provider provenance.
- A free data.gov.in API key can be requested at [data.gov.in](https://data.gov.in/user/register), but the app needs a chosen API-enabled resource ID before it can use that dataset.
- Voice input uses browser speech recognition by default. Gemini Live transcription is optional via a backend-only `GEMINI_API_KEY`; see [VOICE_ARCHITECTURE.md](VOICE_ARCHITECTURE.md). Grant microphone permission.
- Road-media OCR runs in-browser through Tesseract.js and fetches its language data on demand. Image cues are heuristic and require a human to classify/confirm.

No verified free, public live feed is configured for Bengaluru dispatch, ambulance, hospital capacity, police, fire, or traffic. The email panel creates reviewable drafts; demo send records no external delivery. Gmail SMTP is optional and disabled by default; see [EMAIL_ARCHITECTURE.md](EMAIL_ARCHITECTURE.md). Webcam evidence intake requires browser permission; AI camera detection is unavailable.

## Run deterministic scenario

With the backend virtual environment active:

```powershell
Set-Location D:\CrisisFlow-main\backend
python demo.py
```

The script runs a simulated incident through ten specialist agents, approval, local execution, verification, and a road-closure replan. It sends no external action.

## Checks

From `frontend`, run `npm run lint` and `npm run build`. From `backend`, run `python -m pytest`.

The original STGCN weights/validation data (`val_dataset.pt`) are absent. Flood prediction therefore uses a clearly identified deterministic simulation provider until the original compatible, licensed artifacts and preprocessing are supplied. See [API_KEYS_REQUIRED.md](API_KEYS_REQUIRED.md), [DATA_SOURCES.md](DATA_SOURCES.md), and [SECURITY.md](SECURITY.md).
