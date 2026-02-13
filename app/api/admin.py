import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from typing_extensions import Annotated

from app.api.deps import admin_required, api_response
from app.db import crud, models
from app.db.session import get_db
from app.services import storage

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(admin_required)])


class FactoryIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: Annotated[str, StringConstraints(min_length=2, max_length=255)]
    location: Annotated[str, StringConstraints(min_length=2, max_length=255)]
    category: Annotated[str, StringConstraints(min_length=2, max_length=255)]


class UserIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    factory_id: str
    email: EmailStr
    full_name: Annotated[str, StringConstraints(min_length=2, max_length=255)]
    role: str = Field(pattern="^(ADMIN|USER)$")
    is_active: bool = True
    password: Annotated[str, StringConstraints(min_length=8, max_length=128)] | None = None


class ProductIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    category_id: str
    name: Annotated[str, StringConstraints(min_length=2, max_length=255)]
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None


class StatusIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    status: Annotated[str, StringConstraints(min_length=2, max_length=50)]
    status_description: Annotated[str, StringConstraints(max_length=2000)] | None = None


class NormalReferenceIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    status_description: Annotated[str, StringConstraints(min_length=2, max_length=2000)]


def _commit_or_raise(db: Session, integrity_message: str = "Database constraint violated") -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=integrity_message) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Database operation failed") from exc


