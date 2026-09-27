# KAVACH Voice Architecture

## Providers

- **Gemini Live Transcription (optional):** Set `GEMINI_API_KEY` in backend environment. The backend requests a single-use ephemeral token constrained to the Live Transcription model and allowed configuration, then the browser streams mono 16 kHz PCM. The long-lived API key never goes to the browser. Gemini final transcription is passed to KAVACH's deterministic intent parser; Gemini does not get authority to approve or execute actions. Transcription runs directly through Gemini Live; generated spoken responses still use the browser's speech synthesis.
- **AssemblyAI (optional):** Existing streaming speech provider, enabled by `ASSEMBLYAI_API_KEY`.
- **Browser speech (free default):** Uses Web Speech recognition and synthesis where supported. Browser recognition may rely on browser vendor services and is not guaranteed offline.

The Gemini Live token feature follows Google's [ephemeral token guide](https://ai.google.dev/gemini-api/docs/live-api/ephemeral-tokens) and [Live transcription guide](https://ai.google.dev/gemini-api/docs/live-api/live-transcribe). The model is configurable with `GEMINI_LIVE_TRANSCRIBE_MODEL`; default is `gemini-3.5-transcribe-live`. Availability and billing depend on the Gemini account and current Google API terms. Live voice could not be exercised without the user's key.

Voice commands use the same deterministic action handlers and approval workflow as typed commands. They do not authenticate identity. Known names resolve only to fixed demo coordinates and remain labeled simulated. Unknown or ambiguous location phrases require manual map confirmation.
