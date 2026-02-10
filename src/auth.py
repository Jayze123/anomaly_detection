from __future__ import annotations

import os

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_session_secret() -> str:
    return os.environ.get("SESSION_SECRET", "change-me-in-production")
