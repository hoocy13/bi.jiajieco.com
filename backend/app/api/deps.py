from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User


oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_PREFIX}/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    username = decode_access_token(token)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": 401, "message": "Invalid token", "data": None},
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": 401, "message": "Inactive or missing user", "data": None},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def permission_codes(user: User) -> set[str]:
    if user.role is None or not user.role.is_active:
        return set()
    return {permission.code for permission in user.role.permissions}


def require_permission(code: str) -> Callable[..., User]:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if code not in permission_codes(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": 403, "message": "当前账号没有访问该功能的权限", "data": None},
            )
        return user

    return dependency
