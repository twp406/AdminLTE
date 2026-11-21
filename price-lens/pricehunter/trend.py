"""价格趋势：演示模式使用确定性历史曲线，实时模式按当前价格回推参考曲线。"""

from __future__ import annotations

import hashlib
import math
import random
import statistics
from datetime import date, timedelta
from typing import Any

from .models import Product


def _seed(*parts: str) -> int:
    text = "|".join(parts).lower().encode("utf-8")
    return int.from_bytes(hashlib.blake2b(text, digest_size=8).digest(), "big")


def _series(base: float, days: int, drift: float, seed: int) -> list[float]:
    rnd = random.Random(seed)
    phase = rnd.uniform(0, math.tau)
    points: list[float] = []
    for index in range(days):
        progress = index / (days - 1)
        trend = 1 + drift * (1 - progress)
        wave = 1 + 0.022 * math.sin(index * 0.72 + phase) * (1 - 0.55 * progress)
        noise = 1 + rnd.uniform(-0.007, 0.007) * (1 - progress)
        points.append(round(base * trend * wave * noise, 2))
    points[-1] = round(base, 2)
    return points


def _delta(points: list[float]) -> float:
    if len(points) < 2 or points[0] == 0:
        return 0.0
    return round((points[-1] - points[0]) / points[0] * 100, 1)


def build_trend(
    keyword: str,
    products: list[Product],
    featured: Product | None = None,
    basis: str = "demo",
    days: int = 30,
) -> dict[str, Any]:
    today = date.today()
    labels = [(today - timedelta(days=days - 1 - index)).strftime("%m-%d") for index in range(days)]

    groups: dict[str, list[Product]] = {}
    for product in products:
        groups.setdefault(product.platform, []).append(product)

    platform_series = []
    for code, items in groups.items():
        base = statistics.median(item.price for item in items)
        rnd = random.Random(_seed(keyword, code, "drift"))
        drift = rnd.uniform(-0.095, 0.02)
        points = _series(base, days, drift, _seed(keyword, code, basis))
        platform_series.append(
            {
                "code": code,
                "name": items[0].platform_name,
                "data": points,
                "delta_pct": _delta(points),
                "median": round(base, 2),
            }
        )
    platform_series.sort(key=lambda row: row["median"])

    product_series = None
    if featured is not None:
        rnd = random.Random(_seed(keyword, featured.id, "drift"))
        points = _series(
            featured.price,
            days,
            rnd.uniform(-0.08, 0.015),
            _seed(keyword, featured.id, basis),
        )
        product_series = {
            "id": featured.id,
            "name": featured.title,
            "platform": featured.platform,
            "platform_name": featured.platform_name,
            "price": featured.price,
            "data": points,
            "delta_pct": _delta(points),
        }

    overall_delta = 0.0
    if platform_series:
        overall_delta = round(sum(row["delta_pct"] for row in platform_series) / len(platform_series), 1)

    return {
        "labels": labels,
        "window_days": days,
        "basis": basis,
        "platform_series": platform_series,
        "product_series": product_series,
        "delta_pct": overall_delta,
    }
