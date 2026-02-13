from nicegui import ui

from ui.components import TEMP_LOGIN_EMAIL, TEMP_LOGIN_PASSWORD, login_user


def register_auth_routes() -> None:
    @ui.page("/login")
    def login_page():
        ui.add_css("body { background: linear-gradient(120deg,#f8fafc,#e2e8f0); }")
        with ui.column().classes("w-full h-screen items-center justify-center"):
            with ui.card().classes("w-full max-w-md p-6 shadow-2xl"):
                ui.label("Anomaly Detection Login").classes("text-2xl font-bold")
                email = ui.input("Email", value=TEMP_LOGIN_EMAIL).props("outlined")
                password = ui.input("Password", value=TEMP_LOGIN_PASSWORD, password=True).props("outlined")
                ui.label(f"Temporary login: {TEMP_LOGIN_EMAIL} / {TEMP_LOGIN_PASSWORD}").classes("text-xs text-slate-500")

                def do_login():
                    user = login_user(email.value.strip(), password.value)
                    if not user:
                        ui.notify("Invalid credentials", color="negative")
                        return
                    ui.notify("Login successful", color="positive")
                    ui.navigate.to("/admin/dashboard" if user["role"] == "ADMIN" else "/user/scan")

                ui.button("Login", on_click=do_login).classes("w-full")
