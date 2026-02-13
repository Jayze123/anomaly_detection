from fastapi import FastAPI

from ui.admin_ui import register_admin_routes
from ui.auth_ui import register_auth_routes
from ui.user_ui import register_user_routes


def register_ui(app: FastAPI) -> None:
    _ = app
    register_auth_routes()
    register_admin_routes()
    register_user_routes()
