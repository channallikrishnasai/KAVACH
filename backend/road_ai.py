"""Conservative post-processing for licensed local object detector outputs."""
from __future__ import annotations

from typing import Any


def derive_damage_severity(detection: dict[str, Any], width: int, height: int, *, emergency_corridor: bool = False) -> dict[str, Any]:
    """Estimate operational review priority from model confidence and box area.

    This is a transparent pixel-area heuristic, not physical depth measurement.
    """
    box = detection.get("boundingBox")
    confidence = detection.get("confidence")
    if not isinstance(box, list) or len(box) != 4 or not isinstance(confidence, (int, float)):
        return {"severity": "LOW", "reason": "No valid model box/confidence; manual review only", "areaRatio": None}
    x1, y1, x2, y2 = (float(value) for value in box)
    area_ratio = max(0.0, x2 - x1) * max(0.0, y2 - y1) / max(1.0, float(width) * float(height))
    reasons = [f"Model box covers {area_ratio:.1%} of the image", f"Model confidence is {float(confidence):.2f}"]
    if area_ratio >= 0.08:
        severity = "HIGH"
        reasons.append("Large image-relative defect area raises inspection priority")
    elif area_ratio >= 0.02:
        severity = "MEDIUM"
        reasons.append("Moderate image-relative defect area")
    else:
        severity = "LOW"
        reasons.append("Small image-relative defect area")
    if float(confidence) < 0.4 and severity != "LOW":
        severity = "LOW"
        reasons.append("Low model confidence reduces the severity recommendation")
    if emergency_corridor and float(confidence) >= 0.6:
        severity = "CRITICAL" if area_ratio >= 0.08 and float(confidence) >= 0.8 else "HIGH"
        reasons.append("Operator-confirmed overlap with an emergency corridor raises response priority")
    reasons.append("Pixel area is not physical defect size; human confirmation required")
    return {"severity": severity, "reason": "; ".join(reasons), "areaRatio": round(area_ratio, 5), "basis": "MODEL_CONFIDENCE_PLUS_IMAGE_RELATIVE_BOX_AREA"}
