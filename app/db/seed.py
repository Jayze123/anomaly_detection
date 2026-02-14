from sqlalchemy import select

from app.db import models
from app.db.crud import create_user


def seed(db):
    factory = db.scalar(select(models.Factory).where(models.Factory.name == "Default Factory"))
    if not factory:
        factory = models.Factory(name="Default Factory", location="Plant A", category="Beverage")
        db.add(factory)
        db.flush()

    category = db.scalar(select(models.ProductCategory).where(models.ProductCategory.name == "Bottle"))
    if not category:
        category = models.ProductCategory(name="Bottle", description="Bottle products")
        db.add(category)
        db.flush()

    product = db.scalar(select(models.Product).where(models.Product.name == "Sample Bottle"))
    if not product:
        product = models.Product(name="Sample Bottle", category_id=category.id, description="Seed product")
        db.add(product)
        db.flush()

    for status_name in ["NORMAL", "SCRATCH", "DENT", "MISALIGNMENT"]:
        status = db.scalar(
            select(models.ProductStatus).where(
                models.ProductStatus.product_id == product.id,
                models.ProductStatus.status == status_name,
            )
        )
        if not status:
            db.add(models.ProductStatus(product_id=product.id, status=status_name, status_description=f"{status_name} state"))

    admin = db.scalar(select(models.User).where(models.User.email == "admin@local"))
    if not admin:
        create_user(
            db,
            factory_id=factory.id,
            email="admin@local",
            full_name="System Admin",
            password="admin123",
            role=models.RoleEnum.ADMIN.value,
            user_role=models.UserRoleEnum.ADMIN.value,
            is_active=True,
        )

    normal_user = db.scalar(select(models.User).where(models.User.email == "user@local"))
    if not normal_user:
        create_user(
            db,
            factory_id=factory.id,
            email="user@local",
            full_name="Line Operator",
            password="user123",
            role=models.RoleEnum.USER.value,
            user_role=models.UserRoleEnum.STAFF.value,
            is_active=True,
        )

    db.commit()
