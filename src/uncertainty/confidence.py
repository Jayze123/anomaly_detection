from __future__ import annotations


def combine_confidence(anomaly_conf: float, vlm_conf: float, method: str = "min") -> float:
    if method == "min":
        return float(min(anomaly_conf, vlm_conf))
    if method == "mean":
        return float((anomaly_conf + vlm_conf) / 2.0)
    raise ValueError(f"Unknown combine method: {method}")

