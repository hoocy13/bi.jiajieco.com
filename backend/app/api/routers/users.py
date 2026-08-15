import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import get_password_hash
from app.db.session import get_db
from app.models.user import Role, User
from app.schemas.common import ApiResponse, ok
from app.schemas.user import UserCreate, UserProfileUpdate, UserPublic, UserRoleUpdate, UserStatusUpdate
from app.api.routers.auth import serialize_user


router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    role_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(User)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        query = query.filter(
            User.display_name.ilike(pattern) | User.email.ilike(pattern) | User.phone.ilike(pattern) | User.username.ilike(pattern)
        )
    if role_id is not None:
        query = query.filter(User.role_id == role_id)
    total = query.count()
    users = query.order_by(User.role_id.asc(), User.created_at.desc(), User.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return ok({"items": [serialize_user(user) for user in users], "total": total, "page": page, "page_size": page_size})


@router.post("", response_model=ApiResponse[UserPublic])
def create_user(
    payload: UserCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    username = payload.username.strip()
    if len(username) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": 400, "message": "Username must be at least 3 characters", "data": None},
        )
    if len(payload.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": 400, "message": "Password must be at least 8 characters", "data": None},
        )
    existing_user = db.query(User).filter(User.username == username).first()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": 409, "message": "Username already exists", "data": None},
        )

    user = User(
        username=username,
        hashed_password=get_password_hash(payload.password),
        is_active=True,
        role=db.query(Role).filter(Role.code == "pending").first(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok(UserPublic.model_validate(user).model_dump())


@router.put("/{user_id}/role", response_model=ApiResponse[UserPublic])
def update_user_role(
    user_id: int,
    payload: UserRoleUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    role = db.get(Role, payload.role_id)
    if user is None:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "用户不存在", "data": None})
    if role is None or not role.is_active:
        raise HTTPException(status_code=400, detail={"code": 400, "message": "角色不存在或已停用", "data": None})
    if user.id == current_user.id and user.role_id != role.id:
        raise HTTPException(status_code=400, detail={"code": 400, "message": "不能修改自己的角色", "data": None})
    user.role = role
    db.commit()
    db.refresh(user)
    return ok(serialize_user(user))


@router.put("/{user_id}/profile", response_model=ApiResponse[UserPublic])
def update_user_profile(
    user_id: int,
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "用户不存在", "data": None})

    email = payload.email.strip().lower() if payload.email else None
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=400, detail={"code": 400, "message": "请输入有效的邮箱地址", "data": None})
    if email and db.query(User).filter(User.email == email, User.id != user.id).first():
        raise HTTPException(status_code=409, detail={"code": 409, "message": "该邮箱已被其他账号使用", "data": None})

    phone = payload.phone.strip() if payload.phone else None
    if phone and not re.fullmatch(r"[0-9+()\-\s]{6,32}", phone):
        raise HTTPException(status_code=400, detail={"code": 400, "message": "请输入有效的手机号", "data": None})

    user.display_name = payload.display_name.strip()
    user.email = email
    user.phone = phone
    db.commit()
    db.refresh(user)
    return ok(serialize_user(user))


@router.patch("/{user_id}/status", response_model=ApiResponse[UserPublic])
def update_user_status(
    user_id: int,
    payload: UserStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": 404, "message": "User not found", "data": None},
        )
    if user.id == current_user.id and not payload.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": 400, "message": "Cannot disable current user", "data": None},
        )

    user.is_active = payload.is_active
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok(UserPublic.model_validate(user).model_dump())
