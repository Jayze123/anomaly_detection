from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from nicegui import ui
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import admin, auth, user
from app.api.deps import api_response
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.base import Base
from app.db.seed import seed
from app.db.session import SessionLocal, engine
from ui.app_ui import register_ui

configure_logging()
settings = get_settings()

api_app = FastAPI(title="Anomaly Inspection", version="0.1.0")
api_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_app.include_router(auth.router)
api_app.include_router(admin.router)
api_app.include_router(user.router)

Path(settings.storage_root).mkdir(parents=True, exist_ok=True)
api_app.mount("/data", StaticFiles(directory=settings.storage_root), name="data")


@api_app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content=api_response(False, str(exc.detail), None))


@api_app.exception_handler(RequestValidationError)
async def validation_exception_handler(_, exc: RequestValidationError):
    return JSONResponse(status_code=422, content=api_response(False, "Validation failed", exc.errors()))


@api_app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed(db)


register_ui(api_app)


if __name__ in {"__main__", "app.main"}:
    ui.run_with(api_app, storage_secret=settings.jwt_secret, title="Anomaly Inspection", reload=False, port=8080)
