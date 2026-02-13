from __future__ import annotations

import base64
import threading
import time
from collections.abc import Callable

import cv2
import numpy as np

from app.core.config import get_settings


class CameraService:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._cap: cv2.VideoCapture | None = None
        self._last_capture_ts = 0.0

    def _parse_roi(self, frame: np.ndarray) -> tuple[int, int, int, int]:
        settings = get_settings()
        if not settings.roi:
            h, w = frame.shape[:2]
            return 0, 0, w, h

        parts = [int(v.strip()) for v in settings.roi.split(",") if v.strip()]
        if len(parts) != 4:
            h, w = frame.shape[:2]
            return 0, 0, w, h

        x, y, rw, rh = parts
        return max(0, x), max(0, y), max(1, rw), max(1, rh)

    def start(
        self,
        on_frame: Callable[[np.ndarray], None],
        on_capture: Callable[[np.ndarray], None],
    ) -> None:
        if self._running.is_set():
            return

        self._running.set()

        def _runner() -> None:
            settings = get_settings()
            self._cap = cv2.VideoCapture(settings.camera_index)
            subtractor = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=32, detectShadows=False)

            while self._running.is_set() and self._cap.isOpened():
                ok, frame = self._cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue

                on_frame(frame)

                x, y, w, h = self._parse_roi(frame)
                roi = frame[y : y + h, x : x + w]
                fg_mask = subtractor.apply(roi)
                _, fg_mask = cv2.threshold(fg_mask, 200, 255, cv2.THRESH_BINARY)
                motion_ratio = float(np.count_nonzero(fg_mask)) / float(fg_mask.size)

                now_ms = time.time() * 1000
                if motion_ratio > settings.trigger_threshold and (now_ms - self._last_capture_ts) >= settings.debounce_ms:
                    self._last_capture_ts = now_ms
                    on_capture(frame.copy())

                time.sleep(0.02)

            if self._cap:
                self._cap.release()

        self._thread = threading.Thread(target=_runner, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)


camera_service = CameraService()


def frame_to_base64_jpg(frame: np.ndarray) -> str:
    ok, encoded = cv2.imencode(".jpg", frame)
    if not ok:
        return ""
    return base64.b64encode(encoded.tobytes()).decode("ascii")
