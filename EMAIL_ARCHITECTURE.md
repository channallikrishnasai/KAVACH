# Email and Communication Architecture

## Draft lifecycle

When agents create a plan, KAVACH creates department-specific email drafts (for example Police and Hospital for a collision). Draft recipients are read only and come from backend environment variables. Operators can review and edit the subject/body, reject a draft, approve it, and either simulate the send in demo mode or send over configured SMTP. The UI and audit stream distinguish `SIMULATED` from `SENT`.

`SIMULATED_NO_EXTERNAL_DELIVERY` means no email was sent. A successful SMTP handoff is labeled `EMAIL ACCEPTED BY SMTP SERVER`; delivery to a recipient is not verified. SMTP exception responses expose only a generic exception class, never credentials. Draft and status APIs: `GET /api/communications`, `PUT /api/communications/{id}`, `POST /api/communications/{id}/approve`, `/reject`, `/send`, `/simulate-send`.

## Optional Gmail SMTP

Copy `backend/.env.example` to ignored `backend/.env`, then set:

```dotenv
KAVACH_EMAIL_ENABLED=true
KAVACH_EMAIL_HOST=smtp.gmail.com
KAVACH_EMAIL_PORT=465
KAVACH_EMAIL_SECURE=true
KAVACH_EMAIL_USER=your-sender@gmail.com
KAVACH_EMAIL_APP_PASSWORD=your-google-app-password
KAVACH_POLICE_EMAIL=your-controlled-test-recipient@example.com
KAVACH_HOSPITAL_EMAIL=your-controlled-test-recipient@example.com
```

Use a Gmail App Password, never a normal account password. Only the configured department addresses can receive messages; the user cannot edit the `To` field. Keep the feature disabled until you configure controlled test recipients and explicitly approve each draft. API key and SMTP configuration are not supplied in this checkout; real SMTP was tested only through a mock adapter.

This prototype still has no trusted login/session identity. Role values on API requests are caller-supplied labels, so do not expose SMTP-enabled KAVACH to the internet or treat it as production-ready. See [SECURITY.md](SECURITY.md).
