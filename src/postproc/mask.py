from __future__ import annotations

import numpy as np


def threshold_heatmap(
    hm: np.ndarray,
    method: str = "fixed",
    value: float = 0.5,
    percentile: float = 99.5,
) -> np.ndarray:
    if method == "fixed":
        thresh = value
    elif method == "percentile":
        thresh = float(np.percentile(hm, percentile))
    else:
        raise ValueError(f"Unknown threshold method: {method}")
    return (hm >= thresh).astype(np.uint8)

