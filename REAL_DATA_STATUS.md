# Real Data Status

Verified 2026-09-27 against the Phase 3 checkout. `LIVE` is emitted only after a successful provider response or actual model inference. Local seed records remain `SIMULATED`.

| Capability | Provider | Mode | Live? | Credential | Last Verified | Notes |
|------------|----------|------|-------|------------|---------------|-------|
| Current weather and forecast | Open-Meteo | LIVE/CACHED/SIMULATED | Conditional | None for free non-commercial use | 2026-09-27 | HTTP success is LIVE; 60-second cache and labeled fallback. Attribution required; free service is non-commercial. |
| KC Valley roads and geometry | Bundled OpenStreetMap extract / NetworkX | CACHED | No live refresh | None | 2026-09-27 | Used by routing and 3D view. Snapshot date unknown; ODbL and attribution apply. |
| Bengaluru hospitals | KAVACH demo inventory | SIMULATED | No | None | 2026-09-27 | Facility names/coordinates/capabilities and capacity are demo records; capability and capacity modes are separately exposed. |
| Ambulances | KAVACH demo inventory | SIMULATED | No | None | 2026-09-27 | Structured capability/location/availability fields exist; no dispatch or real unit feed. |
| Fire and police | KAVACH demo inventory | SIMULATED | No | None | 2026-09-27 | Station/unit records are demo data; police jurisdiction and staffing are not verified. |
| Traffic and closures | Bundled OSM graph plus local simulation | CACHED + SIMULATED | No live traffic | None | 2026-09-27 | The local failure simulator changes paths; it does not observe current road closures/congestion. |
| Government open data | data.gov.in generic resource adapter | UNAVAILABLE / NOT_CONFIGURED | No resource selected | API key + resource ID | 2026-09-27 | Query, page, filter, bounded cache, timeout and malformed-response behavior implemented. No dataset is claimed as connected. |
| Road damage | Optional local ONNX model provider | UNAVAILABLE | No compatible weights configured | Optional model file; explicit compatible license metadata | 2026-09-27 | Inference adapter is implemented and blocks incompatible/undocumented weights. Current media flow reports OCR/cues without damage classification. |
| Speech transcription | Browser Web Speech API | LIVE/LOCAL | Browser dependent | None | 2026-09-27 | Current free fallback. Browser vendor may process speech remotely depending on browser. |
| Optional streaming STT | AssemblyAI | UNAVAILABLE / LIVE when configured | Not verified without credentials | `ASSEMBLYAI_API_KEY` | 2026-09-27 | Short-lived browser token endpoint and WebSocket client implemented; not exercised because no key is configured. |
| Flood prediction | STGCN or deterministic simulator | SIMULATED | No | Dataset artifact absent | 2026-09-27 | `val_dataset.pt` remains unavailable; no artifact was manufactured. |
| Communications | Local audit adapter | SIMULATED | No external delivery | None | 2026-09-27 | n8n/SMS/email/WhatsApp external send is blocked because no authenticated identity provider exists. |

Provider status routes: `/api/providers`, `/api/providers/status`, `/api/providers/health`, `/api/providers/government/data`, `/api/voice/providers`, and `/api/auth/status`.
