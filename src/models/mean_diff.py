from __future__ import annotations

import numpy as np
from PIL import Image


class MeanDiffModel:
    """
    Simple baseline: compute per-pixel mean/std from train/good images.
    Anomaly heatmap = mean(abs(image - mean) / (std + eps)) over channels.
    """

    def __init__(self, eps: float = 1e-6):
        self.eps = eps
        self.mean = None
        self.std = None
        self.shape = None

    def fit(self, images: list[Image.Image]) -> None:
        if not images:
            raise ValueError("No training images provided.")
        arrs = [np.asarray(im, dtype=np.float32) for im in images]
        shapes = {a.shape for a in arrs}
        if len(shapes) != 1:
            raise ValueError(f"Image size mismatch in training set: {shapes}")
        stack = np.stack(arrs, axis=0)
        self.mean = stack.mean(axis=0)
        self.std = stack.std(axis=0)
        self.shape = stack.shape[1:]

    def infer(self, image: Image.Image) -> tuple[float, np.ndarray]:
        if self.mean is None or self.std is None:
            raise RuntimeError("Model not fitted.")
        arr = np.asarray(image, dtype=np.float32)
        if arr.shape != self.shape:
            raise ValueError(f"Image size mismatch. Expected {self.shape}, got {arr.shape}")
        z = np.abs(arr - self.mean) / (self.std + self.eps)
        heatmap = z.mean(axis=2)
        score = float(np.max(heatmap))
        return score, heatmap

