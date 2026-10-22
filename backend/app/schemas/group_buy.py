from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
Quantity = Annotated[int, Field(strict=True, ge=0, le=100_000_000)]
BRANDS = ["兰蔻", "资生堂", "YSL", "植村秀", "赫莲娜"]


class CreateBatch(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    brand: Literal["兰蔻", "资生堂", "YSL", "植村秀", "赫莲娜"]
    name: str = Field(min_length=1, max_length=64)
    copy_from: int | None = None


class RevisionInput(BaseModel):
    revision: int = Field(ge=1)


class RenameBatch(RevisionInput):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class CellInput(BaseModel):
    product_id: str
    kind: Literal["order", "allocation"]
    column_id: str
    quantity: Quantity


class SaveCells(RevisionInput):
    cells: list[CellInput] = Field(min_length=1, max_length=10_000)


class AddColumn(RevisionInput):
    source: Name
    customer: Annotated[str, StringConstraints(strip_whitespace=True, max_length=128)] = ""
    counter: bool = False


class RenameLabel(RevisionInput):
    name: Name


class AddQuota(RevisionInput):
    product_id: str
    source: Name
    mode: Literal["add", "set"] = "add"
    quantity: Quantity
    note: str = Field(min_length=1, max_length=500)


class ProductInput(RevisionInput):
    code: Name
    name: str = Field(min_length=1, max_length=300)
    barcode: str = Field(default="", max_length=128)
    price: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    abc: str = Field(default="", max_length=32)
    pcb: Quantity | None = None


class ImportInput(RevisionInput):
    # Import payload is parsed server-side from the selected workbook(s).
    model_config = ConfigDict(extra="forbid")
    pass
