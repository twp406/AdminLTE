"""分析层：性价比评分、平台横向对比、推荐标注。"""

from __future__ import annotations

import math
import statistics
from typing import Any

from .models import Product

BADGES = {
    "value": "性价比首选",
    "cheapest": "全场最低",
    "sales": "销量冠军",
    "rating": "口碑之选",
}


def _scale(value: float, low: float, high: float) -> float:
    if high - low < 1e-9:
        return 100.0
    return max(0.0, min(100.0, (value - low) / (high - low) * 100))


def enrich(products: list[Product]) -> None:
    """为商品计算各维度得分与标签。"""
    if not products:
        return
    prices = [max(product.price, 0.01) for product in products]
    logs = [math.log(price) for price in prices]
    log_min, log_max = min(logs), max(logs)
    max_sales = max(product.sales for product in products) or 1
    loop_max = math.log1p(max_sales)
    median_price = statistics.median(prices)

    for product in products:
        price_score = _scale(-math.log(max(product.price, 0.01)), -log_max, -log_min)
        sales_score = math.log1p(max(product.sales, 0)) / loop_max * 100 if loop_max else 0.0
        rating = product.rating if product.rating is not None else 4.5
        rating_score = _scale(rating, 3.5, 5.0)
        product.price_score = price_score
        product.sales_score = sales_score
        product.rating_score = rating_score
        product.value_score = round(0.45 * price_score + 0.35 * sales_score + 0.20 * rating_score, 1)
        product.price_gap_pct = (product.price - median_price) / median_price * 100

    ranked_sales = sorted(products, key=lambda item: item.sales, reverse=True)
    ranked_price = sorted(products, key=lambda item: item.price)
    ranked_rating = sorted(products, key=lambda item: item.rating or 0, reverse=True)

    for product in products:
        tags: list[str] = []
        if product.value_score >= 78:
            tags.append("高性价比")
        if product.price_gap_pct <= -15:
            tags.append("低于均价")
        if product.sales >= ranked_sales[min(2, len(ranked_sales) - 1)].sales:
            tags.append("热销")
        if (product.rating or 0) >= 4.8:
            tags.append("口碑好")
        product.tags = tags[:3]

    # 给头部商品加上强标签
    best_value = max(products, key=lambda item: item.value_score)
    cheapest = min(products, key=lambda item: item.price)
    top_sales = ranked_sales[0]
    top_rating = ranked_rating[0]
    for product, badge in (
        (best_value, BADGES["value"]),
        (cheapest, BADGES["cheapest"]),
        (top_sales, BADGES["sales"]),
        (top_rating, BADGES["rating"]),
    ):
        if badge not in product.tags:
            product.tags.insert(0, badge)
        product.tags = product.tags[:4]


def platform_stats(products: list[Product]) -> list[dict[str, Any]]:
    groups: dict[str, list[Product]] = {}
    for product in products:
        groups.setdefault(product.platform, []).append(product)

    stats = []
    for code, items in groups.items():
        prices = [item.price for item in items]
        stats.append(
            {
                "code": code,
                "name": items[0].platform_name,
                "count": len(items),
                "min": round(min(prices), 2),
                "max": round(max(prices), 2),
                "avg": round(sum(prices) / len(prices), 2),
                "median": round(statistics.median(prices), 2),
            }
        )
    stats.sort(key=lambda row: row["median"])
    return stats


def summarize(products: list[Product]) -> dict[str, Any]:
    if not products:
        return {}
    prices = [product.price for product in products]
    median_price = statistics.median(prices)
    best_value = max(products, key=lambda item: item.value_score)
    cheapest = min(products, key=lambda item: item.price)
    return {
        "count": len(products),
        "min": round(min(prices), 2),
        "max": round(max(prices), 2),
        "avg": round(sum(prices) / len(prices), 2),
        "median": round(median_price, 2),
        "spread_pct": round((max(prices) - min(prices)) / max(prices) * 100, 1),
        "total_sales": sum(product.sales for product in products),
        "cheapest": {
            "id": cheapest.id,
            "title": cheapest.title,
            "price": cheapest.price,
            "platform": cheapest.platform,
            "platform_name": cheapest.platform_name,
        },
        "best_value": {
            "id": best_value.id,
            "title": best_value.title,
            "price": best_value.price,
            "score": best_value.value_score,
            "platform": best_value.platform,
            "platform_name": best_value.platform_name,
        },
    }


def recommendations(products: list[Product]) -> list[dict[str, Any]]:
    if not products:
        return []
    by_value = sorted(products, key=lambda item: item.value_score, reverse=True)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(kind: str, badge: str, product: Product, reason: str) -> bool:
        if product.id in seen:
            return False
        seen.add(product.id)
        result.append(
            {
                "type": kind,
                "badge": badge,
                "reason": reason,
                "product": product.to_dict(),
            }
        )
        return True

    best = by_value[0]
    gap_text = f"低于均价 {abs(best.price_gap_pct):.0f}%" if best.price_gap_pct < 0 else f"高于均价 {best.price_gap_pct:.0f}%"
    add("value", BADGES["value"], best, f"综合评分 {best.value_score} 分，{gap_text}，销量 {best.sales:,}")

    cheapest = min(products, key=lambda item: item.price)
    add("cheapest", BADGES["cheapest"], cheapest, f"全场最低价 ¥{cheapest.price:,.0f}，适合预算优先")

    for index, product in enumerate(sorted(products, key=lambda item: item.sales, reverse=True)):
        if product.id in seen:
            continue
        badge = BADGES["sales"] if index == 0 else "热销之选"
        add("sales", badge, product, f"月销 {product.sales:,} 件，市场热度领先")
        break

    for product in sorted(products, key=lambda item: item.rating or 0, reverse=True):
        if product.id in seen:
            continue
        add("rating", BADGES["rating"], product, f"店铺评分 {product.rating}，售后与口碑更稳")
        break

    for product in by_value:
        if len(result) >= 4:
            break
        add("value", "值得关注", product, f"综合评分 {product.value_score} 分，可加入对比")
    return result
