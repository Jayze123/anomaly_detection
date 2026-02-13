from datetime import datetime

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from typing_extensions import Annotated

from app.api.deps import api_response, user_required
from app.db import crud, models
from app.db.models import User
from app.db.session import get_db
from app.services import inference, storage

router = APIRouter(prefix="/user", tags=["user"], dependencies=[Depends(user_required)])


@router.get("/products")
def list_products(user: User = Depends(user_required), db: Session = Depends(get_db)):
    _ = user
    items = db.scalars(select(models.Product).order_by(models.Product.name)).all()
    return api_response(
        True,
        "Products",
        [{"id": p.id, "name": p.name, "category_id": p.category_id, "category_name": p.category.name if p.category else None} for p in items],
    )


@router.post("/scans", status_code=201)
def create_scan(
    product_id: str = Form(...),
    notes: Annotated[str | None, StringConstraints(max_length=2000)] = Form(None),
    predicted_status: Annotated[str | None, StringConstraints(min_length=2, max_length=50)] = Form(None),
    confidence: float | None = Form(None, ge=0.0, le=1.0),
    is_defect: bool | None = Form(None),
    files: list[UploadFile] | None = File(None),
    user: User = Depends(user_required),
    db: Session = Depends(get_db),
):
    product = db.get(models.Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    image_paths: list[str] = []
    captured_frame = None
    if files:
        try:
            for f in files:
                path = storage.store_upload(f, f"scan_images/{user.id}")
                image_paths.append(path)
        except ValueError as exc:
            for path in image_paths:
                storage.delete_file(path)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        first_path = storage.absolute_path(image_paths[0])
        captured_frame = cv2.imread(str(first_path))

    if predicted_status is None or confidence is None or is_defect is None:
        if captured_frame is None:
            # fallback deterministic blank frame
            captured_frame = np.zeros((240, 320, 3), dtype=np.uint8)
        predicted_status, confidence, is_defect = inference.inference_service.predict(captured_frame, product_id)

    try:
        scan = crud.create_scan(
            db,
            factory_id=user.factory_id,
            user_id=user.id,
            product_id=product_id,
            predicted_status=predicted_status,
            confidence=confidence,
            is_defect=is_defect,
            image_paths=image_paths,
            notes=notes,
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        for path in image_paths:
            storage.delete_file(path)
        raise HTTPException(status_code=500, detail="Failed to save scan") from exc

    return api_response(True, "Scan created", {"id": scan.id, "predicted_status": scan.predicted_status, "confidence": scan.confidence})


@router.get("/scans")
def list_scans(
    product_id: str | None = Query(default=None),
    defect_only: bool = False,
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    user: User = Depends(user_required),
    db: Session = Depends(get_db),
):
    if start_at and end_at and start_at > end_at:
        raise HTTPException(status_code=400, detail="start_at must be before end_at")
    scans = crud.query_user_scans(
        db,
        user=user,
        product_id=product_id,
        defect_only=defect_only,
        start_at=start_at,
        end_at=end_at,
    )
    out = []
    for s in scans:
        images = db.scalars(select(models.ScanImage).where(models.ScanImage.scan_id == s.id)).all()
        out.append(
            {
                "id": s.id,
                "factory_id": s.factory_id,
                "product_id": s.product_id,
                "product_name": s.product.name if s.product else None,
                "predicted_status": s.predicted_status,
                "confidence": s.confidence,
                "is_defect": s.is_defect,
                "captured_at": s.captured_at.isoformat(),
                "notes": s.notes,
                "images": [img.image_path for img in images],
            }
        )
    return api_response(True, "Scans", out)


@router.get("/scans/{scan_id}")
def get_scan(scan_id: str, user: User = Depends(user_required), db: Session = Depends(get_db)):
    scan = db.get(models.Scan, scan_id)
    if not scan or scan.factory_id != user.factory_id:
        raise HTTPException(status_code=404, detail="Scan not found")
    images = db.scalars(select(models.ScanImage).where(models.ScanImage.scan_id == scan.id)).all()
    return api_response(
        True,
        "Scan detail",
        {
            "id": scan.id,
            "product_id": scan.product_id,
            "product_name": scan.product.name if scan.product else None,
            "predicted_status": scan.predicted_status,
            "confidence": scan.confidence,
            "is_defect": scan.is_defect,
            "captured_at": scan.captured_at.isoformat(),
            "notes": scan.notes,
            "images": [i.image_path for i in images],
        },
    )
