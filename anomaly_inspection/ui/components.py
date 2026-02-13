from __future__ import annotations

from collections.abc import Callable

from nicegui import app, ui
from app.core.security import create_access_token, decode_token
from app.db import crud
from app.db.models import Factory, User
from app.db.session import SessionLocal


def get_session_user() -> dict | None:
    token = app.storage.user.get("token")
    if not token:
        return None
    try:
        payload = decode_token(token)
    except ValueError:
        return None
    with SessionLocal() as db:
        user = db.get(User, payload.get("sub"))
        if not user or not user.is_active:
            return None
        return {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "factory_id": user.factory_id,
            "factory_name": user.factory.name if user.factory else "",
            "token": token,
        }


def login_user(email: str, password: str) -> dict | None:
    with SessionLocal() as db:
        user = crud.authenticate_user(db, email, password)
        if not user or not user.is_active:
            return None
        token = create_access_token(user.id, user.role)
        payload = {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "factory_id": user.factory_id,
            "factory_name": user.factory.name if user.factory else "",
            "token": token,
        }
        app.storage.user.update(payload)
        return payload


def logout_user() -> None:
    app.storage.user.clear()


def require_ui_role(required_role: str) -> dict:
    user = get_session_user()
    if not user:
        ui.notify("Session expired. Please login.", color="negative")
        ui.navigate.to("/login")
        raise RuntimeError("unauthenticated")
    if user["role"] != required_role:
        ui.notify("Access denied", color="negative")
        if user["role"] == "ADMIN":
            ui.navigate.to("/admin/dashboard")
        else:
            ui.navigate.to("/user/scan")
        raise RuntimeError("forbidden")
    return user


def navbar(user: dict, title: str):
    with ui.header().classes("items-center justify-between bg-slate-900 text-white"):
        with ui.row().classes("items-center gap-4"):
            ui.label("Anomaly Inspection").classes("text-lg font-bold")
            ui.label(title).classes("text-sm opacity-80")
        with ui.row().classes("items-center gap-4"):
            ui.label(f"{user['full_name']} ({user['role']})")
            if user["role"] == "USER":
                ui.label(user.get("factory_name", "")).classes("text-xs")
            ui.button("Logout", on_click=lambda: (logout_user(), ui.navigate.to("/login"))).props("outline color=white")


def confirm_dialog(message: str, on_confirm: Callable[[], None]):
    with ui.dialog() as dialog, ui.card():
        ui.label(message)
        with ui.row():
            ui.button("Cancel", on_click=dialog.close)
            ui.button("Confirm", on_click=lambda: (on_confirm(), dialog.close())).props("color=negative")
    dialog.open()


def fetch_factory_options() -> list[tuple[str, str]]:
    with SessionLocal() as db:
        from sqlalchemy import select

        return [(f.id, f.name) for f in db.scalars(select(Factory).order_by(Factory.name)).all()]
