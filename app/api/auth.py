from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.api.deps import api_response, get_current_user
from app.core.security import create_access_token
from app.db.crud import authenticate_user
from app.db.models import User, UserRoleEnum
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, payload.email, payload.password)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(subject=user.id, role=user.role)
    effective_user_role = user.user_role or (UserRoleEnum.ADMIN.value if user.role == "ADMIN" else UserRoleEnum.STAFF.value)
    return api_response(
        True,
        "Login successful",
        {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": datetime.now(timezone.utc).isoformat(),
            "user": {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
                "user_role": effective_user_role,
                "factory_id": user.factory_id,
            },
        },
    )


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    effective_user_role = user.user_role or (UserRoleEnum.ADMIN.value if user.role == "ADMIN" else UserRoleEnum.STAFF.value)
    return api_response(
        True,
        "Current user",
        {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "user_role": effective_user_role,
            "factory_id": user.factory_id,
            "is_active": user.is_active,
        },
    )
