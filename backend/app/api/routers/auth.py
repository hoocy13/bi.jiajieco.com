from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.common import ApiResponse, ok
from app.schemas.user import UserPublic


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=ApiResponse[TokenResponse])
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": 401, "message": "账号或密码错误，请重新输入", "data": None},
        )

    token = create_access_token(subject=user.username)
    return ok(TokenResponse(access_token=token).model_dump())


@router.get("/me", response_model=ApiResponse[UserPublic])
def me(current_user: User = Depends(get_current_user)) -> dict:
    return ok(UserPublic.model_validate(current_user).model_dump())
