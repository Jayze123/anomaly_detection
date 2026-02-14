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
        self.running = False


def build_scan_history(history_area, user: dict, start_at, end_at, product_filter, defect_only):
    history_area.clear()
    with SessionLocal() as db:
        where = [Scan.factory_id == user["factory_id"]]
        if product_filter.value:
            where.append(Scan.product_id == product_filter.value)
        if defect_only.value:
            where.append(Scan.is_defect.is_(True))
        if start_at.value:
            try:
                where.append(Scan.captured_at >= datetime.fromisoformat(start_at.value))
            except ValueError:
                ui.notify("Invalid start date format. Use YYYY-MM-DD.", color="warning")
        if end_at.value:
            try:
                where.append(Scan.captured_at <= datetime.fromisoformat(end_at.value))
            except ValueError:
                ui.notify("Invalid end date format. Use YYYY-MM-DD.", color="warning")
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


def register_user_routes() -> None:
    @ui.page("/user/scan")
    def user_scan_page():
        user = require_ui_role("USER")
        if not user:
            return
        navbar(user, "Scanner", nav_links=[("Scan", "/user/scan"), ("Scan History", "/user/history")])
        state = ScanState()

        with SessionLocal() as db:
            products = db.scalars(select(Product).order_by(Product.name)).all()

        product_options = {p.id: p.name for p in products}
        default_product_id = next(iter(product_options.keys()), None)

        with ui.column().classes("p-4 w-full"):
            ui.label("Product Scan").classes("text-2xl font-bold")
            with ui.row().classes("items-center gap-3 w-full"):
                product = ui.select(
                    product_options,
                    label="Select Product",
                    value=default_product_id,
                ).props("outlined").classes("min-w-[280px]")
                start_btn = ui.button("Start Camera").props("color=positive")
                stop_btn = ui.button("Stop Camera").props("color=warning")
                manual_btn = ui.button("Manual Capture").props("color=primary")
                camera_status = ui.badge("Stopped").props("color=grey")

            if not product_options:
                ui.notify("No products available. Ask admin to create a product first.", color="warning")
                start_btn.disable()
                manual_btn.disable()

            with ui.row().classes("w-full gap-4 items-start"):
                with ui.card().classes("w-full max-w-3xl"):
                    ui.label("Live Preview").classes("text-base font-semibold")
                    image_view = ui.interactive_image().classes("w-full border rounded")
                with ui.column().classes("min-w-[260px] gap-2"):
                    result_label = ui.badge("Result: -").props("color=grey")
                    confidence_label = ui.label("Confidence: 0.00")
                    counters = ui.label("Inspected: 0 | Defects: 0 | Defect rate: 0.00%")
                    thumb = ui.image().classes("w-56 h-40 rounded border")
                    view_btn = ui.button("View Last Capture").props("outline")

            def update_labels():
                rate = (state.defects / state.inspected * 100) if state.inspected else 0.0
                result_text = f"Result: {state.last_result['status']}"
                result_label.set_text(result_text)
                result_label.props(
                    "color=positive" if state.last_result["status"] == "NORMAL" else "color=negative"
                )
                confidence_label.set_text(f"Confidence: {state.last_result['confidence']:.2f}")
                counters.set_text(f"Inspected: {state.inspected} | Defects: {state.defects} | Defect rate: {rate:.2f}%")
                if state.last_result["image"]:
                    thumb.set_source(f"/data{state.last_result['image']}")

            def on_frame(frame):
                state.last_frame = frame.copy()
                state.preview_b64 = frame_to_base64_jpg(frame)

            def persist_capture(frame):
                if not product.value:
                    ui.notify("Select a valid product before capture", color="warning")
                    return
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

            def process_capture_queue():
                if not state.capture_queue:
                    return
                frame = state.capture_queue.popleft()
                persist_capture(frame)

            def start_camera():
                if not product.value:
                    ui.notify("Select a product before start", color="warning")
                    return
                if state.running:
                    ui.notify("Camera is already running", color="warning")
                    return
                camera_service.start(on_frame=on_frame, on_capture=lambda frame: state.capture_queue.append(frame))
                state.running = True
                camera_status.set_text("Running")
                camera_status.props("color=positive")
                ui.notify("Camera started", color="positive")

            def stop_camera():
                if not state.running:
                    return
                camera_service.stop()
                state.running = False
                camera_status.set_text("Stopped")
                camera_status.props("color=grey")
                ui.notify("Camera stopped", color="warning")

            def manual_capture():
                if state.last_frame is None:
                    ui.notify("No frame available", color="warning")
                    return
                state.capture_queue.append(state.last_frame.copy())

            def open_last_capture():
                if not state.last_result.get("image"):
                    ui.notify("No captured image yet", color="warning")
                    return
                with ui.dialog() as dialog, ui.card().classes("w-[780px]"):
                    ui.label("Last Captured Image").classes("text-lg font-semibold")
                    ui.image(f"/data{state.last_result['image']}").classes("w-full max-h-[70vh] object-contain")
                    ui.button("Close", on_click=dialog.close)
                dialog.open()

            start_btn.on_click(start_camera)
            stop_btn.on_click(stop_camera)
            manual_btn.on_click(manual_capture)
            view_btn.on_click(open_last_capture)

            def refresh_preview():
                if state.preview_b64:
                    image_view.set_source(f"data:image/jpeg;base64,{state.preview_b64}")

            ui.timer(0.1, refresh_preview)
            ui.timer(0.1, process_capture_queue)
            ui.context.client.on_disconnect(stop_camera)

    @ui.page("/user/history")
    def user_history_page():
        user = require_ui_role("USER")
        if not user:
            return
        navbar(user, "Scan History", nav_links=[("Scan", "/user/scan"), ("Scan History", "/user/history")])

        with SessionLocal() as db:
            products = db.scalars(select(Product).order_by(Product.name)).all()

        with ui.column().classes("p-4 w-full"):
            product_map = {p.id: p.name for p in products}
            with ui.row().classes("gap-3"):
                start_at = ui.input("Start (YYYY-MM-DD)")
                end_at = ui.input("End (YYYY-MM-DD)")
                product_filter = ui.select({"": "All", **product_map}, value="", label="Product")
                defect_only = ui.switch("Defects only", value=False)
                ui.button(
                    "Apply",
                    on_click=lambda: build_scan_history(history_area, user, start_at, end_at, product_filter, defect_only),
                )
            history_area = ui.column().classes("w-full")

            build_scan_history(history_area, user, start_at, end_at, product_filter, defect_only)
