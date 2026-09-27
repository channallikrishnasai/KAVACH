# External Component Audit

Audit date: 2026-09-27. Source and license checks were made against repository metadata/primary GitHub pages. Public visibility alone does not grant permission to copy source or model weights.

| Repository | Purpose / useful module | License status | Source copy? | Architecture reuse? | Recommendation |
|---|---|---|---|---|---|
| [KAVACH](https://github.com/channallikrishnasai/KAVACH) | User-provided destination | Apache-2.0; repository currently has only license and near-empty README | No code to copy | N/A | Treat this workspace as the implementation base; preserve Apache attribution if this code is later published there. |
| [CrisisFlow](https://github.com/h4ck3r0/CrisisFlow) | Existing Bengaluru map, flood API, CRUD, routes | No license file/license metadata found | No | Yes, local code is already the base | Keep useful modules; do not import remote source. |
| [FloodOps](https://github.com/krishddd/floodops-multi-agent-system) | Multi-agent flood orchestration, event bus and provider patterns | No license file/license metadata found | No | Yes, high-level event-driven pattern only | Independently implement typed deterministic agents; do not copy source. |
| RESQ / RescueMind | Disaster-response agents | Prompt name is ambiguous; candidate RescueMind page does not establish a usable license in this audit | No | General concepts only | Do not depend on this candidate. |
| [DisasterView](https://github.com/vinayaksingh0542/DisasterView) | Sensor fusion / hazard command UI | No license metadata found | No | General concepts only | No source reuse. |
| UFIS | Urban flood intelligence | No unique repository was specified or verified | No | N/A | Excluded until a precise repository and license can be identified. |
| [iWatchRoad](https://github.com/smlab-niser/iWatchRoad) | YOLO pothole tracking and geospatial review | GitHub reports `NOASSERTION`; bundled BharatPotHole dataset is separate and has its own terms | No | Conceptual pipeline only | Do not copy code/weights/data without author and dataset license clarification. |
| [SentriRoad](https://github.com/Arpitha-creates/sentriroad001) | Pothole workflow / work orders | MIT | Technically yes, but no source copied in this phase | Yes | Reuse its public workflow ideas only if needed; implement independently for now. |
| [Pothole & Road Distress Detection model](https://huggingface.co/vinothvikas1987/pothole-detection-yolov8) | ONNX detector for potholes and road distress | Conflict: model card says Apache-2.0; downloaded ONNX metadata says AGPL-3.0; training dataset provenance is also undisclosed | No, pending written license clarification | Architecture only | Rejected for KAVACH. It was downloaded for metadata inspection and removed; do not redistribute/use until author resolves the license conflict. |
| Pothole Reporter | Road-hazard reporting | Ambiguous name; no unique repository/license verified | No | N/A | Excluded pending exact source. |
| [OpenHands](https://github.com/OpenHands/OpenHands) | General agent/tool runtime | MIT | Technically yes, but too large and not needed | Yes | Do not add a heavyweight general coding-agent runtime to a city ops demo. |
| [LangGraph](https://github.com/langchain-ai/langgraph) | Stateful graph orchestration | MIT | Dependency may be used under its license | Yes | Optional; a small deterministic state machine is simpler and works offline. |
| [Playwright](https://github.com/microsoft/playwright) | Browser automation/testing | Apache-2.0 | Dependency may be used under its license | Yes | Optional UI verification; not a production app runtime dependency. |
| [Browser Use](https://github.com/browser-use/browser-use) | Browser agent automation | MIT | Not copied | Yes | Not needed for core incident orchestration. |
| OPERO | Voice architecture | Prompt does not identify a unique repository; license/source not verified | No | N/A | Use browser-native speech interfaces with typed fallback; no OPERO code copied. |

## Dependency/data license cautions

- The linked KAVACH repo is Apache-2.0, but that does not relicense bundled source/data whose provenance is unknown.
- Existing frontend/backend dependencies retain their upstream licenses. Generate a machine-readable license inventory before distribution.
- OSM-derived city features are under ODbL and require attribution; feature/database redistribution may trigger share-alike obligations.
- Open-Meteo free endpoint is limited to non-commercial use under its terms and data is CC BY 4.0; attribute it and use another provider or paid plan for commercial operation.
- No pothole model or dataset is currently installed. iWatchRoad's dataset link does not itself grant a model license.
