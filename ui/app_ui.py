from fastapi import FastAPI
from nicegui import ui

from ui.admin_ui import register_admin_routes
from ui.auth_ui import register_auth_routes
from ui.components import get_session_user
from ui.user_ui import register_user_routes


def register_ui(app: FastAPI) -> None:
    _ = app
    
    @ui.page("/")
    def root_redirect():
        user = get_session_user()
        if not user:
            ui.navigate.to("/login")
            return
        ui.navigate.to("/admin/dashboard" if user["role"] == "ADMIN" else "/user/scan")

    register_auth_routes()
    register_admin_routes()
    register_user_routes()
