"""领域数据模型：统一的商品结构与流水线结果。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


PLATFORM_NAMES = {"jd": "京东", "tb": "淘宝", "pdd": "拼多多"}


@dataclass(slots=True)
class Product:
    """清洗后的统一商品记录。"""

    id: str
    platform: str
    platform_name: str
    title: str
    price: float
    sales: int
    shop: str
    url: str
    original_price: float | None = None
    rating: float | None = None
    coupon: str = ""

    # 分析阶段写入
    value_score: float = 0.0
    price_score: float = 0.0
    sales_score: float = 0.0
    rating_score: float = 0.0
    price_gap_pct: float = 0.0
    tags: list[str] = field(default_factory=list)
    rank: int = 0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["price"] = round(self.price, 2)
        if self.original_price is not None:
            data["original_price"] = round(self.original_price, 2)
        if self.rating is not None:
            data["rating"] = round(self.rating, 2)
        for key in ("value_score", "price_score", "sales_score", "rating_score", "price_gap_pct"):
            data[key] = round(getattr(self, key), 1)
        return data


@dataclass(slots=True)
class CleanStats:
    raw: int = 0
    valid: int = 0
    cleaned: int = 0
    duplicates: int = 0
    outliers: int = 0
    invalid: int = 0
    imputed: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class CleanResult:
    products: list[Product]
    stats: CleanStats
