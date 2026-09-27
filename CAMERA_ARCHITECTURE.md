# Camera Architecture

## Available path

The Camera Center obtains a local webcam stream in the browser, registers/starts a camera record through `/api/cameras`, and lets the operator capture a frame as JPEG evidence. The operator must identify and confirm the reported event before KAVACH creates an incident. The backend creates a normal incident marked `source=CAMERA`, stores the frame in process memory with a SHA-256 digest, emits camera/evidence events, and automatically runs the incident investigation and draft workflow.

This camera path is **human confirmed**. The backend status explicitly says `VISION MODEL UNAVAILABLE`; it does not detect a collision, invent a confidence, or automatically create a critical incident. There is no HLS, WebRTC, IP camera, RTSP bridge, object detection, temporal validation, or persistent frame storage in this build.

Camera records and frame evidence are process-memory demo state and reset when the server restarts. Routes: `GET/POST /api/cameras`, `GET /api/cameras/{id}`, `POST /api/cameras/{id}/start`, `/stop`, `DELETE /api/cameras/{id}`, `POST /api/cameras/{id}/observations/confirm`, `GET /api/cameras/evidence/{id}`. Run on localhost/HTTPS and grant browser camera permission.