def _ensure_normal_status(db: Session, product_id: str) -> models.ProductStatus:
    product = db.get(models.Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    normal = db.scalar(
        select(models.ProductStatus).where(
            models.ProductStatus.product_id == product_id,
            func.upper(models.ProductStatus.status) == "NORMAL",
        )
    )
    if normal:
        return normal

    normal = models.ProductStatus(
        product_id=product_id,
        status="NORMAL",
        status_description="Reference normal product condition",
    )
    db.add(normal)
    _commit_or_raise(db, "Unable to create normal reference status")
    db.refresh(normal)
    return normal


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    today = datetime.utcnow().date()
    total_products = db.scalar(select(func.count()).select_from(models.Product)) or 0
    scans_today = db.scalar(select(func.count()).select_from(models.Scan).where(func.date(models.Scan.captured_at) == today)) or 0
    defects_today = db.scalar(
        select(func.count()).select_from(models.Scan).where(func.date(models.Scan.captured_at) == today, models.Scan.is_defect.is_(True))
    ) or 0
    active_users = db.scalar(select(func.count()).select_from(models.User).where(models.User.is_active.is_(True))) or 0
    defect_rate = (defects_today / scans_today) if scans_today else 0.0

    rows = db.execute(
        select(models.Scan, models.Product.name, models.User.full_name, models.Factory.name)
        .join(models.Product, models.Product.id == models.Scan.product_id)
        .join(models.User, models.User.id == models.Scan.user_id)
        .join(models.Factory, models.Factory.id == models.Scan.factory_id)
        .order_by(models.Scan.captured_at.desc())
        .limit(10)
    ).all()

    scans = [
        {
            "id": s.id,
            "time": s.captured_at.isoformat(),
            "product": product_name,
            "status": s.predicted_status,
            "confidence": s.confidence,
            "user": user_name,
            "factory": factory_name,
        }
        for s, product_name, user_name, factory_name in rows
    ]

    return api_response(
        True,
        "Dashboard metrics",
        {
            "total_products": total_products,
            "scans_today": scans_today,
            "defect_rate_today": defect_rate,
            "active_users": active_users,
            "last_scans": scans,
        },
    )


@router.get("/factories")
def list_factories(db: Session = Depends(get_db)):
    items = db.scalars(select(models.Factory).order_by(models.Factory.name)).all()
    return api_response(True, "Factories", [
        {"id": i.id, "name": i.name, "location": i.location, "category": i.category} for i in items
    ])


@router.post("/factories", status_code=201)
def create_factory(payload: FactoryIn, db: Session = Depends(get_db)):
    item = models.Factory(**payload.model_dump())
    db.add(item)
    _commit_or_raise(db, "Factory name already exists")
    db.refresh(item)
    return api_response(True, "Factory created", {"id": item.id})


@router.put("/factories/{factory_id}")
def update_factory(factory_id: str, payload: FactoryIn, db: Session = Depends(get_db)):
    item = db.get(models.Factory, factory_id)
    if not item:
        raise HTTPException(status_code=404, detail="Factory not found")
    for k, v in payload.model_dump().items():
        setattr(item, k, v)
    db.add(item)
    _commit_or_raise(db, "Factory name already exists")
    return api_response(True, "Factory updated", {"id": item.id})


@router.delete("/factories/{factory_id}")
def delete_factory(factory_id: str, db: Session = Depends(get_db)):
    item = db.get(models.Factory, factory_id)
    if not item:
        raise HTTPException(status_code=404, detail="Factory not found")
    db.delete(item)
    _commit_or_raise(db, "Factory cannot be deleted because it is in use")
    return api_response(True, "Factory deleted", None)


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    rows = db.execute(select(models.User, models.Factory.name).join(models.Factory, models.Factory.id == models.User.factory_id)).all()
    return api_response(
        True,
        "Users",
        [
            {
                "id": u.id,
                "email": u.email,
                "full_name": u.full_name,
                "role": u.role,
                "is_active": u.is_active,
                "factory_id": u.factory_id,
                "factory_name": factory_name,
            }
            for u, factory_name in rows
        ],
    )


@router.post("/users", status_code=201)
def create_user(payload: UserIn, db: Session = Depends(get_db)):
    pwd = payload.password or secrets.token_urlsafe(10)
    user = crud.create_user(
        db,
        factory_id=payload.factory_id,
        email=payload.email,
        full_name=payload.full_name,
        password=pwd,
        role=payload.role,
        is_active=payload.is_active,
    )
    _commit_or_raise(db, "Email already exists or factory is invalid")
    return api_response(True, "User created", {"id": user.id, "generated_password": pwd if not payload.password else None})


@router.put("/users/{user_id}")
def update_user(user_id: str, payload: UserIn, db: Session = Depends(get_db)):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    for field in ["factory_id", "email", "full_name", "role", "is_active"]:
        setattr(user, field, getattr(payload, field))
    if payload.password:
        crud.reset_password(db, user, payload.password)
    db.add(user)
    _commit_or_raise(db, "User update violated constraints")
    return api_response(True, "User updated", {"id": user.id})


@router.post("/users/{user_id}/reset-password")
def reset_user_password(user_id: str, db: Session = Depends(get_db)):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    temp_password = secrets.token_urlsafe(8)
    crud.reset_password(db, user, temp_password)
    _commit_or_raise(db, "Password reset failed")
    return api_response(True, "Password reset", {"temporary_password": temp_password})


@router.delete("/users/{user_id}")
def delete_user(user_id: str, db: Session = Depends(get_db)):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    _commit_or_raise(db, "User cannot be deleted because it is in use")
    return api_response(True, "User deleted", None)


@router.get("/products")
def list_products(
    search: Annotated[str | None, Query(max_length=255)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    db: Session = Depends(get_db),
):
    items, total = crud.list_products(db, search, skip=(page - 1) * page_size, limit=page_size)
    output = []
    for i in items:
        output.append(
            {
                "id": i.id,
                "name": i.name,
                "description": i.description,
                "category_id": i.category_id,
                "category_name": i.category.name if i.category else None,
            }
        )
    return api_response(True, "Products", {"items": output, "total": total, "page": page, "page_size": page_size})


@router.post("/products", status_code=201)
def create_product(payload: ProductIn, db: Session = Depends(get_db)):
    item = models.Product(**payload.model_dump())
    db.add(item)
    _commit_or_raise(db, "Invalid category or duplicate product data")
    db.refresh(item)
    return api_response(True, "Product created", {"id": item.id})


@router.put("/products/{product_id}")
def update_product(product_id: str, payload: ProductIn, db: Session = Depends(get_db)):
    item = db.get(models.Product, product_id)
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    for k, v in payload.model_dump().items():
        setattr(item, k, v)
    db.add(item)
    _commit_or_raise(db, "Invalid product update")
    return api_response(True, "Product updated", {"id": item.id})


@router.delete("/products/{product_id}")
def delete_product(product_id: str, db: Session = Depends(get_db)):
    item = db.get(models.Product, product_id)
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    db.delete(item)
    _commit_or_raise(db, "Product cannot be deleted because it is in use")
    return api_response(True, "Product deleted", None)


@router.get("/products/{product_id}")
def get_product(product_id: str, db: Session = Depends(get_db)):
    item = db.get(models.Product, product_id)
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")

    statuses = db.scalars(select(models.ProductStatus).where(models.ProductStatus.product_id == product_id)).all()
    return api_response(
        True,
        "Product detail",
        {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "category_id": item.category_id,
            "category_name": item.category.name if item.category else None,
            "statuses": [
                {
                    "id": s.id,
                    "status": s.status,
                    "status_description": s.status_description,
                }
                for s in statuses
            ],
        },
    )


@router.get("/products/{product_id}/statuses")
def list_statuses(product_id: str, db: Session = Depends(get_db)):
    statuses = db.scalars(
        select(models.ProductStatus).where(models.ProductStatus.product_id == product_id).order_by(models.ProductStatus.created_at.asc())
    ).all()
    data = []
    for s in statuses:
        images = db.scalars(
            select(models.ProductStatusImage)
            .where(models.ProductStatusImage.product_status_id == s.id)
            .order_by(models.ProductStatusImage.sort_order)
        ).all()
        data.append(
            {
                "id": s.id,
                "status": s.status,
                "status_description": s.status_description,
                "images": [
                    {"id": img.id, "image_path": img.image_path, "sort_order": img.sort_order}
                    for img in images
                ],
            }
        )
    return api_response(True, "Statuses", data)


@router.post("/products/{product_id}/statuses", status_code=201)
def create_status(product_id: str, payload: StatusIn, db: Session = Depends(get_db)):
    product = db.get(models.Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    item = models.ProductStatus(product_id=product_id, **payload.model_dump())
    db.add(item)
    _commit_or_raise(db, "Status already exists for this product")
    db.refresh(item)
    return api_response(True, "Status created", {"id": item.id})


@router.put("/statuses/{status_id}")
def update_status(status_id: str, payload: StatusIn, db: Session = Depends(get_db)):
    item = db.get(models.ProductStatus, status_id)
    if not item:
        raise HTTPException(status_code=404, detail="Status not found")
    item.status = payload.status
    item.status_description = payload.status_description
    db.add(item)
    _commit_or_raise(db, "Status update violated constraints")
    return api_response(True, "Status updated", {"id": item.id})


@router.delete("/statuses/{status_id}")
def delete_status(status_id: str, db: Session = Depends(get_db)):
    item = db.get(models.ProductStatus, status_id)
    if not item:
        raise HTTPException(status_code=404, detail="Status not found")
    db.delete(item)
    _commit_or_raise(db, "Status delete failed")
    return api_response(True, "Status deleted", None)


@router.post("/statuses/{status_id}/images", status_code=201)
def upload_status_image(status_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    status_obj = db.get(models.ProductStatus, status_id)
    if not status_obj:
        raise HTTPException(status_code=404, detail="Status not found")

    try:
        crud.ensure_status_image_capacity(db, status_id)
        path = storage.store_upload(file, f"status_images/{status_id}")
        order = crud.next_sort_order(db, status_id)
        item = models.ProductStatusImage(product_status_id=status_id, image_path=path, sort_order=order)
        db.add(item)
        _commit_or_raise(db, "Unable to save status image")
    except crud.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return api_response(True, "Status image uploaded", {"id": item.id, "image_path": item.image_path, "sort_order": item.sort_order})


@router.post("/statuses/{status_id}/images/reorder")
def reorder_images(status_id: str, image_ids: list[str], db: Session = Depends(get_db)):
    status_obj = db.get(models.ProductStatus, status_id)
    if not status_obj:
        raise HTTPException(status_code=404, detail="Status not found")
    images = crud.reorder_status_images(db, status_id, image_ids)
    _commit_or_raise(db, "Unable to reorder images")
    return api_response(True, "Images reordered", [{"id": i.id, "sort_order": i.sort_order} for i in images])


@router.delete("/status-images/{image_id}")
def delete_status_image(image_id: str, db: Session = Depends(get_db)):
    item = db.get(models.ProductStatusImage, image_id)
    if not item:
        raise HTTPException(status_code=404, detail="Image not found")
    status_id = item.product_status_id
    path = item.image_path
    db.delete(item)
    db.flush()

    images = db.scalars(
        select(models.ProductStatusImage)
        .where(models.ProductStatusImage.product_status_id == status_id)
        .order_by(models.ProductStatusImage.sort_order)
    ).all()
    for idx, image in enumerate(images, start=1):
        image.sort_order = idx
        db.add(image)

    _commit_or_raise(db, "Unable to delete status image")
    storage.delete_file(path)
    return api_response(True, "Status image deleted", None)


@router.post("/scan-images/upload")
def upload_scan_image(file: UploadFile = File(...)):
    try:
        path = storage.store_upload(file, "scan_images/manual")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return api_response(True, "Scan image uploaded", {"image_path": path})


@router.get("/products/{product_id}/normal-reference")
def get_normal_reference(product_id: str, db: Session = Depends(get_db)):
    normal = _ensure_normal_status(db, product_id)
    images = db.scalars(
        select(models.ProductStatusImage)
        .where(models.ProductStatusImage.product_status_id == normal.id)
        .order_by(models.ProductStatusImage.sort_order.asc())
    ).all()
    return api_response(
        True,
        "Normal reference",
        {
            "status_id": normal.id,
            "status": normal.status,
            "status_description": normal.status_description,
            "images": [{"id": i.id, "image_path": i.image_path, "sort_order": i.sort_order} for i in images],
        },
    )


@router.put("/products/{product_id}/normal-reference")
def update_normal_reference(product_id: str, payload: NormalReferenceIn, db: Session = Depends(get_db)):
    normal = _ensure_normal_status(db, product_id)
    normal.status_description = payload.status_description
    db.add(normal)
    _commit_or_raise(db, "Unable to update normal reference")
    return api_response(True, "Normal reference updated", {"status_id": normal.id})


@router.post("/products/{product_id}/normal-reference/images", status_code=201)
def upload_normal_reference_image(product_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    normal = _ensure_normal_status(db, product_id)
    try:
        crud.ensure_status_image_capacity(db, normal.id)
        path = storage.store_upload(file, f"status_images/{normal.id}")
        order = crud.next_sort_order(db, normal.id)
        item = models.ProductStatusImage(product_status_id=normal.id, image_path=path, sort_order=order)
        db.add(item)
        _commit_or_raise(db, "Unable to save normal reference image")
    except crud.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return api_response(
        True,
        "Normal reference image uploaded",
        {"id": item.id, "image_path": item.image_path, "sort_order": item.sort_order},
    )


@router.delete("/products/{product_id}/normal-reference/images/{image_id}")
def delete_normal_reference_image(product_id: str, image_id: str, db: Session = Depends(get_db)):
    normal = _ensure_normal_status(db, product_id)
    item = db.get(models.ProductStatusImage, image_id)
    if not item or item.product_status_id != normal.id:
        raise HTTPException(status_code=404, detail="Normal reference image not found")

    path = item.image_path
    db.delete(item)
    db.flush()

    images = db.scalars(
        select(models.ProductStatusImage)
        .where(models.ProductStatusImage.product_status_id == normal.id)
        .order_by(models.ProductStatusImage.sort_order.asc())
    ).all()
    for idx, image in enumerate(images, start=1):
        image.sort_order = idx
        db.add(image)

    _commit_or_raise(db, "Unable to delete normal reference image")
    storage.delete_file(path)
    return api_response(True, "Normal reference image deleted", None)


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    categories = db.scalars(select(models.ProductCategory).order_by(models.ProductCategory.name)).all()
    return api_response(True, "Categories", [{"id": c.id, "name": c.name, "description": c.description} for c in categories])
