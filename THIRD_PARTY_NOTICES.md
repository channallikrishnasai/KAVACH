# Third-Party Notices and Model Provenance

- OpenStreetMap data: © OpenStreetMap contributors, licensed under the Open Database License 1.0 (ODbL). The bundled extract's capture date is unknown. Preserve attribution and comply with ODbL terms.
- Open-Meteo weather data: CC BY 4.0 attribution applies; the free API is for non-commercial use under its current terms.
- AssemblyAI: optional hosted transcription service. Its terms and current pricing apply when enabled; no service credentials are included.
- ONNX Runtime, OpenCV, and Tesseract.js are third-party packages; see their respective package license files and notices.

## Road model status

No road-damage weights are bundled or used by the application. A downloaded candidate from CamThink advertised MIT on its model page, while the inspected ONNX file metadata declared AGPL-3.0 and did not establish training dataset rights. Because those declarations conflict and dataset provenance was unclear, KAVACH blocks that model and does not use it. The public page is [CamThink Road Damage Object Detection](https://www.camthink.ai/developer-center/models/road-damage-object-detection/).

The `backend/model_artifacts/` folder is ignored by Git. An incompatible local candidate may remain in a developer checkout; application code does not select it unless explicitly configured, and its license check rejects it. Users must supply weights with a verifiable permissive license and dataset provenance before enabling inference.

The iWatchRoad project is licensed CC BY-NC-SA 4.0, which is not suitable as a general permissive integration: [project license](https://github.com/smlab-niser/iWatchRoad). No iWatchRoad assets or weights are bundled.
