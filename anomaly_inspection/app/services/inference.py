from __future__ import annotations

import cv2
import numpy as np


class InferenceService:
    """Deterministic inference service with model-like interface."""

    def predict(self, frame: np.ndarray, product_id: str) -> tuple[str, float, bool]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness = float(np.mean(gray))
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        status = "NORMAL"
        is_defect = False
        confidence = 0.9

        if brightness < 45 or brightness > 220:
            status = "MISALIGNMENT"
            is_defect = True
            confidence = min(0.99, 0.65 + abs(brightness - 128) / 255)
        elif lap_var < 40:
            status = "DENT"
            is_defect = True
            confidence = min(0.98, 0.6 + (40 - lap_var) / 100)
        elif lap_var > 900:
            status = "SCRATCH"
            is_defect = True
            confidence = min(0.98, 0.6 + (lap_var - 900) / 2000)
        else:
            confidence = max(0.75, 0.95 - abs(brightness - 128) / 512)

        confidence = max(0.0, min(1.0, float(confidence)))
        return status, confidence, is_defect


inference_service = InferenceService()
