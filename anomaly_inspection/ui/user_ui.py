from __future__ import annotations

from collections import deque
from datetime import datetime

import cv2
from nicegui import ui
from sqlalchemy import select

from app.db import crud
from app.db.models import Product, Scan, ScanImage
from app.db.session import SessionLocal
from app.services.camera import camera_service, frame_to_base64_jpg
from app.services.inference import inference_service
from app.services.storage import store_frame_bytes
from ui.components import navbar, require_ui_role


class ScanState:
    def __init__(self):
        self.preview_b64 = ""
        self.last_frame = None
        self.last_result = {"status": "-", "confidence": 0.0, "is_defect": False, "image": None}
        self.inspected = 0
        self.defects = 0
        self.capture_queue = deque(maxlen=16)


def register_user_routes() -> None:
    @ui.page("/user/scan")
    def user_scan_page():
        user = require_ui_role("USER")
        navbar(user, "Scanner")
        state = ScanState()

        with SessionLocal() as db:
            products = db.scalars(select(Product).order_by(Product.name)).all()

        with ui.column().classes("p-4 w-full"):
            with ui.row().classes("items-center gap-3"):
                product_map = {p.name: p.id for p in products}
                product = ui.select(product_map, label="Product", value=next(iter(product_map.values()), None))
                start_btn = ui.button("Start")
                stop_btn = ui.button("Stop")
                manual_btn = ui.button("Manual Capture")

            image_view = ui.interactive_image().classes("w-full max-w-2xl border")
            result_label = ui.label("Result: -").classes("text-xl font-bold")
            confidence_label = ui.label("Confidence: 0.00")
            counters = ui.label("Inspected: 0 | Defects: 0 | Defect rate: 0.00%")
            thumb = ui.image().classes("w-48 h-32")

            def update_labels():
                rate = (state.defects / state.inspected * 100) if state.inspected else 0.0
                result_label.set_text(f"Result: {state.last_result['status']}")
                confidence_label.set_text(f"Confidence: {state.last_result['confidence']:.2f}")
                counters.set_text(f"Inspected: {state.inspected} | Defects: {state.defects} | Defect rate: {rate:.2f}%")
                if state.last_result["image"]:
                    thumb.set_source(f"/data{state.last_result['image']}")

            def on_frame(frame):
                state.last_frame = frame.copy()
                state.preview_b64 = frame_to_base64_jpg(frame)

            def persist_capture(frame):
                ok, encoded = cv2.imencode(".jpg", frame)
                if not ok:
                    return
                path = store_frame_bytes(encoded.tobytes(), f"scan_images/{user['id']}", ".jpg")
                status, conf, defect = inference_service.predict(frame, product.value)
                with SessionLocal() as db:
                    scan = crud.create_scan(
                        db,
                        factory_id=user["factory_id"],
                        user_id=user["id"],
                        product_id=product.value,
                        predicted_status=status,
                        confidence=conf,
                        is_defect=defect,
                        image_paths=[path],
                    )
                    db.commit()
                state.last_result = {"status": status, "confidence": conf, "is_defect": defect, "image": path, "scan_id": scan.id}
                state.inspected += 1
                if defect:
                    state.defects += 1
                ui.notify(f"Captured: {status} ({conf:.2f})", color="negative" if defect else "positive")
                update_labels()
                render_history()

            def process_capture_queue():
                if not state.capture_queue:
                    return
                frame = state.capture_queue.popleft()
                persist_capture(frame)

            def start_camera():
                if not product.value:
                    ui.notify("Select a product before start", color="warning")
                    return
                camera_service.start(on_frame=on_frame, on_capture=lambda frame: state.capture_queue.append(frame))
                ui.notify("Camera started", color="positive")

            def stop_camera():
                camera_service.stop()
                ui.notify("Camera stopped", color="warning")

            def manual_capture():
                if state.last_frame is None:
                    ui.notify("No frame available", color="warning")
                    return
                state.capture_queue.append(state.last_frame.copy())

            start_btn.on_click(start_camera)
            stop_btn.on_click(stop_camera)
            manual_btn.on_click(manual_capture)

            def refresh_preview():
                if state.preview_b64:
                    image_view.set_source(f"data:image/jpeg;base64,{state.preview_b64}")

            ui.timer(0.1, refresh_preview)
            ui.timer(0.1, process_capture_queue)
            ui.context.client.on_disconnect(stop_camera)

            with ui.tabs().classes("w-full") as tabs:
                history_tab = ui.tab("History")
            with ui.tab_panels(tabs, value=history_tab).classes("w-full"):
                with ui.tab_panel(history_tab):
                    with ui.row().classes("gap-3"):
                        start_at = ui.input("Start (YYYY-MM-DD)")
                        end_at = ui.input("End (YYYY-MM-DD)")
                        product_filter = ui.select({"": "All", **product_map}, value="", label="Product")
                        defect_only = ui.switch("Defects only", value=False)
                        ui.button("Apply", on_click=lambda: render_history())
                    history_area = ui.column().classes("w-full")

            def render_history():
                history_area.clear()
                with SessionLocal() as db:
                    where = [Scan.factory_id == user["factory_id"]]
                    if product_filter.value:
                        where.append(Scan.product_id == product_filter.value)
                    if defect_only.value:
                        where.append(Scan.is_defect.is_(True))
                    if start_at.value:
                        where.append(Scan.captured_at >= datetime.fromisoformat(start_at.value))
                    if end_at.value:
                        where.append(Scan.captured_at <= datetime.fromisoformat(end_at.value))
                    scans = db.scalars(select(Scan).where(*where).order_by(Scan.captured_at.desc()).limit(200)).all()

                rows = []
                for s in scans:
                    rows.append(
                        {
                            "id": s.id,
                            "time": s.captured_at.isoformat(timespec="seconds"),
                            "product": s.product.name if s.product else "",
                            "status": s.predicted_status,
                            "confidence": f"{s.confidence:.2f}",
                            "defect": "Yes" if s.is_defect else "No",
                        }
                    )

                with history_area:
                    table = ui.table(
                        columns=[
                            {"name": "time", "label": "Time", "field": "time", "sortable": True},
                            {"name": "product", "label": "Product", "field": "product", "sortable": True},
                            {"name": "status", "label": "Status", "field": "status", "sortable": True},
                            {"name": "confidence", "label": "Confidence", "field": "confidence", "sortable": True},
                            {"name": "defect", "label": "Defect", "field": "defect", "sortable": True},
                        ],
                        rows=rows,
                        row_key="id",
                        pagination=10,
                    ).classes("w-full")

                    def open_row(e):
                        sid = e.args["id"]
                        with SessionLocal() as db:
                            scan = db.get(Scan, sid)
                            imgs = db.scalars(select(ScanImage).where(ScanImage.scan_id == sid)).all()
                        with ui.dialog() as d, ui.card().classes("w-[760px]"):
                            ui.label(f"Scan {scan.id}").classes("text-lg font-bold")
                            ui.label(f"Status: {scan.predicted_status} | Confidence: {scan.confidence:.2f}")
                            for img in imgs:
                                ui.image(f"/data{img.image_path}").classes("max-h-80")
                            ui.button("Close", on_click=d.close)
                        d.open()

                    table.on("rowClick", open_row)

            render_history()
