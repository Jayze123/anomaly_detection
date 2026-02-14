from nicegui import ui

from ui.components import TEMP_LOGIN_EMAIL, TEMP_LOGIN_PASSWORD, login_user


def register_auth_routes() -> None:
    @ui.page("/login")
    def login_page():
        next_target = ui.context.client.request.query_params.get("next")
        if not next_target or not next_target.startswith("/"):
            next_target = None

        ui.add_css("body { background: linear-gradient(120deg,#f8fafc,#e2e8f0); }")
        with ui.column().classes("w-full h-screen items-center justify-center"):
            with ui.card().classes("w-full max-w-md p-6 shadow-2xl"):
                ui.label("Anomaly Detection Login").classes("text-2xl font-bold")
                email = ui.input("Email").props("outlined")
                password = ui.input("Password", password=True).props("outlined")
                ui.label("Staff: user@local / user123").classes("text-xs text-slate-500")
                ui.label(f"Temporary admin: {TEMP_LOGIN_EMAIL} / {TEMP_LOGIN_PASSWORD}").classes("text-xs text-slate-500")

                def do_login():
                    user = login_user(email.value.strip(), password.value)
                    if not user:
                        ui.notify("Invalid credentials", color="negative")
                        return
                    ui.notify("Login successful", color="positive")
                    role_target = "/admin/dashboard" if user.get("user_role") == "admin" else "/user/scan"
                    if next_target:
                        if (user.get("user_role") == "admin" and next_target.startswith("/admin")) or (
                            user.get("user_role") != "admin" and next_target.startswith("/user")
                        ):
                            ui.navigate.to(next_target)
                            return
                    ui.navigate.to(role_target)

                ui.button("Login", on_click=do_login).classes("w-full")
