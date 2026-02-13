from nicegui import ui

from ui.components import login_user


def register_auth_routes() -> None:
    @ui.page("/login")
    def login_page():
        ui.add_css("body { background: linear-gradient(120deg,#f8fafc,#e2e8f0); }")
        with ui.column().classes("w-full h-screen items-center justify-center"):
            with ui.card().classes("w-full max-w-md p-6 shadow-2xl"):
                ui.label("Anomaly Inspection Login").classes("text-2xl font-bold")
                email = ui.input("Email", value="admin@local").props("outlined")
                password = ui.input("Password", value="admin123", password=True).props("outlined")

                def do_login():
                    user = login_user(email.value.strip(), password.value)
                    if not user:
                        ui.notify("Invalid credentials", color="negative")
                        return
                    ui.notify("Login successful", color="positive")
                    ui.navigate.to("/admin/dashboard" if user["role"] == "ADMIN" else "/user/scan")

                ui.button("Login", on_click=do_login).classes("w-full")
