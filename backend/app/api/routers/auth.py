from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime
import re
import uuid

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token, get_password_hash, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.common import ApiResponse, ok
from app.schemas.user import RolePublic, UserPublic


router = APIRouter(prefix="/auth", tags=["auth"])


def serialize_user(user: User) -> dict:
    role = RolePublic.model_validate(user.role).model_dump() if user.role else None
    return UserPublic(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        phone=user.phone,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        role=role,
        permissions=[permission.code for permission in user.role.permissions] if user.role and user.role.is_active else [],
    ).model_dump()


@router.post("/register", response_model=ApiResponse[UserPublic])
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict:
    email = payload.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=400, detail={"code": 400, "message": "请输入有效的邮箱地址", "data": None})
    if db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(status_code=409, detail={"code": 409, "message": "该邮箱已注册", "data": None})
    from app.models.user import Role

    pending_role = db.query(Role).filter(Role.code == "pending", Role.is_active.is_(True)).first()
    if pending_role is None:
        raise HTTPException(status_code=503, detail={"code": 503, "message": "注册服务尚未初始化", "data": None})
    user = User(
        username=f"user_{uuid.uuid4().hex}",
        email=email,
        display_name=payload.display_name.strip(),
        phone=payload.phone.strip() if payload.phone else None,
        hashed_password=get_password_hash(payload.password),
        is_active=True,
        role=pending_role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok(serialize_user(user))


@router.post("/login", response_model=ApiResponse[TokenResponse])
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    account = payload.username.strip().lower()
    user = db.query(User).filter(or_(User.username == payload.username.strip(), User.email == account)).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": 401, "message": "账号或密码错误，请重新输入", "data": None},
        )

    if not user.is_active:
        raise HTTPException(status_code=403, detail={"code": 403, "message": "账号已停用，请联系管理员", "data": None})
    user.last_login_at = datetime.utcnow()
    db.add(user)
    db.commit()
    token = create_access_token(subject=user.username)
    return ok(TokenResponse(access_token=token).model_dump())


@router.get("/me", response_model=ApiResponse[UserPublic])
def me(current_user: User = Depends(get_current_user)) -> dict:
    return ok(serialize_user(current_user))
