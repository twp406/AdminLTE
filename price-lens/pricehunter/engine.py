"""流水线编排：采集 → 清洗 → 分析 → 排序 → 输出。"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from .adapters import (
    AdapterError,
    BaseAdapter,
    DemoAdapter,
    JDAdapter,
    PDDAdapter,
    TaobaoAdapter,
)
from .analyze import enrich, platform_stats, recommendations, summarize
from .clean import clean_records
from .models import PLATFORM_NAMES, Product
from .trend import build_trend

LIVE_ADAPTERS: dict[str, type[BaseAdapter]] = {
    "jd": JDAdapter,
    "tb": TaobaoAdapter,
    "pdd": PDDAdapter,
}

SORTERS = {
    "price": lambda product: product.price,
    "value": lambda product: -product.value_score,
    "sales": lambda product: -product.sales,
    "rating": lambda product: -(product.rating or 0),
}


class PipelineError(RuntimeError):
    def __init__(self, message: str, warnings: list[str] | None = None):
        super().__init__(message)
        self.warnings = warnings or []


def _dirtiness(record: dict[str, Any]) -> int:
    score = 0
    price = record.get("price")
    if isinstance(price, str):
        score += 2
    if price is None or price == "":
        score += 2
    try:
        number = float(str(price).replace("¥", "").replace(",", "").replace("￥", ""))
        if number < 5 or number > 50_000:
            score += 2
    except (TypeError, ValueError):
        pass
    title = str(record.get("title") or "")
    if "<" in title or "&amp;" in title:
        score += 1
    if isinstance(record.get("sales"), str) and "万" in str(record.get("sales")):
        score += 1
    if record.get("rating") is None:
        score += 1
    return score


def _sample_raw(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = sorted(raw, key=_dirtiness, reverse=True)
    picks = scored[:3]
    for record in raw:
        if len(picks) >= 4:
            break
        if record not in picks:
            picks.append(record)
    return picks[:4]


def _collect(
    keyword: str,
    platforms: list[str],
    source: str,
    limit: int,
    log: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    started = time.perf_counter()
    warnings: list[str] = []

    if source == "demo":
        raw = DemoAdapter().search(keyword, limit=limit)
        raw = [row for row in raw if row.get("platform") in platforms]
        log.append(
            {
                "step": "启动采集",
                "status": "ok",
                "detail": f"关键词「{keyword}」· 演示数据源 · {len(platforms)} 个平台",
                "ms": round((time.perf_counter() - started) * 1000, 1),
            }
        )
        for code in platforms:
            count = sum(1 for row in raw if row.get("platform") == code)
            log.append(
                {
                    "step": f"{PLATFORM_NAMES.get(code, code)} · 抓取",
                    "status": "ok",
                    "detail": f"获得 {count} 条原始记录",
                    "ms": 0,
                }
            )
        return raw, warnings

    raw: list[dict[str, Any]] = []
    for code in platforms:
        adapter_cls = LIVE_ADAPTERS.get(code)
        if adapter_cls is None:
            continue
        platform_started = time.perf_counter()
        try:
            records = adapter_cls().search(keyword, limit=limit)
            raw.extend(records)
            log.append(
                {
                    "step": f"{PLATFORM_NAMES.get(code, code)} · 实时抓取",
                    "status": "ok",
                    "detail": f"获得 {len(records)} 条原始记录",
                    "ms": round((time.perf_counter() - platform_started) * 1000, 1),
                }
            )
        except AdapterError as exc:
            warnings.append(f"{PLATFORM_NAMES.get(code, code)}: {exc}")
            log.append(
                {
                    "step": f"{PLATFORM_NAMES.get(code, code)} · 实时抓取",
                    "status": "warn",
                    "detail": str(exc),
                    "ms": round((time.perf_counter() - platform_started) * 1000, 1),
                }
            )

    if not raw:
        message = "实时采集失败，可切换为演示数据源，或配置 Cookie 后重试。"
        raise PipelineError(message, warnings)
    return raw, warnings


def run_pipeline(
    keyword: str,
    platforms: list[str] | None = None,
    source: str = "demo",
    sort: str = "price",
    limit: int = 30,
) -> dict[str, Any]:
    keyword = (keyword or "").strip()
    if not keyword:
        raise PipelineError("请输入搜索关键词")
    platforms = platforms or ["jd", "tb", "pdd"]
    platforms = [code for code in platforms if code in PLATFORM_NAMES]
    if not platforms:
        raise PipelineError("请至少选择一个平台")
    if source not in ("demo", "live"):
        raise PipelineError("数据源仅支持 demo 或 live")
    sort = sort if sort in SORTERS else "price"
    limit = max(1, min(int(limit), 100))

    started_all = time.perf_counter()
    log: list[dict[str, Any]] = []

    raw, warnings = _collect(keyword, platforms, source, limit, log)

    clean_started = time.perf_counter()
    cleaned = clean_records(raw)
    stats = cleaned.stats
    log.append(
        {
            "step": "字段清洗",
            "status": "ok",
            "detail": (
                f"有效 {stats.valid}/{stats.raw} 条 · 丢弃无效 {stats.invalid} 条 · "
                f"补全评分 {stats.imputed} 条"
            ),
            "ms": round((time.perf_counter() - clean_started) * 1000, 1),
        }
    )
    log.append(
        {
            "step": "去重合并",
            "status": "ok",
            "detail": f"合并同平台重复铺货 {stats.duplicates} 条，剔除异常价格 {stats.outliers} 条",
            "ms": 0,
        }
    )

    if not cleaned.products:
        raise PipelineError("清洗后没有可用商品，请更换关键词后重试", warnings)

    analyze_started = time.perf_counter()
    enrich(cleaned.products)
    summary = summarize(cleaned.products)
    platforms_summary = platform_stats(cleaned.products)
    picks = recommendations(cleaned.products)
    featured = max(cleaned.products, key=lambda item: item.value_score)
    log.append(
        {
            "step": "性价比建模",
            "status": "ok",
            "detail": f"价格 / 销量 / 评分加权评分，识别 {len(picks)} 个推荐位",
            "ms": round((time.perf_counter() - analyze_started) * 1000, 1),
        }
    )

    trend_started = time.perf_counter()
    trend = build_trend(
        keyword,
        cleaned.products,
        featured=featured,
        basis="demo" if source == "demo" else "modeled",
    )
    log.append(
        {
            "step": "趋势与对比",
            "status": "ok",
            "detail": f"生成 {trend['window_days']} 天价格曲线与 {len(platforms_summary)} 个平台横向对比",
            "ms": round((time.perf_counter() - trend_started) * 1000, 1),
        }
    )

    ordered = sorted(cleaned.products, key=SORTERS[sort])
    displayed = ordered[:limit]
    for index, product in enumerate(displayed, start=1):
        product.rank = index

    elapsed = round((time.perf_counter() - started_all) * 1000, 1)
    log.append(
        {
            "step": "完成",
            "status": "ok",
            "detail": f"输出 {len(displayed)} 条商品，总耗时 {elapsed} ms",
            "ms": 0,
        }
    )

    return {
        "keyword": keyword,
        "source": source,
        "source_label": "离线演示数据" if source == "demo" else "实时采集",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "elapsed_ms": elapsed,
        "query": {"platforms": platforms, "sort": sort, "limit": limit},
        "log": log,
        "warnings": warnings,
        "raw_count": stats.raw,
        "raw_sample": _sample_raw(raw),
        "clean_stats": stats.to_dict(),
        "stats": summary,
        "platforms": platforms_summary,
        "products": [product.to_dict() for product in displayed],
        "recommendations": picks,
        "trend": trend,
        "trend_featured": {
            "id": featured.id,
            "title": featured.title,
            "platform": featured.platform,
            "platform_name": featured.platform_name,
            "price": featured.price,
            "value_score": featured.value_score,
        },
    }
