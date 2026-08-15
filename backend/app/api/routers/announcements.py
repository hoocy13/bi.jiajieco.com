from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.announcement import Announcement
from app.models.user import User
from app.schemas.announcement import AnnouncementPayload, AnnouncementPublic
from app.schemas.common import ApiResponse, ok


router = APIRouter(prefix="/announcements", tags=["announcements"])


@router.get("", response_model=ApiResponse[list[AnnouncementPublic]])
def list_announcements(
    status_filter: str = Query("active", alias="status", pattern="^(active|inactive|all)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    query = db.query(Announcement)
    if status_filter == "active":
        query = query.filter(Announcement.is_active.is_(True))
    elif status_filter == "inactive":
        query = query.filter(Announcement.is_active.is_(False))
    items = query.order_by(Announcement.is_active.desc(), Announcement.updated_at.desc(), Announcement.id.desc()).all()
    return ok([AnnouncementPublic.model_validate(item).model_dump() for item in items])


@router.post("", response_model=ApiResponse[AnnouncementPublic])
def create_announcement(payload: AnnouncementPayload, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = Announcement(title=payload.title.strip(), content=payload.content.strip(), is_active=payload.is_active, created_by=current_user.id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return ok(AnnouncementPublic.model_validate(item).model_dump())


@router.put("/{announcement_id}", response_model=ApiResponse[AnnouncementPublic])
def update_announcement(announcement_id: int, payload: AnnouncementPayload, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = db.get(Announcement, announcement_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "公告不存在", "data": None})
    item.title = payload.title.strip()
    item.content = payload.content.strip()
    item.is_active = payload.is_active
    db.commit()
    db.refresh(item)
    return ok(AnnouncementPublic.model_validate(item).model_dump())


@router.delete("/{announcement_id}")
def delete_announcement(announcement_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    item = db.get(Announcement, announcement_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "公告不存在", "data": None})
    db.delete(item)
    db.commit()
    return ok({"id": announcement_id})
