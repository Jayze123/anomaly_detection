from fastapi import FastAPI
from nicegui import ui

from ui.admin_ui import register_admin_routes
from ui.auth_ui import register_auth_routes
from ui.user_ui import register_user_routes


def register_ui(app: FastAPI) -> None:
    _ = app
    
    @ui.page("/")
    def landing_page():
        ui.add_css(
            """
            body { background: linear-gradient(120deg, #f8fafc, #e2e8f0); }
            .landing-card { max-width: 720px; width: 100%; }
            """
        )
        with ui.column().classes("w-full h-screen items-center justify-center p-6"):
            with ui.card().classes("landing-card p-8 shadow-2xl"):
                ui.label("Anomaly Detection").classes("text-3xl font-bold text-slate-900")
                ui.label("Industrial visual inspection platform").classes("text-slate-600 mb-6")
                with ui.row().classes("w-full gap-3"):
                    ui.button("Product Scan", on_click=lambda: ui.navigate.to("/login?next=/user/scan")).classes("flex-1")
                    ui.button("Admin Login", on_click=lambda: ui.navigate.to("/login?next=/admin/dashboard")).props("outline").classes("flex-1")

    register_auth_routes()
    register_admin_routes()
    register_user_routes()
