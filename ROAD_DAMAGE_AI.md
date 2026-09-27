# Road Damage Intelligence

## Implemented pipeline

The upload route decodes images or up to eight video frames, computes image dimensions and SHA-256, reads EXIF GPS when available, accepts browser Tesseract OCR text/confidence, and calls a local ONNX object detector when a configured model passes format and license checks. Model output class, raw model confidence and bounding box are preserved. A separate severity review estimate uses the detection box's image-relative area and confidence; it explicitly is not physical depth/size. Human confirmation remains required. OCR is evidence only and never supplies a location by itself.

If no compatible model is configured, `model_mode=UNAVAILABLE`, `detections=[]`, `pothole_detected=null`; OpenCV contrast cues remain labeled non-classifying and are never called damage detections. Media reports require EXIF GPS or an operator-confirmed map location before incident creation.

Road hazard incidents are passed through the Road Intelligence, Traffic, Routing and Logistics specialists. Human-confirmed hazard points that coincide with an active emergency path are used to check an alternate path; the updated response returns to `AWAITING_APPROVAL`. Hazard/path matches use the bundled graph and operator-confirmed coordinates, not live traffic observation.

## Model/license review

- [CamThink Road Damage Object Detection](https://www.camthink.ai/developer-center/models/road-damage-object-detection/) lists MIT on its model page, but its downloadable ONNX artifact metadata declares `AGPL-3.0`. The page does not identify the training dataset/license. The artifact is rejected by the runtime gate and is not used for detections.
- [iWatchRoad](https://github.com/smlab-niser/iWatchRoad) advertises a YOLOv8 road detector, but its repository states CC BY-NC-SA 4.0; its BharatPotHole dataset's separate license and the released weights' license/provenance are not sufficient for this integration.
- Other reviewed checkpoints either have no weight license, use unclear training data, or depend on model/framework terms that were not verified. No weight or source code was copied into the application.

The provider supports an ONNX file via `ROAD_DAMAGE_MODEL_PATH` only when model metadata (or `ROAD_DAMAGE_MODEL_LICENSE`) declares a specifically allowed permissive license: MIT, Apache-2.0, or BSD-3-Clause. `AGPL`, `CC BY-NC-SA`, missing license metadata, malformed inputs, and unsupported output formats are blocked. The current workspace has no accepted model; therefore Phase 3 model-detection success criteria are not met yet.

## Output fields

`damageType`, raw `confidence`, `boundingBox`, `severity`, `reason`, `areaRatio`, `frameIndex`, `source`, and `mode`. Severity reason states when it relies on pixels rather than physical measurement. `CRITICAL` requires high-confidence large detection plus independently confirmed emergency-corridor overlap; it cannot be inferred from OCR or contrast cues.
