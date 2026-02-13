import os
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings

ALLOWED_MIME = {"image/jpeg": ".jpg", "image/png": ".png"}
ALLOWED_EXT = {".jpg", ".jpeg", ".png"}
MAX_SIZE_BYTES = 5 * 1024 * 1024


def _root() -> Path:
    settings = get_settings()
    root = Path(settings.storage_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def validate_upload(upload: UploadFile, data: bytes) -> str:
    if len(data) > MAX_SIZE_BYTES:
        raise ValueError("File exceeds max size of 5MB")

    ext = Path(upload.filename or "").suffix.lower()
    content_type = upload.content_type or ""
    if content_type in ALLOWED_MIME:
        return ALLOWED_MIME[content_type]
    if ext in ALLOWED_EXT:
        return ".jpg" if ext == ".jpeg" else ext
    raise ValueError("Invalid file type. Allowed: jpg, jpeg, png")


def store_upload(upload: UploadFile, folder: str) -> str:
    data = upload.file.read()
    ext = validate_upload(upload, data)
    file_name = f"{uuid.uuid4().hex}{ext}"
    rel_path = Path(folder) / file_name
    abs_path = _root() / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(data)
    return f"/{rel_path.as_posix()}"


def store_frame_bytes(data: bytes, folder: str, ext: str = ".jpg") -> str:
    file_name = f"{uuid.uuid4().hex}{ext}"
    rel_path = Path(folder) / file_name
    abs_path = _root() / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(data)
    return f"/{rel_path.as_posix()}"


def absolute_path(relative_path: str) -> Path:
    cleaned = relative_path[1:] if relative_path.startswith("/") else relative_path
    return _root() / cleaned


def delete_file(relative_path: str) -> None:
    path = absolute_path(relative_path)
    if path.exists() and path.is_file():
        os.remove(path)
