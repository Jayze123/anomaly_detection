from __future__ import annotations

from nicegui import ui
from sqlalchemy import func, select

from app.db import crud
from app.db.models import Factory, Product, ProductCategory, ProductStatus, ProductStatusImage, Scan, ScanImage, User
from app.db.session import SessionLocal
from app.core.security import hash_password
from app.services.storage import delete_file, store_frame_bytes
from ui.components import confirm_dialog, navbar, require_ui_role


def register_admin_routes() -> None:
    @ui.page("/admin/dashboard")
    def admin_dashboard():
        user = require_ui_role("ADMIN")
        navbar(user, "Dashboard")
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

    @ui.page("/admin/factories")
    def admin_factories():
        user = require_ui_role("ADMIN")
        navbar(user, "Factories")

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
                    name = ui.input("Name", value=item.name if item else "")
                    location = ui.input("Location", value=item.location if item else "")
                    category = ui.input("Category", value=item.category if item else "")

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

                    with ui.row():
                        ui.button("Cancel", on_click=d.close)
                        ui.button("Save", on_click=save).props("color=primary")
                d.open()

            search.on("change", lambda _: render())
            render()

    @ui.page("/admin/users")
    def admin_users():
        user = require_ui_role("ADMIN")
        navbar(user, "Users")

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
                    target.password_hash = crud.hash_password(pwd)
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

    @ui.page("/admin/products")
    def admin_products():
        user = require_ui_role("ADMIN")
        navbar(user, "Products")

        with ui.column().classes("p-4 w-full"):
            search = ui.input("Search by name/category").props("outlined clearable")
            body = ui.column().classes("w-full")

            def open_form(product_id: str | None = None):
                p = None
                with SessionLocal() as db:
                    categories = db.scalars(select(ProductCategory).order_by(ProductCategory.name)).all()
                    if not categories:
                        categories = [ProductCategory(name="Default", description="Auto")]
                        db.add(categories[0])
                        db.commit()
                        db.refresh(categories[0])
                    if product_id:
                        p = db.get(Product, product_id)
                with ui.dialog() as d, ui.card().classes("w-[560px]"):
                    category_map = {c.name: c.id for c in categories}
                    category = ui.select(category_map, value=(p.category_id if p else next(iter(category_map.values()))), label="Category")
                    name = ui.input("Name", value=p.name if p else "")
                    description = ui.textarea("Description", value=p.description if p else "")

                    def save():
                        with SessionLocal() as db:
                            target = db.get(Product, product_id) if product_id else Product()
                            target.category_id = category.value
                            target.name = name.value
                            target.description = description.value
                            db.add(target)
                            db.commit()
                        d.close()
                        render()
                        ui.notify("Product saved", color="positive")

                    with ui.row():
                        ui.button("Cancel", on_click=d.close)
                        ui.button("Save", on_click=save).props("color=primary")
                d.open()

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
                    ui.button("Add Product", on_click=lambda: open_form()).props("color=primary")
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

    @ui.page("/admin/products/{product_id}")
    def admin_product_detail(product_id: str):
        user = require_ui_role("ADMIN")
        navbar(user, "Product Detail")

        with SessionLocal() as db:
            product = db.get(Product, product_id)
            if not product:
                ui.notify("Product not found", color="negative")
                ui.navigate.to("/admin/products")
                return

        with ui.column().classes("p-4 w-full"):
            ui.label(product.name).classes("text-2xl font-bold")
            ui.label(f"Category: {product.category.name if product.category else ''}")
            ui.label(product.description or "")

            status_list = ui.column().classes("w-full")

            def manage_images(status_id: str):
                with SessionLocal() as db:
                    imgs = db.scalars(
                        select(ProductStatusImage)
                        .where(ProductStatusImage.product_status_id == status_id)
                        .order_by(ProductStatusImage.sort_order)
                    ).all()

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

                    ui.button("Close", on_click=drawer.hide).props("flat")
                    render_grid()

            def open_status_form(status_id: str | None = None):
                s = None
                if status_id:
                    with SessionLocal() as db:
                        s = db.get(ProductStatus, status_id)
                with ui.dialog() as d, ui.card().classes("w-[500px]"):
                    status = ui.input("Status", value=s.status if s else "")
                    desc = ui.textarea("Description", value=s.status_description if s else "")

                    def save():
                        with SessionLocal() as db:
                            target = db.get(ProductStatus, status_id) if status_id else ProductStatus(product_id=product_id)
                            target.status = status.value
                            target.status_description = desc.value
                            db.add(target)
                            db.commit()
                        d.close()
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

            def render_statuses():
                status_list.clear()
                with SessionLocal() as db:
                    statuses = db.scalars(select(ProductStatus).where(ProductStatus.product_id == product_id)).all()
                with status_list:
                    ui.button("Add Status", on_click=lambda: open_status_form()).props("color=primary")
                    rows = [{"id": s.id, "status": s.status, "description": s.status_description or ""} for s in statuses]
                    table = ui.table(
                        columns=[
                            {"name": "status", "label": "Status", "field": "status", "sortable": True},
                            {"name": "description", "label": "Description", "field": "description"},
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
                    table.on("images", lambda e: manage_images(e.args))
                    table.on("edit", lambda e: open_status_form(e.args))
                    table.on("remove", lambda e: confirm_dialog("Delete status?", lambda: remove_status(e.args)))

            render_statuses()
