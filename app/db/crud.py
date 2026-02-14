from datetime import datetime
from typing import Iterable

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.db import models


class ValidationError(ValueError):
    pass


def authenticate_user(db: Session, email: str, password: str) -> models.User | None:
    user = db.scalar(select(models.User).where(models.User.email == email))
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def create_user(
    db: Session,
    *,
    factory_id: str,
    email: str,
    full_name: str,
    password: str,
    role: str,
    user_role: str | None = None,
    is_active: bool = True,
) -> models.User:
    normalized_user_role = (user_role or "").strip().lower()
    if normalized_user_role not in {models.UserRoleEnum.ADMIN.value, models.UserRoleEnum.STAFF.value}:
        normalized_user_role = models.UserRoleEnum.ADMIN.value if role == models.RoleEnum.ADMIN.value else models.UserRoleEnum.STAFF.value
    user = models.User(
        factory_id=factory_id,
        email=email.lower().strip(),
        full_name=full_name,
        password_hash=hash_password(password),
        role=role,
        user_role=normalized_user_role,
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    return user


def reset_password(db: Session, user: models.User, new_password: str) -> None:
    user.password_hash = hash_password(new_password)
    db.add(user)


def list_products(db: Session, search: str | None, skip: int, limit: int) -> tuple[list[models.Product], int]:
    base: Select[tuple[models.Product]] = select(models.Product)
    if search:
        like = f"%{search.strip()}%"
        base = base.join(models.ProductCategory, models.Product.category_id == models.ProductCategory.id).where(
            or_(models.Product.name.ilike(like), models.ProductCategory.name.ilike(like))
        )

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = db.scalars(base.order_by(models.Product.created_at.desc()).offset(skip).limit(limit)).all()
    return items, total


def ensure_status_image_capacity(db: Session, status_id: str) -> int:
    count = db.scalar(select(func.count()).select_from(models.ProductStatusImage).where(models.ProductStatusImage.product_status_id == status_id)) or 0
    if count >= 4:
        raise ValidationError("Maximum of 4 images allowed per product status")
    return count


def next_sort_order(db: Session, status_id: str) -> int:
    used = db.scalars(
        select(models.ProductStatusImage.sort_order)
        .where(models.ProductStatusImage.product_status_id == status_id)
        .order_by(models.ProductStatusImage.sort_order)
    ).all()
    for candidate in [1, 2, 3, 4]:
        if candidate not in used:
            return candidate
    raise ValidationError("Maximum of 4 images allowed per product status")


def reorder_status_images(db: Session, status_id: str, ordered_ids: Iterable[str]) -> list[models.ProductStatusImage]:
    images = db.scalars(
        select(models.ProductStatusImage).where(models.ProductStatusImage.product_status_id == status_id)
    ).all()
    image_map = {img.id: img for img in images}
    valid_ids = [img_id for img_id in ordered_ids if img_id in image_map]
    remaining = [img.id for img in sorted(images, key=lambda it: it.sort_order) if img.id not in valid_ids]
    final = valid_ids + remaining
    for idx, image_id in enumerate(final, start=1):
        image_map[image_id].sort_order = idx
        db.add(image_map[image_id])
    return sorted(images, key=lambda it: it.sort_order)


def create_scan(
    db: Session,
    *,
    factory_id: str,
    user_id: str,
    product_id: str,
    predicted_status: str,
    confidence: float,
    is_defect: bool,
    image_paths: list[str],
    notes: str | None = None,
    captured_at: datetime | None = None,
) -> models.Scan:
    scan = models.Scan(
        factory_id=factory_id,
        user_id=user_id,
        product_id=product_id,
        predicted_status=predicted_status,
        confidence=confidence,
        is_defect=is_defect,
        notes=notes,
        captured_at=captured_at or datetime.utcnow(),
    )
    db.add(scan)
    db.flush()
    for path in image_paths:
        db.add(models.ScanImage(scan_id=scan.id, image_path=path))
    db.flush()
    return scan


def query_user_scans(
    db: Session,
    *,
    user: models.User,
    product_id: str | None,
    defect_only: bool,
    start_at: datetime | None,
    end_at: datetime | None,
) -> list[models.Scan]:
    where = [models.Scan.factory_id == user.factory_id]
    if product_id:
        where.append(models.Scan.product_id == product_id)
    if defect_only:
        where.append(models.Scan.is_defect.is_(True))
    if start_at:
        where.append(models.Scan.captured_at >= start_at)
    if end_at:
        where.append(models.Scan.captured_at <= end_at)

    return db.scalars(select(models.Scan).where(and_(*where)).order_by(models.Scan.captured_at.desc())).all()
