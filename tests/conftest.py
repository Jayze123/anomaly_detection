import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["STORAGE_ROOT"] = "/tmp/anomaly_test_data"
os.environ["JWT_SECRET"] = "test-secret"

from app.api import admin, auth, user
from app.api.deps import get_db
from app.db.base import Base
from app.db.seed import seed


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, class_=Session)
    Base.metadata.create_all(bind=engine)
    Path("/tmp/anomaly_test_data").mkdir(parents=True, exist_ok=True)

    with TestingSessionLocal() as db:
        seed(db)

    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(user.router)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c
