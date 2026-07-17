from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.session import Base, SessionLocal, engine
from app.core.model_crypto import encrypt_api_key
from app.models.model_setting import ModelSetting
from app.models.user import User


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.username == settings.DEMO_USERNAME).first()
        if user is None:
            db.add(
                User(
                    username=settings.DEMO_USERNAME,
                    hashed_password=get_password_hash(settings.DEMO_PASSWORD),
                    is_active=True,
                )
            )
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
        else:
            user.hashed_password = get_password_hash(settings.DEMO_PASSWORD)
            user.is_active = True
            db.commit()
    finally:
        db.close()
