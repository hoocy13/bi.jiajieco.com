from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import get_password_hash
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import ApiResponse, ok
from app.schemas.user import UserCreate, UserPublic, UserStatusUpdate


router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=ApiResponse[list[UserPublic]])
def list_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    users = db.query(User).order_by(User.id.asc()).all()
    return ok([UserPublic.model_validate(user).model_dump() for user in users])


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
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return ok(UserPublic.model_validate(user).model_dump())


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
