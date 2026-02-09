from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VLMResult:
    defect_label: str
    evidence: list[str]
    confidence: float


def infer_defect_label(
    category: str,
    label_set: list[str],
    unknown_label: str,
    roi_note: str,
) -> VLMResult:
    # Placeholder. Replace with actual VLM call.
    return VLMResult(
        defect_label=unknown_label,
        evidence=[
            "NEEDED FROM USER: VLM integration not configured.",
            f"ROI note: {roi_note}",
        ],
        confidence=0.0,
    )

