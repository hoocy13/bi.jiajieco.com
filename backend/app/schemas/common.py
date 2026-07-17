from typing import Generic, TypeVar

from pydantic import BaseModel


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T | None = None


def ok(data: T | None = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}


def fail(message: str, code: int = 1, data: T | None = None) -> dict:
    return {"code": code, "message": message, "data": data}
