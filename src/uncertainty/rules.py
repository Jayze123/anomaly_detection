from __future__ import annotations


def requires_human_review(confidence: float, label: str, unknown_label: str, threshold: float) -> bool:
    if label == unknown_label:
        return True
    return confidence < threshold

