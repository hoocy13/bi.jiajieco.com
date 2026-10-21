from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PriceInput(BaseModel):
    product_code: str = Field(min_length=1, max_length=128)
    barcode: str | None = Field(default=None, max_length=128)
    product_name: str = Field(default="", max_length=255)
    price: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    effective_date: date = Field(default_factory=date.today)
    pricing_mode: Literal["fixed", "discount"] = "fixed"
    discount: Decimal | None = Field(default=None, gt=0, le=10, max_digits=7, decimal_places=4)
    base_retail_price: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    expected_revision_id: int | None = None

    @model_validator(mode="after")
    def validate_price(self):
        self.product_code = self.product_code.strip()
        if not self.product_code:
            raise ValueError("商品编号不能为空")
        if self.pricing_mode == "fixed" and (self.price is None or self.discount is not None):
            raise ValueError("直接填价需要有效成本价，折扣应留空")
        if self.pricing_mode == "discount" and self.discount is None:
            raise ValueError("请填写核心成本折扣（0～10 折）")
        return self


class ImportInput(BaseModel):
    rows: list[PriceInput] = Field(min_length=1, max_length=5000)


class BatchPriceInput(BaseModel):
    keyword: str = Field(default="", max_length=255)
    brand: list[str] = Field(default_factory=list, max_length=100)
    product_type: list[str] = Field(default_factory=list, max_length=100)
    discount: Decimal = Field(gt=0, le=10, max_digits=7, decimal_places=4)
    overwrite_fixed: bool = False
