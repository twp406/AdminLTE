"""数据清洗层：字段归一化 → 无效数据剔除 → 重复合并 → 异常价格识别。"""

from __future__ import annotations

import html
import re
import statistics
import unicodedata
from typing import Any

from .models import CleanResult, CleanStats, Product

TAG_RE = re.compile(r"<[^>]+>")
ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2028\u2029\ufeff]")
NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
MARKETING_SUFFIXES = (
    "官方正品",
    "正品保障",
    "限时特惠",
    "限时折扣",
    "官方旗舰店",
    "旗舰店",
    "包邮",
    "秒杀",
    "热卖",
)

PRICE_MIN = 5.0
PRICE_MAX = 50_000.0


def parse_price(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = html.unescape(str(value)).replace(",", "").replace("，", "")
        if "万" in text:
            match = NUMBER_RE.search(text)
            if not match:
                return None
            number = float(match.group()) * 10_000
        else:
            match = NUMBER_RE.search(text)
            if not match:
                return None
            number = float(match.group())
    if number <= 0:
        return None
    return round(number, 2)


def parse_sales(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = html.unescape(str(value)).replace(",", "").replace("，", "")
    match = NUMBER_RE.search(text)
    if not match:
        return 0
    number = float(match.group())
    if "万" in text:
        number *= 10_000
    return max(0, int(number))


def parse_rating(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    match = NUMBER_RE.search(str(value))
    if not match:
        return None
    rating = float(match.group())
    if rating <= 0 or rating > 5:
        return None
    return round(rating, 2)


def clean_title(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = TAG_RE.sub(" ", text)
    text = ZERO_WIDTH_RE.sub("", text)
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def title_key(title: str) -> str:
    """生成去重指纹：去掉营销后缀、标点、空格与大小写差异。"""
    text = unicodedata.normalize("NFKC", title).lower()
    changed = True
    while changed:
        changed = False
        for suffix in MARKETING_SUFFIXES:
            if text.endswith(suffix):
                text = text[: -len(suffix)].strip()
                changed = True
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _merge(bucket: list[Product], candidate: Product) -> Product | None:
    """若与同平台同标题商品价格接近，则视为重复铺货并合并。"""
    for existing in bucket:
        tolerance = max(5.0, 0.2 * min(existing.price, candidate.price))
        if abs(existing.price - candidate.price) <= tolerance:
            if candidate.sales > existing.sales:
                for field in ("id", "title", "price", "original_price", "sales", "shop", "url", "coupon"):
                    setattr(existing, field, getattr(candidate, field))
            existing.rating = existing.rating or candidate.rating
            existing.original_price = existing.original_price or candidate.original_price
            return existing
    return None


def _remove_outliers(products: list[Product], stats: CleanStats) -> list[Product]:
    by_platform: dict[str, list[Product]] = {}
    for product in products:
        by_platform.setdefault(product.platform, []).append(product)

    kept: list[Product] = []
    for group in by_platform.values():
        prices = [item.price for item in group]
        median = statistics.median(prices)
        q3 = statistics.quantiles(prices, n=4)[2] if len(prices) >= 8 else max(prices)
        upper_soft = max(q3 * 2.5, median * 8)
        for product in group:
            if product.price < PRICE_MIN or product.price > PRICE_MAX:
                stats.outliers += 1
                continue
            if len(group) >= 8 and product.price > upper_soft:
                stats.outliers += 1
                continue
            kept.append(product)
    return kept


def _impute_rating(products: list[Product], stats: CleanStats) -> None:
    by_platform: dict[str, list[float]] = {}
    for product in products:
        if product.rating is not None:
            by_platform.setdefault(product.platform, []).append(product.rating)
    overall = [rating for values in by_platform.values() for rating in values]
    fallback = statistics.median(overall) if overall else 4.6
    for product in products:
        if product.rating is None:
            values = by_platform.get(product.platform)
            product.rating = round(statistics.median(values) if values else fallback, 1)
            stats.imputed += 1


def clean_records(raw_records: list[dict[str, Any]]) -> CleanResult:
    stats = CleanStats(raw=len(raw_records))
    normalized: list[Product] = []

    for row in raw_records:
        title = clean_title(row.get("title"))
        price = parse_price(row.get("price"))
        if not title or len(title) < 3 or price is None:
            stats.invalid += 1
            continue

        platform = str(row.get("platform") or "jd")
        original = parse_price(row.get("original_price"))
        if original is not None and original <= price:
            original = None

        normalized.append(
            Product(
                id=str(row.get("id") or f"{platform}-{abs(hash(title)) % 10**10}"),
                platform=platform,
                platform_name=str(row.get("platform_name") or platform),
                title=title,
                price=price,
                original_price=original,
                sales=parse_sales(row.get("sales")),
                rating=parse_rating(row.get("rating")),
                shop=clean_title(row.get("shop")) or "未知店铺",
                url=str(row.get("url") or ""),
                coupon=clean_title(row.get("coupon")),
            )
        )

    stats.valid = len(normalized)

    # 同平台 + 同标题指纹 + 价格接近 → 合并重复铺货
    buckets: dict[str, list[Product]] = {}
    deduped: list[Product] = []
    for product in normalized:
        key = f"{product.platform}|{title_key(product.title)}"
        bucket = buckets.setdefault(key, [])
        merged = _merge(bucket, product)
        if merged is not None:
            stats.duplicates += 1
        else:
            bucket.append(product)
            deduped.append(product)

    deduped = _remove_outliers(deduped, stats)
    _impute_rating(deduped, stats)
    stats.cleaned = len(deduped)
    return CleanResult(products=deduped, stats=stats)
