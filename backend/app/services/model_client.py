import json
from json import JSONDecodeError
from socket import timeout as SocketTimeout
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.model_crypto import decrypt_api_key
from app.models.model_setting import ModelSetting


def get_model_config(db: Session) -> tuple[str, str, str]:
    setting = db.get(ModelSetting, 1)
    if setting is None:
        return "", "", ""
    try:
        api_key = decrypt_api_key(setting.api_key_encrypted)
    except InvalidToken as exc:
        raise ValueError("API Key 无法解密，请重新保存模型设置") from exc
    return setting.base_url.rstrip("/"), setting.model_id, api_key


def chat_completion(
    db: Session,
    messages: list[dict[str, str]],
    max_tokens: int = 800,
) -> str:
    base_url, model_id, api_key = get_model_config(db)
    if not base_url or not model_id or not api_key:
        raise ValueError("模型配置不完整")

    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(
            {
                "model": model_id,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": max_tokens,
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=settings.OPENAI_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"模型服务返回 {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"无法连接模型服务: {exc.reason}") from exc
    except SocketTimeout as exc:
        raise RuntimeError(f"模型服务响应超时，当前超时设置为 {settings.OPENAI_TIMEOUT_SECONDS} 秒") from exc
    except JSONDecodeError as exc:
        raise RuntimeError("模型服务响应不是合法 JSON") from exc

    try:
        return str(payload["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("模型响应格式不正确") from exc
