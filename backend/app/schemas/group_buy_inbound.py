from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated


class InboundScope(BaseModel):
    start_date: date
    end_date: date
    brand: str = Field(min_length=1, max_length=32)


class CounterMapping(BaseModel):
    batch_id: int = Field(gt=0)
    revision: int = Field(ge=1)
    source_id: str
    supplier: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    supplier_code: str | None = Field(default=None, max_length=128)


class LineVersion(BaseModel):
    id: int = Field(gt=0)
    revision: int = Field(ge=1)


class InboundAction(BaseModel):
    action: Literal['confirm', 'exclude', 'release']
    lines: list[LineVersion] = Field(min_length=1, max_length=1000)
    batch_id: int | None = Field(default=None, gt=0)
    batch_revision: int | None = Field(default=None, ge=1)
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ''


class ReceiptAssignment(LineVersion):
    batch_id: int = Field(gt=0)
    batch_revision: int = Field(ge=1)
    source_id: str = Field(min_length=1, max_length=32)
    product_id: str | None = Field(default=None, max_length=32)
    mode: Literal['normal', 'substitute'] = 'normal'
    credit_quantity: int | None = Field(default=None, gt=0, le=100_000_000)
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ''


class ReceiptConfirmation(BaseModel):
    lines: list[ReceiptAssignment] = Field(min_length=1, max_length=1000)


class ReceiptHoldAction(BaseModel):
    revision: int = Field(ge=0)
    waiting: bool = True
    month: str = Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    counter: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ''


class OrderCollectionEdit(BaseModel):
    revision: int = Field(ge=0)
    month: str = Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    brand: str = Field(min_length=1, max_length=32)
    counter: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    batch_id: int | None = Field(default=None, gt=0)
    status: Literal['missing', 'partial', 'received'] = 'missing'
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ''
