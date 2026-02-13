from __future__ import annotations

import io

from nicegui import ui
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
import numpy as np
from PIL import Image

from app.db import crud
from app.db.models import Factory, Product, ProductCategory, ProductStatus, ProductStatusImage, Scan, ScanImage, User
from app.db.session import SessionLocal
from app.core.security import hash_password
from app.services.storage import absolute_path, delete_file, store_frame_bytes
from ui.components import admin_side_nav, confirm_dialog, navbar, page_footer, require_ui_role

STANDARD_PRODUCT_CATEGORIES = ["Bottle", "Cable", "Wood", "Tile", "Leather"]


def register_admin_routes() -> None:
    @ui.page("/admin/dashboard")
    def admin_dashboard():
        user = require_ui_role("ADMIN")
        navbar(user, "Dashboard")
        admin_side_nav()
        with SessionLocal() as db:
            total_products = db.scalar(select(func.count()).select_from(Product)) or 0
            scans_today = db.scalar(select(func.count()).select_from(Scan).where(func.date(Scan.captured_at) == func.current_date())) or 0
            defects_today = db.scalar(
                select(func.count()).select_from(Scan).where(func.date(Scan.captured_at) == func.current_date(), Scan.is_defect.is_(True))
            ) or 0
            active_users = db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True))) or 0
            defect_rate = (defects_today / scans_today * 100) if scans_today else 0.0
            scans = db.execute(
                select(Scan, Product.name, User.full_name, Factory.name)
                .join(Product, Product.id == Scan.product_id)
                .join(User, User.id == Scan.user_id)
                .join(Factory, Factory.id == Scan.factory_id)
                .order_by(Scan.captured_at.desc())
                .limit(10)
            ).all()

        with ui.column().classes("p-4 w-full"):
            with ui.row().classes("w-full gap-3"):
                for title, value in [
                    ("Total Products", total_products),
                    ("Scans Today", scans_today),
                    ("Defect Rate Today", f"{defect_rate:.2f}%"),
                    ("Active Users", active_users),
                ]:
                    with ui.card().classes("p-4 w-1/4"):
                        ui.label(title).classes("text-sm text-slate-500")
                        ui.label(str(value)).classes("text-2xl font-bold")

            rows = []
            for s, product_name, user_name, factory_name in scans:
                rows.append(
                    {
                        "id": s.id,
                        "time": s.captured_at.isoformat(timespec="seconds"),
                        "product": product_name,
                        "status": s.predicted_status,
                        "confidence": f"{s.confidence:.2f}",
                        "user": user_name,
                        "factory": factory_name,
                    }
                )

            ui.label("Last 10 scans").classes("text-lg mt-4")
            table = ui.table(
                columns=[
                    {"name": "time", "label": "Time", "field": "time", "sortable": True},
                    {"name": "product", "label": "Product", "field": "product", "sortable": True},
                    {"name": "status", "label": "Status", "field": "status", "sortable": True},
                    {"name": "confidence", "label": "Confidence", "field": "confidence", "sortable": True},
                    {"name": "user", "label": "User", "field": "user", "sortable": True},
                    {"name": "factory", "label": "Factory", "field": "factory", "sortable": True},
                ],
                rows=rows,
                row_key="id",
                pagination=10,
            ).classes("w-full")

            def open_scan(e):
                with SessionLocal() as db:
                    scan = db.get(Scan, e.args["id"])
                    images = db.scalars(select(ScanImage).where(ScanImage.scan_id == scan.id)).all()
                with ui.dialog() as d, ui.card().classes("w-[720px]"):
                    ui.label(f"Scan {scan.id}").classes("text-lg font-bold")
                    ui.label(f"Status: {scan.predicted_status} ({scan.confidence:.2f})")
                    for img in images:
                        ui.image(f"/data{img.image_path}").classes("max-h-64")
                    ui.button("Close", on_click=d.close)
                d.open()

            table.on("rowClick", open_scan)
        page_footer()

    @ui.page("/admin/factories")
    def admin_factories():
        user = require_ui_role("ADMIN")
        navbar(user, "Factories")
        admin_side_nav()

        with ui.column().classes("p-4 w-full"):
            search = ui.input("Search by name/location").props("outlined clearable")
            body = ui.column().classes("w-full")

            def render():
                body.clear()
                with SessionLocal() as db:
                    q = select(Factory)
                    if search.value:
                        like = f"%{search.value}%"
                        q = q.where((Factory.name.ilike(like)) | (Factory.location.ilike(like)))
                    data = db.scalars(q.order_by(Factory.name)).all()

                with body:
                    ui.button("Add Factory", on_click=lambda: open_form()).props("color=primary")
                    rows = [{"id": f.id, "name": f.name, "location": f.location, "category": f.category} for f in data]
                    table = ui.table(
                        columns=[
                            {"name": "name", "label": "Name", "field": "name", "sortable": True},
                            {"name": "location", "label": "Location", "field": "location", "sortable": True},
                            {"name": "category", "label": "Category", "field": "category", "sortable": True},
                            {"name": "actions", "label": "Actions", "field": "actions"},
                        ],
                        rows=rows,
                        row_key="id",
                        pagination=10,
                    ).classes("w-full")
                    table.add_slot(
                        "body-cell-actions",
                        """
                        <q-td :props=\"props\"> 
                            <q-btn dense flat icon=\"edit\" @click=\"$parent.$emit('edit', props.row.id)\"/>
                            <q-btn dense flat icon=\"delete\" color=\"negative\" @click=\"$parent.$emit('remove', props.row.id)\"/>
                        </q-td>
                        """,
                    )
                    table.on("edit", lambda e: open_form(e.args))
                    table.on("remove", lambda e: confirm_dialog("Delete factory?", lambda: do_delete(e.args)))

            def do_delete(factory_id: str):
                with SessionLocal() as db:
                    item = db.get(Factory, factory_id)
                    if item:
                        db.delete(item)
                        db.commit()
                ui.notify("Factory deleted", color="positive")
                render()

            def open_form(factory_id: str | None = None):
                item = None
                if factory_id:
                    with SessionLocal() as db:
                        item = db.get(Factory, factory_id)
                with ui.dialog() as d, ui.card().classes("w-[520px]"):
                    name = ui.input("Name", value=item.name if item else "").classes("w-full")
                    location = ui.input("Location", value=item.location if item else "").classes("w-full")
                    category = ui.input("Category", value=item.category if item else "").classes("w-full")

                    def save():
                        with SessionLocal() as db:
                            target = db.get(Factory, factory_id) if factory_id else Factory()
                            target.name = name.value
                            target.location = location.value
                            target.category = category.value
                            db.add(target)
                            db.commit()
                        d.close()
                        ui.notify("Saved", color="positive")
                        render()

                    with ui.row().classes("w-full justify-end gap-2"):
                        ui.button("Cancel", on_click=d.close)
                        ui.button("Save", on_click=save).props("color=primary")
                d.open()

            search.on("change", lambda _: render())
            render()
        page_footer()

    @ui.page("/admin/users")
    def admin_users():
        user = require_ui_role("ADMIN")
        navbar(user, "Users")
        admin_side_nav()

        with ui.column().classes("p-4 w-full"):
            content = ui.column().classes("w-full")

            def open_form(user_id: str | None = None):
                u = None
                with SessionLocal() as db:
                    factories = db.scalars(select(Factory).order_by(Factory.name)).all()
                    if user_id:
                        u = db.get(User, user_id)
                with ui.dialog() as d, ui.card().classes("w-[560px]"):
                    email = ui.input("Email", value=u.email if u else "")
                    full_name = ui.input("Full Name", value=u.full_name if u else "")
                    factory_map = {f.name: f.id for f in factories}
                    factory = ui.select(factory_map, value=(u.factory_id if u else next(iter(factory_map.values()), None)), label="Factory")
                    role = ui.select(["ADMIN", "USER"], value=u.role if u else "USER", label="Role")
                    active = ui.switch("Active", value=u.is_active if u else True)
                    password = ui.input("Password (optional)", password=True)

                    def save():
                        with SessionLocal() as db:
                            target = db.get(User, user_id) if user_id else User()
                            target.email = email.value.strip().lower()
                            target.full_name = full_name.value
                            target.factory_id = factory.value
                            target.role = role.value
                            target.is_active = active.value
                            if not user_id:
                                target.password_hash = hash_password(password.value or "temp12345")
                            elif password.value:
                                target.password_hash = hash_password(password.value)
                            db.add(target)
                            db.commit()
                        d.close()
                        render()
                        ui.notify("User saved", color="positive")

                    with ui.row():
                        ui.button("Cancel", on_click=d.close)
                        ui.button("Save", on_click=save).props("color=primary")
                d.open()

            def reset_pwd(user_id: str):
                import secrets

                pwd = secrets.token_urlsafe(8)
                with SessionLocal() as db:
                    target = db.get(User, user_id)
                    target.password_hash = hash_password(pwd)
                    db.add(target)
                    db.commit()
                ui.notify(f"Temporary password: {pwd}", color="warning", timeout=8000)

            def remove(user_id: str):
                with SessionLocal() as db:
                    target = db.get(User, user_id)
                    if target:
                        db.delete(target)
                        db.commit()
                render()
                ui.notify("User deleted", color="positive")

            def render():
                content.clear()
                with SessionLocal() as db:
                    rows = db.execute(select(User, Factory.name).join(Factory, Factory.id == User.factory_id)).all()
                mapped = [
                    {
                        "id": u.id,
                        "email": u.email,
                        "full_name": u.full_name,
                        "role": u.role,
                        "factory": factory_name,
                        "active": "Yes" if u.is_active else "No",
                    }
                    for u, factory_name in rows
                ]
                with content:
                    ui.button("Add User", on_click=lambda: open_form()).props("color=primary")
                    table = ui.table(
                        columns=[
                            {"name": "email", "label": "Email", "field": "email", "sortable": True},
                            {"name": "full_name", "label": "Name", "field": "full_name", "sortable": True},
                            {"name": "role", "label": "Role", "field": "role", "sortable": True},
                            {"name": "factory", "label": "Factory", "field": "factory", "sortable": True},
                            {"name": "active", "label": "Active", "field": "active", "sortable": True},
                            {"name": "actions", "label": "Actions", "field": "actions"},
                        ],
                        rows=mapped,
                        row_key="id",
                        pagination=10,
                    ).classes("w-full")
                    table.add_slot(
                        "body-cell-actions",
                        """
                        <q-td :props=\"props\"> 
                            <q-btn dense flat icon=\"vpn_key\" @click=\"$parent.$emit('reset', props.row.id)\"/>
                            <q-btn dense flat icon=\"edit\" @click=\"$parent.$emit('edit', props.row.id)\"/>
                            <q-btn dense flat icon=\"delete\" color=\"negative\" @click=\"$parent.$emit('remove', props.row.id)\"/>
                        </q-td>
                        """,
                    )
                    table.on("reset", lambda e: reset_pwd(e.args))
                    table.on("edit", lambda e: open_form(e.args))
                    table.on("remove", lambda e: confirm_dialog("Delete user?", lambda: remove(e.args)))

            render()
        page_footer()

    @ui.page("/admin/products")
    def admin_products():
        user = require_ui_role("ADMIN")
        navbar(user, "Products")
        admin_side_nav()

        with ui.column().classes("p-4 w-full"):
            search = ui.input("Search by name/category").props("outlined clearable")
            body = ui.column().classes("w-full")
            form_state: dict[str, str | None] = {"product_id": None}

            def ensure_standard_categories() -> list[tuple[str, str]]:
                with SessionLocal() as db:
                    existing = db.scalars(select(ProductCategory)).all()
                    by_name = {c.name.lower(): c for c in existing}
                    for cat_name in STANDARD_PRODUCT_CATEGORIES:
                        if cat_name.lower() not in by_name:
                            c = ProductCategory(name=cat_name, description=f"{cat_name} products")
                            db.add(c)
                            db.flush()
                            by_name[cat_name.lower()] = c
                    db.commit()
                    return [(by_name[cat_name.lower()].id, by_name[cat_name.lower()].name) for cat_name in STANDARD_PRODUCT_CATEGORIES]

            with ui.dialog() as product_dialog, ui.card().classes("w-[560px]"):
                ui.label("Product Form").classes("text-lg font-bold")
                category = ui.select({}, label="Category").classes("w-full")
                name = ui.input("Name").classes("w-full")
                description = ui.textarea("Description").classes("w-full")

                def save_form():
                    clean_name = str(name.value or "").strip()
                    if not category.value:
                        ui.notify("Category is required", color="negative")
                        return
                    if not clean_name:
                        ui.notify("Product name is required", color="negative")
                        return

                    product_id = form_state["product_id"]
                    with SessionLocal() as db:
                        target = db.get(Product, product_id) if product_id else Product()
                        target.category_id = category.value
                        target.name = clean_name
                        target.description = description.value
                        db.add(target)
                        db.commit()
                    product_dialog.close()
                    render()
                    ui.notify("Product saved", color="positive")

                with ui.row():
                    ui.button("Cancel", on_click=product_dialog.close)
                    ui.button("Save", on_click=save_form).props("color=primary")

            def open_form(product_id: str | None = None):
                p = None
                with SessionLocal() as db:
                    if product_id:
                        p = db.get(Product, product_id)
                categories = ensure_standard_categories()
                category_map = {cat_id: cat_name for cat_id, cat_name in categories}
                category.options = category_map
                category.value = p.category_id if p else next(iter(category_map.keys()), None)
                name.value = p.name if p else ""
                description.value = p.description if p else ""
                form_state["product_id"] = product_id
                product_dialog.open()

            def remove(product_id: str):
                with SessionLocal() as db:
                    p = db.get(Product, product_id)
                    if p:
                        db.delete(p)
                        db.commit()
                render()
                ui.notify("Product deleted", color="positive")

            def render():
                body.clear()
                with SessionLocal() as db:
                    q = select(Product, ProductCategory.name).join(ProductCategory, Product.category_id == ProductCategory.id)
                    if search.value:
                        like = f"%{search.value}%"
                        q = q.where((Product.name.ilike(like)) | (ProductCategory.name.ilike(like)))
                    rows = db.execute(q.order_by(Product.created_at.desc())).all()

                with body:
                    ui.button("Add New Product", on_click=lambda: open_form(None)).props("color=primary")
                    table_rows = [
                        {
                            "id": p.id,
                            "name": p.name,
                            "category": category_name,
                            "description": (p.description or "")[:80],
                        }
                        for p, category_name in rows
                    ]
                    table = ui.table(
                        columns=[
                            {"name": "name", "label": "Name", "field": "name", "sortable": True},
                            {"name": "category", "label": "Category", "field": "category", "sortable": True},
                            {"name": "description", "label": "Description", "field": "description"},
                            {"name": "actions", "label": "Actions", "field": "actions"},
                        ],
                        rows=table_rows,
                        row_key="id",
                        pagination=10,
                    ).classes("w-full")
                    table.add_slot(
                        "body-cell-actions",
                        """
                        <q-td :props=\"props\"> 
                            <q-btn dense flat icon=\"visibility\" @click=\"$parent.$emit('view', props.row.id)\"/>
                            <q-btn dense flat icon=\"edit\" @click=\"$parent.$emit('edit', props.row.id)\"/>
                            <q-btn dense flat icon=\"delete\" color=\"negative\" @click=\"$parent.$emit('remove', props.row.id)\"/>
                        </q-td>
                        """,
                    )
                    table.on("view", lambda e: ui.navigate.to(f"/admin/products/{e.args}"))
                    table.on("edit", lambda e: open_form(e.args))
                    table.on("remove", lambda e: confirm_dialog("Delete product?", lambda: remove(e.args)))

            search.on("change", lambda _: render())
            render()
        page_footer()

    @ui.page("/admin/products/new")
    def admin_product_new():
        user = require_ui_role("ADMIN")
        navbar(user, "Add Product")
        admin_side_nav()

        with SessionLocal() as db:
            existing = db.scalars(select(ProductCategory)).all()
            by_name = {c.name.lower(): c for c in existing}
            for cat_name in STANDARD_PRODUCT_CATEGORIES:
                if cat_name.lower() not in by_name:
                    c = ProductCategory(name=cat_name, description=f"{cat_name} products")
                    db.add(c)
                    db.flush()
                    by_name[cat_name.lower()] = c
            db.commit()
            categories = [by_name[n.lower()] for n in STANDARD_PRODUCT_CATEGORIES]

        with ui.column().classes("p-4 w-full max-w-3xl mx-auto"):
            with ui.card().classes("w-full p-5"):
                ui.label("Product Information").classes("text-2xl font-bold")
                ui.label("Create a product record with production information and traceability data.").classes("text-sm text-slate-500")

                category_map = {c.id: c.name for c in categories}
                category = ui.select(
                    category_map,
                    value=next(iter(category_map.keys())),
                    label="Product Category",
                ).classes("w-full")

                ui.separator()
                ui.label("Basic Product Details").classes("text-lg font-semibold")
                name = ui.input("Product Name *").classes("w-full")
                product_code = ui.input("Product Code / SKU").classes("w-full")
                description = ui.textarea("Product Description").classes("w-full")

                ui.separator()
                ui.label("Production Information").classes("text-lg font-semibold")
                with ui.row().classes("w-full gap-2"):
                    production_line = ui.input("Production Line").classes("w-1/2")
                    station = ui.input("Station / Work Cell").classes("w-1/2")
                with ui.row().classes("w-full gap-2"):
                    batch_code = ui.input("Batch Code").classes("w-1/2")
                    lot_number = ui.input("Lot Number").classes("w-1/2")
                with ui.row().classes("w-full gap-2"):
                    shift = ui.select(["Morning", "Afternoon", "Night"], value="Morning", label="Shift").classes("w-1/2")
                    operator = ui.input("Operator").classes("w-1/2")
                notes = ui.textarea("Additional Production Notes").classes("w-full")
                summary = ui.markdown("").classes("text-xs text-slate-600")

                def submit():
                    product_name = str(name.value or "").strip()
                    if not product_name:
                        ui.notify("Product name is required", color="negative")
                        return
                    if not category.value:
                        ui.notify("Product category is required", color="negative")
                        return

                    with SessionLocal() as db:
                        existing = db.scalar(select(Product).where(func.lower(Product.name) == product_name.lower()))
                        if existing:
                            ui.notify("A product with this name already exists", color="warning")
                            return

                    merged_description = (description.value or "").strip()
                    production_meta = (
                        f"\\n\\nProduction Information\\n"
                        f"- Product Code: {product_code.value or 'N/A'}\\n"
                        f"- Line: {production_line.value or 'N/A'}\\n"
                        f"- Station: {station.value or 'N/A'}\\n"
                        f"- Batch: {batch_code.value or 'N/A'}\\n"
                        f"- Lot: {lot_number.value or 'N/A'}\\n"
                        f"- Shift: {shift.value or 'N/A'}\\n"
                        f"- Operator: {operator.value or 'N/A'}\\n"
                        f"- Notes: {notes.value or 'N/A'}"
                    )
                    final_description = (merged_description + production_meta).strip()

                    with SessionLocal() as db:
                        item = Product(category_id=category.value, name=product_name, description=final_description)
                        db.add(item)
                        try:
                            db.commit()
                        except IntegrityError:
                            db.rollback()
                            ui.notify("Could not create product due to database constraint", color="negative")
                            return
                        db.refresh(item)
                    ui.notify("Product created", color="positive")
                    ui.navigate.to(f"/admin/products/{item.id}")

                def refresh_summary():
                    summary.content = (
                        f"**Preview**  \n"
                        f"- Name: {(name.value or '').strip() or '-'}  \n"
                        f"- Code/SKU: {(product_code.value or '').strip() or '-'}  \n"
                        f"- Line: {(production_line.value or '').strip() or '-'}  \n"
                        f"- Batch: {(batch_code.value or '').strip() or '-'}  \n"
                        f"- Shift: {(shift.value or '').strip() or '-'}"
                    )

                for c in [name, product_code, production_line, batch_code, shift]:
                    c.on("change", lambda _: refresh_summary())
                refresh_summary()

                with ui.row().classes("w-full justify-end gap-2 mt-2"):
                    ui.button("Cancel", on_click=lambda: ui.navigate.to("/admin/products")).props("flat")
                    ui.button("Reset", on_click=lambda: ui.navigate.to("/admin/products/new")).props("flat")
                    ui.button("Save Product", on_click=submit).props("color=primary")
        page_footer()

    @ui.page("/admin/products/{product_id}")
    def admin_product_detail(product_id: str):
        user = require_ui_role("ADMIN")
        navbar(user, "Product Detail")
        admin_side_nav()

        with SessionLocal() as db:
            product = db.get(Product, product_id)
            if not product:
                ui.notify("Product not found", color="negative")
                ui.navigate.to("/admin/products")
                return
            product_name = product.name
            product_description = product.description or ""
            category_name = product.category.name if product.category else "-"
            normal_status = db.scalar(
                select(ProductStatus).where(
                    ProductStatus.product_id == product_id,
                    func.upper(ProductStatus.status) == "NORMAL",
                )
            )
            if not normal_status:
                normal_status = ProductStatus(
                    product_id=product_id,
                    status="NORMAL",
                    status_description="Reference normal product condition",
                )
                db.add(normal_status)
                db.commit()
                db.refresh(normal_status)
            normal_status_id = normal_status.id

        def fetch_normal_reference() -> dict:
            with SessionLocal() as db:
                normal = db.scalar(
                    select(ProductStatus).where(
                        ProductStatus.product_id == product_id,
                        func.upper(ProductStatus.status) == "NORMAL",
                    )
                )
                if not normal:
                    normal = ProductStatus(
                        product_id=product_id,
                        status="NORMAL",
                        status_description="Reference normal product condition",
                    )
                    db.add(normal)
                    db.commit()
                    db.refresh(normal)
                images = db.scalars(
                    select(ProductStatusImage)
                    .where(ProductStatusImage.product_status_id == normal.id)
                    .order_by(ProductStatusImage.sort_order.asc())
                ).all()
                return {
                    "status_id": normal.id,
                    "status_description": normal.status_description or "",
                    "images": [{"id": i.id, "image_path": i.image_path, "sort_order": i.sort_order} for i in images],
                }

        normal_ref = fetch_normal_reference()
        normal_status_id = normal_ref["status_id"]

        with ui.column().classes("p-4 w-full"):
            ui.label(product_name).classes("text-2xl font-bold")
            ui.label(f"Category: {category_name}")
            ui.label(product_description)
            ui.separator()

            ui.label("1) Normal Product Reference").classes("text-xl font-semibold")
            ui.label("First add the normal product detail and up to 4 reference images.").classes("text-sm text-slate-600")
            normal_description = ui.textarea("Normal Product Details", value=normal_ref.get("status_description") or "").classes("w-full")
            normal_images_panel = ui.column().classes("w-full")

            status_list = None

            def manage_images(status_id: str, on_changed=None):
                with ui.drawer(side="right", value=True).classes("p-4 w-[460px]") as drawer:
                    ui.label("Manage Images").classes("text-lg font-bold")
                    grid = ui.column().classes("w-full")

                    def render_grid():
                        grid.clear()
                        with SessionLocal() as db:
                            local_imgs = db.scalars(
                                select(ProductStatusImage)
                                .where(ProductStatusImage.product_status_id == status_id)
                                .order_by(ProductStatusImage.sort_order)
                            ).all()
                        with grid:
                            for img in local_imgs:
                                with ui.row().classes("items-center justify-between w-full border p-2"):
                                    with ui.row().classes("items-center gap-2"):
                                        ui.image(f"/data{img.image_path}").classes("w-20 h-20")
                                        ui.label(f"Order {img.sort_order}")
                                    with ui.row():
                                        ui.button("Up", on_click=lambda i=img.id: move(i, -1)).props("flat")
                                        ui.button("Down", on_click=lambda i=img.id: move(i, 1)).props("flat")
                                        ui.button("Delete", on_click=lambda i=img.id: delete_img(i)).props("flat color=negative")

                    def move(image_id: str, delta: int):
                        with SessionLocal() as db:
                            all_imgs = db.scalars(
                                select(ProductStatusImage)
                                .where(ProductStatusImage.product_status_id == status_id)
                                .order_by(ProductStatusImage.sort_order)
                            ).all()
                            ids = [x.id for x in all_imgs]
                            idx = ids.index(image_id)
                            new_idx = max(0, min(len(ids) - 1, idx + delta))
                            ids[idx], ids[new_idx] = ids[new_idx], ids[idx]
                            crud.reorder_status_images(db, status_id, ids)
                            db.commit()
                        render_grid()
                        if on_changed:
                            on_changed()

                    def delete_img(image_id: str):
                        with SessionLocal() as db:
                            target = db.get(ProductStatusImage, image_id)
                            if target:
                                path = target.image_path
                                db.delete(target)
                                db.flush()
                                remain = db.scalars(
                                    select(ProductStatusImage)
                                    .where(ProductStatusImage.product_status_id == status_id)
                                    .order_by(ProductStatusImage.sort_order)
                                ).all()
                                for idx, im in enumerate(remain, start=1):
                                    im.sort_order = idx
                                    db.add(im)
                                db.commit()
                                delete_file(path)
                        render_grid()
                        if on_changed:
                            on_changed()

                    uploader = ui.upload(
                        on_upload=lambda e: upload_image(e, status_id),
                        max_file_size=5 * 1024 * 1024,
                        max_files=1,
                    ).props("accept=.png,.jpg,.jpeg")

                    def upload_image(e, sid: str):
                        raw = e.content.read()
                        ext = ".png" if e.name.lower().endswith(".png") else ".jpg"
                        with SessionLocal() as db:
                            count = db.scalar(
                                select(func.count()).select_from(ProductStatusImage).where(ProductStatusImage.product_status_id == sid)
                            ) or 0
                            if count >= 4:
                                ui.notify("Maximum of 4 images allowed per product status", color="negative")
                                return
                            path = store_frame_bytes(raw, f"status_images/{sid}", ext=ext)
                            order = crud.next_sort_order(db, sid)
                            db.add(ProductStatusImage(product_status_id=sid, image_path=path, sort_order=order))
                            db.commit()
                        render_grid()
                        if on_changed:
                            on_changed()

                    ui.button("Close", on_click=drawer.hide).props("flat")
                    render_grid()

            def render_normal_images():
                normal_images_panel.clear()
                ref = fetch_normal_reference()
                if not ref:
                    return
                normal_images = ref.get("images", [])
                with normal_images_panel:
                    ui.label(f"Normal reference images: {len(normal_images)}/4").classes("text-sm text-slate-600")
                    with ui.row().classes("gap-2"):
                        for img in normal_images:
                            ui.image(f"/data{img['image_path']}").classes("w-24 h-24 border rounded")
                    ui.button(
                        "Manage Normal Images",
                        on_click=lambda: open_normal_images_modal(),
                    ).props("color=primary")

            def save_normal_details():
                clean = (normal_description.value or "").strip()
                if not clean:
                    ui.notify("Normal product details are required", color="negative")
                    return
                with SessionLocal() as db:
                    normal = db.get(ProductStatus, normal_status_id)
                    if not normal:
                        ui.notify("Normal reference status not found", color="negative")
                        return
                    normal.status_description = clean
                    db.add(normal)
                    db.commit()
                ui.notify("Normal product details saved", color="positive")
                render_statuses()

            def normal_reference_ready() -> bool:
                ref = fetch_normal_reference()
                if not ref:
                    return False
                count = len(ref.get("images", []))
                return bool((ref.get("status_description") or "").strip()) and count > 0

            with ui.row().classes("w-full justify-end"):
                ui.button("Save Normal Details", on_click=save_normal_details).props("color=primary")
            render_normal_images()
            ui.separator()

            defect_section = ui.column().classes("w-full mt-3")
            with defect_section:
                ui.label("2) Possible Defect Types").classes("text-xl font-semibold")
                ui.label("After normal reference is complete, add defect statuses below.").classes("text-sm text-slate-600")
                status_list = ui.column().classes("w-full")

            def open_status_form(status_id: str | None = None):
                s = None
                existing_count = 0
                if status_id:
                    with SessionLocal() as db:
                        s = db.get(ProductStatus, status_id)
                        existing_count = db.scalar(
                            select(func.count()).select_from(ProductStatusImage).where(ProductStatusImage.product_status_id == status_id)
                        ) or 0
                pending_uploads: list[tuple[bytes, str, str]] = []  # (raw, ext, filename)
                defect_options = ["Broken Small", "Broken Large", "Contamination"]
                score_by_status = {
                    "Broken Small": 25.0,
                    "Broken Large": 50.0,
                    "Contamination": 75.0,
                }

                def parse_score_and_desc(raw_desc: str | None) -> tuple[float, str]:
                    text = (raw_desc or "").strip()
                    if not text:
                        return 0.0, ""
                    marker = "Defect Score:"
                    if marker in text:
                        parts = text.split(marker, 1)
                        desc_part = parts[0].strip()
                        return 0.0, desc_part
                    return 0.0, text

                _, initial_desc = parse_score_and_desc(s.status_description if s else "")
                initial_status = s.status if s and s.status in defect_options else None
                initial_score = score_by_status.get(initial_status or "", 0.0)
                with ui.dialog() as d, ui.card().classes("w-[680px] max-w-[96vw]"):
                    status = ui.select(defect_options, value=initial_status, label="Status").classes("w-full")
                    defect_score = ui.number("Defect Score (%)", value=initial_score, min=0, max=100, step=0.1, format="%.1f").classes("w-full").props("readonly")
                    desc = ui.textarea("Description", value=initial_desc).classes("w-full")
                    ui.separator()
                    ui.label("Defect Images (max 4 total)").classes("text-sm font-semibold")
                    count_label = ui.label(f"Images: {existing_count}/4 (existing), 0 pending").classes("text-xs text-slate-600")
                    pending_panel = ui.column().classes("w-full gap-1")

                    defect_score.bind_value_from(status, "value", lambda v: score_by_status.get(str(v or ""), 0.0))
                    defect_score.value = score_by_status.get(str(initial_status or ""), 0.0)
                    defect_score.update()

                    def refresh_pending_panel():
                        pending_panel.clear()
                        with pending_panel:
                            if not pending_uploads:
                                ui.label("No pending uploads").classes("text-xs text-slate-500")
                            else:
                                for idx, (_, _, filename) in enumerate(pending_uploads):
                                    with ui.row().classes("w-full items-center justify-between border rounded p-2"):
                                        ui.label(filename).classes("text-xs")
                                        ui.button(
                                            "Remove",
                                            on_click=lambda i=idx: remove_pending(i),
                                        ).props("flat color=negative")
                        count_label.set_text(
                            f"Images: {existing_count}/4 (existing), {len(pending_uploads)} pending"
                        )

                    def remove_pending(index: int):
                        if 0 <= index < len(pending_uploads):
                            pending_uploads.pop(index)
                            refresh_pending_panel()

                    async def upload_defect_image(e):
                        raw = await e.file.read()
                        if not raw:
                            ui.notify("Upload failed: empty file", color="negative")
                            return
                        if len(raw) > 5 * 1024 * 1024:
                            ui.notify("Image too large. Maximum size is 5MB.", color="negative")
                            return
                        current_total = existing_count + len(pending_uploads)
                        if current_total >= 4:
                            ui.notify("Maximum of 4 images allowed per defect type", color="negative")
                            return
                        ext = ".png" if e.file.name.lower().endswith(".png") else ".jpg"
                        pending_uploads.append((raw, ext, e.file.name))
                        refresh_pending_panel()
                        ui.notify("Image queued for save", color="positive")

                    ui.upload(
                        on_upload=upload_defect_image,
                        auto_upload=True,
                        max_file_size=5 * 1024 * 1024,
                        max_files=1,
                        label="Select Defect Image (JPG/PNG)",
                    ).props("accept=.jpg,.jpeg,.png").classes("w-full")
                    refresh_pending_panel()

                    def save():
                        clean_status = str(status.value or "").strip()
                        if not clean_status:
                            ui.notify("Status is required", color="negative")
                            return
                        if clean_status not in defect_options:
                            ui.notify("Select a valid defect status", color="negative")
                            return
                        score_value = score_by_status.get(clean_status, 0.0)
                        merged_desc = (desc.value or "").strip()
                        merged_desc = f"{merged_desc}\n\nDefect Score: {score_value:.1f}%".strip()
                        with SessionLocal() as db:
                            target = db.get(ProductStatus, status_id) if status_id else ProductStatus(product_id=product_id)
                            target.status = clean_status
                            target.status_description = merged_desc
                            db.add(target)
                            db.flush()

                            current_count = db.scalar(
                                select(func.count()).select_from(ProductStatusImage).where(ProductStatusImage.product_status_id == target.id)
                            ) or 0
                            if current_count + len(pending_uploads) > 4:
                                db.rollback()
                                ui.notify("Maximum of 4 images allowed per defect type", color="negative")
                                return

                            for raw, ext, _filename in pending_uploads:
                                path = store_frame_bytes(raw, f"status_images/{target.id}", ext=ext)
                                order = crud.next_sort_order(db, target.id)
                                db.add(ProductStatusImage(product_status_id=target.id, image_path=path, sort_order=order))

                            db.commit()
                        d.close()
                        if pending_uploads:
                            ui.notify(f"Saved status with {len(pending_uploads)} image(s)", color="positive")
                        render_statuses()

                    with ui.row():
                        ui.button("Cancel", on_click=d.close)
                        ui.button("Save", on_click=save).props("color=primary")
                d.open()

            def remove_status(status_id: str):
                with SessionLocal() as db:
                    s = db.get(ProductStatus, status_id)
                    if s:
                        db.delete(s)
                        db.commit()
                render_statuses()

            def _compute_image_quality(raw: bytes) -> tuple[bool, str, str, str]:
                try:
                    image = Image.open(io.BytesIO(raw)).convert("RGB")
                except Exception:
                    return False, "-", "-", "Invalid image file"

                width, height = image.size
                gray = np.asarray(image.convert("L"), dtype=np.float32)
                brightness = float(gray.mean())
                resolution = f"{width}x{height}"
                exposure = f"{brightness:.1f}"

                if width < 640 or height < 480:
                    return False, resolution, exposure, "Resolution too low (min 640x480)"
                if brightness < 60:
                    return False, resolution, exposure, "Exposure too dark"
                if brightness > 200:
                    return False, resolution, exposure, "Exposure too bright"
                return True, resolution, exposure, "OK"

            def open_normal_images_modal():
                with ui.dialog() as dialog, ui.card().classes("w-[820px] max-w-[96vw]"):
                    ui.label("Manage Normal Images").classes("text-xl font-bold")
                    ui.label("Upload one image at a time. Max file size is 5MB.").classes("text-sm text-slate-600")
                    panel = ui.column().classes("w-full")

                    def refresh_panel():
                        panel.clear()
                        ref = fetch_normal_reference()
                        if not ref:
                            return
                        images = ref.get("images", [])
                        with panel:
                            ui.label(f"Total images: {len(images)}/4").classes("text-sm text-slate-600")
                            for img in images:
                                abs_path = absolute_path(img["image_path"])
                                size_bytes = abs_path.stat().st_size if abs_path.exists() else 0
                                raw = abs_path.read_bytes() if abs_path.exists() else b""
                                _, res, exposure, quality = _compute_image_quality(raw) if raw else (False, "-", "-", "Missing file")
                                with ui.row().classes("w-full items-center justify-between border rounded p-2"):
                                    with ui.row().classes("items-center gap-3"):
                                        ui.image(f"/data{img['image_path']}").classes("w-20 h-20 border rounded")
                                        with ui.column().classes("gap-0"):
                                            ui.label(f"Order: {img['sort_order']}").classes("text-sm")
                                            ui.label(f"Size: {size_bytes / (1024 * 1024):.2f} MB").classes("text-xs text-slate-600")
                                            ui.label(f"Resolution: {res}").classes("text-xs text-slate-600")
                                            ui.label(f"Exposure: {exposure} ({quality})").classes("text-xs text-slate-600")
                                    ui.button(
                                        "Delete",
                                        on_click=lambda i=img["id"]: delete_normal_image(i),
                                    ).props("flat color=negative")

                    def delete_normal_image(image_id: str):
                        with SessionLocal() as db:
                            target = db.get(ProductStatusImage, image_id)
                            if not target or target.product_status_id != normal_status_id:
                                ui.notify("Image not found", color="negative")
                                return
                            path = target.image_path
                            db.delete(target)
                            db.flush()
                            remain = db.scalars(
                                select(ProductStatusImage)
                                .where(ProductStatusImage.product_status_id == normal_status_id)
                                .order_by(ProductStatusImage.sort_order.asc())
                            ).all()
                            for idx, im in enumerate(remain, start=1):
                                im.sort_order = idx
                                db.add(im)
                            db.commit()
                            delete_file(path)
                        refresh_panel()
                        render_normal_images()
                        render_statuses()

                    async def upload_normal_image(e):
                        try:
                            raw = await e.file.read()
                            if isinstance(raw, str):
                                raw = raw.encode("utf-8")
                            if not raw:
                                ui.notify("Upload failed: empty file content", color="negative")
                                return

                            size_bytes = len(raw)
                            if size_bytes > 5 * 1024 * 1024:
                                ui.notify("Image too large. Maximum size is 5MB.", color="negative")
                                return

                            ok, resolution, exposure, quality = _compute_image_quality(raw)
                            if not ok:
                                ui.notify(f"Image rejected: {quality} (resolution {resolution}, exposure {exposure})", color="negative")
                                return

                            ext = ".png" if e.file.name.lower().endswith(".png") else ".jpg"
                            with SessionLocal() as db:
                                count = db.scalar(
                                    select(func.count()).select_from(ProductStatusImage).where(ProductStatusImage.product_status_id == normal_status_id)
                                ) or 0
                                if count >= 4:
                                    ui.notify("Maximum of 4 images allowed for normal reference", color="negative")
                                    return
                                path = store_frame_bytes(raw, f"status_images/{normal_status_id}", ext=ext)
                                order = crud.next_sort_order(db, normal_status_id)
                                db.add(ProductStatusImage(product_status_id=normal_status_id, image_path=path, sort_order=order))
                                db.commit()

                            ui.notify(f"Image added ({resolution}, exposure {exposure})", color="positive")
                            refresh_panel()
                            render_normal_images()
                            render_statuses()
                            dialog.close()
                        except Exception as exc:
                            ui.notify(f"Upload failed: {exc}", color="negative")

                    ui.label("Upload Normal Reference Image").classes("text-sm font-semibold")
                    ui.upload(
                        on_upload=upload_normal_image,
                        auto_upload=True,
                        max_file_size=5 * 1024 * 1024,
                        max_files=1,
                        label="Select Image (JPG/PNG)",
                    ).props("accept=.jpg,.jpeg,.png").classes("w-full")
                    ui.label("Tip: image uploads immediately after selection.").classes("text-xs text-slate-500")

                    with ui.row().classes("w-full justify-end"):
                        ui.button("Close", on_click=dialog.close).props("flat")

                    refresh_panel()
                dialog.open()

            def render_statuses():
                status_list.clear()
                with SessionLocal() as db:
                    statuses = db.scalars(
                        select(ProductStatus).where(
                            ProductStatus.product_id == product_id,
                            func.upper(ProductStatus.status) != "NORMAL",
                        )
                    ).all()
                with status_list:
                    ready = normal_reference_ready()
                    if not ready:
                        ui.label("Complete normal details and upload at least 1 normal image to enable defect setup.").classes(
                            "text-sm text-orange-600"
                        )
                    ui.button("Add Defect Type", on_click=lambda: open_status_form()).props("color=primary").set_enabled(ready)
                    rows = []
                    with SessionLocal() as db:
                        for s in statuses:
                            image_count = db.scalar(
                                select(func.count()).select_from(ProductStatusImage).where(ProductStatusImage.product_status_id == s.id)
                            ) or 0
                            rows.append(
                                {
                                    "id": s.id,
                                    "status": s.status,
                                    "description": s.status_description or "",
                                    "images": image_count,
                                }
                            )
                    table = ui.table(
                        columns=[
                            {"name": "status", "label": "Status", "field": "status", "sortable": True},
                            {"name": "description", "label": "Description", "field": "description"},
                            {"name": "images", "label": "Images", "field": "images", "sortable": True},
                            {"name": "actions", "label": "Actions", "field": "actions"},
                        ],
                        rows=rows,
                        row_key="id",
                        pagination=10,
                    ).classes("w-full")
                    table.add_slot(
                        "body-cell-actions",
                        """
                        <q-td :props=\"props\"> 
                            <q-btn dense flat label=\"Images\" @click=\"$parent.$emit('images', props.row.id)\"/>
                            <q-btn dense flat icon=\"edit\" @click=\"$parent.$emit('edit', props.row.id)\"/>
                            <q-btn dense flat icon=\"delete\" color=\"negative\" @click=\"$parent.$emit('remove', props.row.id)\"/>
                        </q-td>
                        """,
                    )
                    table.on("images", lambda e: manage_images(e.args, on_changed=render_statuses))
                    table.on("edit", lambda e: open_status_form(e.args))
                    table.on("remove", lambda e: confirm_dialog("Delete status?", lambda: remove_status(e.args)))

            render_statuses()
        page_footer()
