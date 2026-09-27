# KAVACH Agent Architecture

The existing ten-agent structure remains in `backend/kavach_core.py`. The commander selects specialists according to incident type; major collisions can select all ten. Each selected specialist returns status, finding, evidence, confidence, recommendation, tool labels, trace ID and duration. Agent start/completion, plan, simulation, and lifecycle events are emitted to the local event stream.

| Agent | Current work performed | Data boundary |
|---|---|---|
| Observer | Summarizes city/incident state | Local state |
| Commander | Combines specialist findings and creates plan | Deterministic rules |
| Traffic | Assesses graph path/closure | Bundled OSM-derived graph; no live traffic |
| Medical | Ranks demo hospitals/resources | Seeded simulated capacity |
| Fire | Selects nearby demo station/resource | Seeded simulated inventory |
| Police | Recommends local coordination | Seeded demo records; jurisdiction unverified |
| Road intelligence | Reports OCR and actual local model detections when configured | Human review; detector is unavailable until compatible weights are configured |
| Logistics | Compares available demo resources | Seeded simulated inventory |
| Routing | Calculates graph routes and alternatives | Local graph; travel speed is a heuristic |
| Communications | Drafts a notification/event | Local event log by default |

Confidence is a rule heuristic, not calibrated statistical confidence. Evidence provenance distinguishes local simulation, user/map input, or a provider response. No LLM is required. The UI displays the heuristic boundary rather than claiming autonomous AI validation.

The agent workflow is not a durable distributed agent runtime: there is no broker, persistent trace store, or independent model per specialist. Approval and execution are local state transitions. Actor roles are caller-supplied labels; production identity/RBAC is not implemented.
