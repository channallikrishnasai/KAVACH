# Security and Authorization

- Store secrets only in an untracked `.env`; use `.env.example` for names and safe defaults. Never commit tokens, passwords, or provider credentials.
- Local deterministic mode is for development/demo. It must not be exposed as a public service without authentication, rate limits, input size limits and audit retention controls.
- The demo records an explicit approval transition before local simulated execution. The actor label is not authenticated identity and this build does not implement production RBAC; do not expose it publicly or connect real emergency actions.
- Voice commands use the same command handlers and incident approval state as typed UI commands.
- Keep concise operational summaries and evidence in logs; do not expose hidden model reasoning or log secrets.
- Validate uploads by size, MIME sniffing and decoding; do not trust filenames or EXIF as verified incident location. Escape OCR/user strings in the UI.
- Use parameterized APIs and validate external provider responses. Apply timeouts, caching, and rate limits. Do not present provider fallback or seeded records as live.
- Preserve OpenStreetMap/CARTO/Open-Meteo attribution and comply with their data/service terms.
- The auth status endpoint explicitly reports that identity is unverified. No authentication layer is implemented. API role fields remain caller-supplied labels. Add identity, authenticated `READ`/`SUGGEST`/`APPROVE`/`EXECUTE` roles and authorization audit controls before deployment or publishing.
- Current role values are caller-supplied labels, not verified identities. Local policy gates reduce accidental demo misuse but do not provide real RBAC. Optional SMTP can send only to fixed department recipients configured in backend environment after an explicit draft approval; default is disabled. Do not expose SMTP-enabled KAVACH to the internet or connect emergency operations until authenticated identity and server-side authorization are implemented.
- Keep `KAVACH_DEMO_MODE=true` and `KAVACH_EXTERNAL_ACTIONS_ENABLED=false` for the free local demonstration. The notification adapter records to the local event log unless explicitly configured otherwise.
