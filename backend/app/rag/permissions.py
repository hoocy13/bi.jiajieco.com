from fastapi import Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.config import settings
from app.models.user import User


def rag_role_for_user(user: User) -> str:
    admin_usernames = {
        username.strip()
        for username in settings.RAG_ADMIN_USERNAMES
        if username.strip()
    }
    return "admin" if user.username in admin_usernames else "analyst"


def require_rag_admin(user: User = Depends(get_current_user)) -> User:
    if rag_role_for_user(user) != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": 403, "message": "RAG admin permission required", "data": None},
        )
    return user
