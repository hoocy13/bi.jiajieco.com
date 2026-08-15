from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import Permission, Role, User
from app.schemas.common import ApiResponse, ok
from app.schemas.user import PermissionPublic, RoleCreate, RolePublic, RoleUpdate


router = APIRouter(prefix="/roles", tags=["roles"])


def serialize_role(role: Role, user_count: int = 0) -> dict:
    return RolePublic(
        id=role.id,
        role_no=role.role_no,
        code=role.code,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        is_active=role.is_active,
        permissions=[PermissionPublic.model_validate(item) for item in role.permissions],
        user_count=user_count,
    ).model_dump()


def permissions_for_codes(db: Session, codes: list[str]) -> list[Permission]:
    unique_codes = set(codes)
    permissions = db.query(Permission).filter(Permission.code.in_(unique_codes)).all() if unique_codes else []
    if len(permissions) != len(unique_codes):
        raise HTTPException(status_code=400, detail={"code": 400, "message": "包含无效权限", "data": None})
    return permissions


@router.get("")
def list_roles(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    counts = dict(db.query(User.role_id, func.count(User.id)).group_by(User.role_id).all())
    roles = db.query(Role).order_by(Role.is_active.desc(), Role.id.asc()).all()
    return ok([serialize_role(role, counts.get(role.id, 0)) for role in roles])


@router.get("/permissions", response_model=ApiResponse[list[PermissionPublic]])
def list_permissions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    items = db.query(Permission).order_by(Permission.sort_order.asc()).all()
    return ok([PermissionPublic.model_validate(item).model_dump() for item in items])


@router.post("")
def create_role(payload: RoleCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if db.query(Role).filter(Role.name == payload.name.strip()).first():
        raise HTTPException(status_code=409, detail={"code": 409, "message": "角色名称已存在", "data": None})
    used_numbers = {int(value) for (value,) in db.query(Role.role_no).filter(Role.role_no.is_not(None)).all() if value and value.isdigit()}
    next_number = next((number for number in range(1, 1000) if number not in used_numbers), None)
    if next_number is None:
        raise HTTPException(status_code=400, detail={"code": 400, "message": "角色编号已用完", "data": None})
    role_no = f"{next_number:03d}"
    role = Role(code=f"custom_{role_no}", role_no=role_no, name=payload.name.strip(), description=payload.description.strip(), permissions=permissions_for_codes(db, payload.permission_codes))
    db.add(role)
    db.commit()
    db.refresh(role)
    return ok(serialize_role(role))


@router.put("/{role_id}")
def update_role(role_id: int, payload: RoleUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "角色不存在", "data": None})
    if role.code in {"pending", "admin"}:
        raise HTTPException(status_code=400, detail={"code": 400, "message": "该系统角色不允许修改", "data": None})
    duplicate = db.query(Role).filter(Role.name == payload.name.strip(), Role.id != role.id).first()
    if duplicate:
        raise HTTPException(status_code=409, detail={"code": 409, "message": "角色名称已存在", "data": None})
    role.name = payload.name.strip()
    role.description = payload.description.strip()
    role.permissions = permissions_for_codes(db, payload.permission_codes)
    db.commit()
    db.refresh(role)
    return ok(serialize_role(role, db.query(User).filter(User.role_id == role.id).count()))


@router.delete("/{role_id}")
def delete_role(role_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "角色不存在", "data": None})
    if role.is_system:
        raise HTTPException(status_code=400, detail={"code": 400, "message": "系统预置角色不能删除", "data": None})
    user_count = db.query(User).filter(User.role_id == role.id).count()
    if user_count:
        raise HTTPException(status_code=400, detail={"code": 400, "message": "该角色仍有用户，请先调整用户角色", "data": None})
    role.permissions = []
    db.flush()
    db.delete(role)
    db.commit()
    return ok({"id": role_id})
