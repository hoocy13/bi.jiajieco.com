from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.session import Base, SessionLocal, engine
from app.core.model_crypto import encrypt_api_key
from app.models.model_setting import ModelSetting
from app.models.announcement import Announcement  # noqa: F401
from app.models.user import Permission, Role, User


PERMISSION_DEFINITIONS = [
    ("dashboard.view", "经营总览", "dashboard"),
    ("sales.view", "销售分析", "sales"),
    ("inventory.view", "库存分析", "inventory"),
    ("ai.decision.view", "AI 决策中心", "ai"),
    ("ai.assistant.use", "AI 数据助手", "ai"),
    ("ai.text_to_sql.use", "数据智能问答", "ai"),
    ("data.export", "数据导出", "operation"),
    ("system.users.manage", "账号权限管理", "system"),
    ("system.roles.manage", "角色管理", "system"),
    ("system.models.manage", "模型设置", "system"),
    ("system.announcements.manage", "系统公告", "system"),
]

ROLE_DEFINITIONS = [
    ("001", "pending", "待授权用户", "新注册用户的默认角色", []),
    ("002", "viewer", "普通查看者", "仅查看经营总览", ["dashboard.view"]),
    ("003", "data_analyst", "数据分析师", "经营、销售、库存与分析工具", ["dashboard.view", "sales.view", "inventory.view", "ai.decision.view", "ai.assistant.use", "data.export"]),
    ("004", "sales", "销售人员", "经营总览和销售分析", ["dashboard.view", "sales.view"]),
    ("005", "inventory", "库存人员", "经营总览和库存分析", ["dashboard.view", "inventory.view"]),
    ("006", "management", "管理层", "经营、销售、库存和导出", ["dashboard.view", "sales.view", "inventory.view", "data.export"]),
    ("007", "admin", "系统管理员", "系统全部权限", [item[0] for item in PERMISSION_DEFINITIONS]),
]


def ensure_user_columns() -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("users")}
    statements = {
        "email": "ALTER TABLE users ADD COLUMN email VARCHAR(255)",
        "display_name": "ALTER TABLE users ADD COLUMN display_name VARCHAR(64)",
        "phone": "ALTER TABLE users ADD COLUMN phone VARCHAR(32)",
        "role_id": "ALTER TABLE users ADD COLUMN role_id INTEGER",
        "created_at": "ALTER TABLE users ADD COLUMN created_at DATETIME",
        "last_login_at": "ALTER TABLE users ADD COLUMN last_login_at DATETIME",
    }
    with engine.begin() as connection:
        for name, statement in statements.items():
            if name not in columns:
                connection.execute(text(statement))
        indexes = {index["name"] for index in inspect(connection).get_indexes("users")}
        if "ix_users_email" not in indexes:
            connection.execute(text("CREATE UNIQUE INDEX ix_users_email ON users (email)"))
        if "ix_users_role_id" not in indexes:
            connection.execute(text("CREATE INDEX ix_users_role_id ON users (role_id)"))


def ensure_role_columns() -> None:
    columns = {column["name"] for column in inspect(engine).get_columns("roles")}
    with engine.begin() as connection:
        if "role_no" not in columns:
            connection.execute(text("ALTER TABLE roles ADD COLUMN role_no VARCHAR(3)"))
        indexes = {index["name"] for index in inspect(connection).get_indexes("roles")}
        if "ix_roles_role_no" not in indexes:
            connection.execute(text("CREATE UNIQUE INDEX ix_roles_role_no ON roles (role_no)"))


def seed_roles(db: Session) -> dict[str, Role]:
    permissions: dict[str, Permission] = {}
    for order, (code, name, module) in enumerate(PERMISSION_DEFINITIONS):
        permission = db.query(Permission).filter(Permission.code == code).first()
        if permission is None:
            permission = Permission(code=code, name=name, module=module, sort_order=order)
            db.add(permission)
        permissions[code] = permission
    db.flush()

    roles: dict[str, Role] = {}
    for role_no, code, name, description, permission_codes in ROLE_DEFINITIONS:
        role = db.query(Role).filter(Role.code == code).first()
        if role is None:
            role = Role(
                code=code,
                role_no=role_no,
                name=name,
                description=description,
                is_system=True,
                is_active=True,
                permissions=[permissions[item] for item in permission_codes],
            )
            db.add(role)
        elif role.role_no is None:
            role.role_no = role_no
        elif code == "admin":
            role.permissions = [permissions[item] for item in permission_codes]
        roles[code] = role
    db.flush()
    used_numbers = {int(role.role_no) for role in db.query(Role).all() if role.role_no and role.role_no.isdigit()}
    for role in db.query(Role).filter(Role.role_no.is_(None)).order_by(Role.id.asc()).all():
        next_number = next((number for number in range(1, 1000) if number not in used_numbers), None)
        if next_number is None:
            break
        role.role_no = f"{next_number:03d}"
        used_numbers.add(next_number)
    return roles


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_user_columns()
    ensure_role_columns()
    db: Session = SessionLocal()
    try:
        roles = seed_roles(db)
        user = db.query(User).filter(User.username == settings.DEMO_USERNAME).first()
        if user is None:
            db.add(
                User(
                    username=settings.DEMO_USERNAME,
                    hashed_password=get_password_hash(settings.DEMO_PASSWORD),
                    is_active=True,
                    display_name="系统管理员",
                    role=roles["admin"],
                )
            )
        elif user.role_id is None:
            user.role = roles["admin"]
        db.commit()
        model_setting = db.get(ModelSetting, 1)
        if model_setting is None and settings.OPENAI_BASE_URL and settings.OPENAI_MODEL_ID:
            db.add(
                ModelSetting(
                    id=1,
                    base_url=settings.OPENAI_BASE_URL.rstrip("/"),
                    model_id=settings.OPENAI_MODEL_ID,
                    api_key_encrypted=encrypt_api_key(settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else "",
                )
            )
            db.commit()
    finally:
        db.close()
