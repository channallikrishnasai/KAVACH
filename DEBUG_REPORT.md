# CrisisFlow Windows Debug Report

## Initial error and root cause

`python main.py` imports `api.py`, which loads `backend/val_dataset.pt` at module import time. That file is absent, so startup raises `FileNotFoundError` before FastAPI can initialize.

Repository inspection found:

- `backend/.gitignore` excludes all `*.pt` files. The extracted repository includes `stgcn_weights.pth` and `stgcn_checkpoint.pth`, but not `val_dataset.pt` or `train_dataset.pt`.
- `backend/train.py` trains from `train_dataset.pt` and `val_dataset.pt`; it does not create either file.
- `backend/extract.py` parses the included OSM data and creates graph/map assets. It does not create training or validation tensors.
- `backend/dataset_meta.json` records dimensions, feature names, aggregate labels, and node IDs. It does not contain the missing tensors or a method to reconstruct their values.
- The README documents the training command but no dataset-generation step, artifact download, model storage, or release. The public upstream repository's tracked backend files likewise have no `.pt` artifact or dataset generator.

Therefore the missing file is an omitted training/validation artifact, not a Windows path separator issue. Reconstructing it from metadata or fabricating replacement values would not faithfully reproduce the model's inputs. No dataset was generated or substituted.

## Commands and results

- `python main.py` (from `backend/`): reproduced the traceback at `api.py` loading `val_dataset.pt`. The PyTorch `torch.jit.script` FutureWarning is non-blocking.
- `npm ci` (from `frontend/`): completed; installed 551 packages. npm reported 21 dependency audit findings (1 low, 5 moderate, 14 high, 1 critical).
- `npm run build`: passed. Vite reported large JavaScript chunks; the build completed successfully.
- `npm run lint`: passed.
- `python -m pytest -q` (backend venv): could not run because `pytest` is not installed (`No module named pytest`). The repository has no discovered test files.
- Local MongoDB check: `127.0.0.1:27017` refused the TCP connection; `mongod.exe` is not on PATH.
- Frontend clean restart: `npm run dev -- --host 127.0.0.1` restarted successfully at `http://127.0.0.1:5173/`. `GET /` and `/src/main.tsx` returned HTTP 200. `http://127.0.0.1:8000/` refused the connection because backend startup is blocked.

## Files modified

- `DEBUG_REPORT.md` — this report, documenting evidence and exact next steps.

No backend, model, data, or UI source files were changed. `npm ci` installed ignored frontend dependencies.

## Startup, API, and end-to-end status

- Backend startup and all backend API requests remain blocked before app initialization by missing `backend/val_dataset.pt`.
- `/`, `/health`, `/weather`, `/simulate`, `/route`, `/route/nearest`, `/geojson/buildings`, `/geojson/water`, and the `/api/...` CRUD routes are declared in the source, but could not be tested over HTTP because the server cannot start.
- MongoDB is also unavailable locally. The configured URL is `mongodb://localhost:27017`; full backend startup requires a running local MongoDB or a configured reachable MongoDB instance.
- The frontend compiles and serves its HTML and JS modules. The interactive map depends on backend GeoJSON endpoints, dashboard data depends on MongoDB-backed API routes, and flood/weather/routing features depend on the STGCN routes. Those end-to-end features could not be verified without the backend.
- No genuine test suite was available to execute: pytest is absent, and no backend test files were found. Frontend build and lint passed.

## Exact next steps to unblock

1. Obtain the original `val_dataset.pt` for this exact graph/model, or obtain the original preprocessing/data-generation code and its genuine source data from the project owner. Place the artifact at `backend/val_dataset.pt`. Do not create an empty or synthetic replacement.
2. Install/start MongoDB Community locally (or set `MONGODB_URL` in the root `.env` to a reachable MongoDB deployment). If installed as a Windows service, start it with `Start-Service MongoDB` from an elevated PowerShell terminal.
3. From a fresh PowerShell terminal, run:

```powershell
Set-Location D:\CrisisFlow-main\backend
.\venv\Scripts\Activate.ps1
python main.py
```

4. In a second PowerShell terminal, run:

```powershell
Set-Location D:\CrisisFlow-main\frontend
npm run dev -- --host 127.0.0.1
```

5. Once the original dataset and MongoDB are available, verify `http://127.0.0.1:8000/health`, then test the declared weather, simulation, routing, GeoJSON, and CRUD endpoints and the frontend map.

## Current result

The repository cannot run as a complete application from the supplied files alone. The missing dataset has no documented download or generation workflow, so it is an external artifact/source-code blocker. MongoDB is a separate local service blocker. The frontend's build, lint, clean restart, and HTTP serving are verified.
