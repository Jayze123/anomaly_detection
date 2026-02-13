from __future__ import annotations


def requires_human_review(confidence: float, label: str, unknown_label: str, threshold: float) -> bool:
    if label == unknown_label:
        return True
    return confidence < threshold


def is_ambiguous_score(score: float, threshold: float, margin: float) -> bool:
    """
    Marks anomaly scores close to decision boundary as ambiguous.
    """
    return abs(score - threshold) <= margin
