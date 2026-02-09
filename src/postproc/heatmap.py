from __future__ import annotations

import numpy as np


def normalize_heatmap(hm: np.ndarray, method: str = "minmax") -> np.ndarray:
    if method == "minmax":
        vmin = float(np.min(hm))
        vmax = float(np.max(hm))
        if vmax - vmin < 1e-12:
            return np.zeros_like(hm, dtype=np.float32)
        return (hm - vmin) / (vmax - vmin)
    raise ValueError(f"Unknown normalize method: {method}")

