from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.model_crypto import encrypt_api_key
from app.db.session import get_db
from app.models.model_setting import ModelSetting
from app.models.user import User
from app.schemas.common import ok
from app.schemas.model_setting import ModelSettingUpdate
from app.services.model_client import chat_completion, get_model_config


router = APIRouter(prefix="/model-settings", tags=["model-settings"])


def _masked_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 10:
        return "*" * len(api_key)
    return f"{api_key[:4]}{'*' * 12}{api_key[-4:]}"


@router.get("")
def get_model_setting(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    setting = db.get(ModelSetting, 1)
    decrypt_error = ""
    try:
        base_url, model_id, api_key = get_model_config(db)
    except ValueError as exc:
        base_url = setting.base_url.rstrip("/") if setting else ""
        model_id = setting.model_id if setting else ""
        api_key = ""
        decrypt_error = str(exc)
    return ok(
        {
            "provider": setting.provider if setting else "OpenAI Compatible",
            "base_url": base_url,
            "model_id": model_id,
            "api_key_masked": _masked_key(api_key),
            "configured": bool(base_url and model_id and api_key),
            "error": decrypt_error,
            "updated_at": setting.updated_at.isoformat() if setting else None,
        }
    )


@router.put("")
def update_model_setting(
    payload: ModelSettingUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    setting = db.get(ModelSetting, 1)
    if setting is None:
        setting = ModelSetting(
            id=1,
            base_url=payload.base_url.rstrip("/"),
            model_id=payload.model_id.strip(),
            api_key_encrypted="",
        )
        db.add(setting)
    else:
        setting.base_url = payload.base_url.rstrip("/")
        setting.model_id = payload.model_id.strip()

    if payload.api_key and payload.api_key.strip():
        setting.api_key_encrypted = encrypt_api_key(payload.api_key.strip())
    setting.updated_at = datetime.now()
    db.commit()
    return get_model_setting(current_user=current_user, db=db)


@router.post("/test")
def test_model_setting(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        response = chat_completion(
            db,
            [
                {"role": "system", "content": "你是连接测试助手。"},
                {"role": "user", "content": "只回复：连接成功"},
            ],
            max_tokens=32,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ok({"connected": True, "response": response})
