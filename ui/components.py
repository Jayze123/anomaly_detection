from __future__ import annotations

from collections.abc import Callable

from nicegui import app, ui
from sqlalchemy import select
from app.core.security import create_access_token, decode_token
from app.db import crud
from app.db.models import Factory, User, UserRoleEnum
from app.db.session import SessionLocal

TEMP_LOGIN_EMAIL = "temp@local"
TEMP_LOGIN_PASSWORD = "TempPass123!"


def get_session_user() -> dict | None:
    token = app.storage.user.get("token")
    if token:
        try:
            payload = decode_token(token)
        except ValueError:
            return None
        with SessionLocal() as db:
            user = db.get(User, payload.get("sub"))
            if not user or not user.is_active:
                return None
            effective_user_role = user.user_role or (UserRoleEnum.ADMIN.value if user.role == "ADMIN" else UserRoleEnum.STAFF.value)
            return {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
                "user_role": effective_user_role,
                "factory_id": user.factory_id,
                "factory_name": user.factory.name if user.factory else "",
                "token": token,
            }

    temp_user = app.storage.user.get("temp_user")
    if temp_user:
        return temp_user
    return None


def login_user(email: str, password: str) -> dict | None:
    normalized_email = email.strip().lower()
    normalized_password = password.strip()
    if normalized_email in {TEMP_LOGIN_EMAIL, "temp"} and normalized_password == TEMP_LOGIN_PASSWORD:
        with SessionLocal() as db:
            admin_user = db.scalar(select(User).where(User.email == "admin@local"))
            if admin_user and admin_user.is_active:
                token = create_access_token(admin_user.id, admin_user.role)
                payload = {
                    "id": admin_user.id,
                    "email": admin_user.email,
                    "full_name": admin_user.full_name,
                    "role": admin_user.role,
                    "user_role": admin_user.user_role or UserRoleEnum.ADMIN.value,
                    "factory_id": admin_user.factory_id,
                    "factory_name": admin_user.factory.name if admin_user.factory else "",
                    "token": token,
                }
                app.storage.user.clear()
                app.storage.user.update(payload)
                return payload

        # Fallback temp session if seeded admin does not exist
        payload = {
            "id": "temp-admin-id",
            "email": TEMP_LOGIN_EMAIL,
            "full_name": "Temporary Admin",
            "role": "ADMIN",
            "user_role": UserRoleEnum.ADMIN.value,
            "factory_id": "temp-factory-id",
            "factory_name": "Temporary Factory",
            "token": "",
        }
        app.storage.user.clear()
        app.storage.user.update({"temp_user": payload})
        return payload

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
            "user_role": user.user_role or (UserRoleEnum.ADMIN.value if user.role == "ADMIN" else UserRoleEnum.STAFF.value),
            "factory_id": user.factory_id,
            "factory_name": user.factory.name if user.factory else "",
            "token": token,
        }
        app.storage.user.clear()
        app.storage.user.update(payload)
        return payload


def logout_user() -> None:
    app.storage.user.clear()


def require_ui_role(required_role: str) -> dict | None:
    user = get_session_user()
    if not user:
        ui.notify("Session expired. Please login.", color="negative")
        ui.navigate.to("/login")
        return None

    role_value = str(user.get("role") or "").strip().upper()
    user_role_value = str(user.get("user_role") or "").strip().lower()

    is_admin = role_value == "ADMIN" or user_role_value == UserRoleEnum.ADMIN.value
    is_staff = role_value in {"USER", "STAFF"} or user_role_value == UserRoleEnum.STAFF.value

    allowed = (required_role == "ADMIN" and is_admin) or (required_role == "USER" and is_staff)
    if not allowed:
        ui.notify(f"Access denied. Login as {required_role}.", color="negative")
        ui.navigate.to("/login")
        return None
    return user


def navbar(user: dict, title: str, nav_links: list[tuple[str, str]] | None = None):
    with ui.header().classes("items-center justify-between bg-slate-900 text-white"):
        with ui.row().classes("items-center gap-4"):
            ui.label("Anomaly Detection").classes("text-lg font-bold")
            ui.label(title).classes("text-sm opacity-80")
            if nav_links:
                for label, target in nav_links:
                    ui.button(label, on_click=lambda t=target: ui.navigate.to(t)).props(
                        "flat no-caps text-color=white"
                    ).classes("text-xs")
        with ui.row().classes("items-center gap-4"):
            if user.get("user_role") != UserRoleEnum.ADMIN.value:
                ui.button("Admin Login", on_click=lambda: (logout_user(), ui.navigate.to("/login?next=/admin/dashboard"))).props(
                    "flat no-caps text-color=white"
                ).classes("text-xs")
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


def page_footer() -> None:
    with ui.footer().classes("items-center justify-between bg-slate-100 text-slate-600 px-4 py-2"):
        ui.label("Anomaly Detection Admin").classes("text-xs")
        ui.label("Internal Visual Inspection System").classes("text-xs")


def admin_side_nav() -> None:
    with ui.left_drawer(top_corner=True, bottom_corner=True).classes("bg-slate-900 text-white"):
        ui.label("Admin Navigation").classes("text-sm font-bold p-2")
        with ui.column().classes("w-full gap-1 p-2"):
            ui.button("Dashboard", on_click=lambda: ui.navigate.to("/admin/dashboard")).props(
                "flat no-caps align=left text-color=white"
            ).classes("w-full justify-start")
            ui.button("Factories", on_click=lambda: ui.navigate.to("/admin/factories")).props(
                "flat no-caps align=left text-color=white"
            ).classes("w-full justify-start")
            ui.button("Users", on_click=lambda: ui.navigate.to("/admin/users")).props(
                "flat no-caps align=left text-color=white"
            ).classes("w-full justify-start")
            ui.button("Products", on_click=lambda: ui.navigate.to("/admin/products")).props(
                "flat no-caps align=left text-color=white"
            ).classes("w-full justify-start")
            ui.button("Add Product", on_click=lambda: ui.navigate.to("/admin/products/new")).props(
                "flat no-caps align=left text-color=white"
            ).classes("w-full justify-start")
