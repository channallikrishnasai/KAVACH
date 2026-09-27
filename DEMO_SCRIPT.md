# KAVACH Final Demo Script

Two repeatable walkthroughs. All inventory and operational actions remain labeled simulated.

## Test case 1 — Silk Board collision, communication approval, and route replan

1. Start the backend and frontend using [START_KAVACH.md](START_KAVACH.md); no API key is required.
2. Select **REPORT INCIDENT**. Keep *Major accident*, *Critical*, *Silk Board*, and the prefilled collision description. Select **ACTIVATE KAVACH**.
3. Watch the map focus, event stream, selected specialist findings, response plan, and two department email drafts. Hospital/resource data and route ETA are simulated.
4. Open the Police draft, review/edit it, click **APPROVE**, then **SIMULATE SEND · NO EMAIL SENT**. The event stream records `SIMULATED_NO_EXTERNAL_DELIVERY`.
5. Click **APPROVE PLAN**, then **EXECUTE DEMO ACTIONS** to see local verification.
6. Click **INJECT FAILURE · REPLAN**. Inspect route failure and replan events. Approve the revised plan and execute again.
7. Use **RESET DEMO** to clear process-memory state.

Optional actual SMTP: set controlled test recipient addresses, Gmail App Password, and `KAVACH_EMAIL_ENABLED=true` in backend `.env`. Drafts can only send to configured department addresses after explicit approval. No SMTP credential is included or live-tested in this checkout.

## Test case 2 — local webcam evidence intake

1. Choose **REPORT INCIDENT** to set a known map location, or leave Silk Board selected.
2. Select **CONNECT CAMERA** and allow browser webcam access.
3. The preview states that vision is unavailable. Inspect the image, select the event type, and confirm only if you personally observed it.
4. Select **CONFIRM EVENT AND ACTIVATE KAVACH**. KAVACH captures a frame, creates a `CAMERA`-source incident with operator-confirmed evidence, and starts the agent workflow automatically.
5. Select the incident and inspect its frame, timestamp/digest, agent results, drafts, route, and approval gate.

This is camera evidence intake with human confirmation, not automated CCTV detection. No vision model is installed. Camera metadata and captured frames are held in process memory and reset when the backend restarts.

## Voice

Microphone permission is required. Set `GEMINI_API_KEY` in ignored `backend/.env` to select Gemini Live transcription; otherwise browser speech is used. Say “Investigate a major accident near Silk Board” or use typed commands. Gemini transcription does not authenticate the speaker or bypass approval. Responses use browser speech synthesis.

## Run services

Run `python main.py` from `backend` with its virtual environment. Run `npm run dev -- --host 127.0.0.1` from `frontend`. Open the Vite URL. The local demo needs no API keys or MongoDB server.
