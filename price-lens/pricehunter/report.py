"""报告输出：终端表格、JSON、CSV、Markdown。"""

from __future__ import annotations

import csv
import io
import json
import sys
import unicodedata
from typing import Any

SORTS = {"price": "价格升序", "value": "性价比优先", "sales": "销量优先", "rating": "评分优先"}


def display_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def truncate(text: str, width: int) -> str:
    text = str(text)
    if display_width(text) <= width:
        return text
    result = ""
    current = 0
    for char in text:
        char_width = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if current + char_width > width - 1:
            break
        result += char
        current += char_width
    return result + "…"


def pad(text: str, width: int, align: str = "left") -> str:
    text = truncate(text, width)
    gap = max(0, width - display_width(text))
    if align == "right":
        return " " * gap + text
    if align == "center":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


def price_text(value: float | None) -> str:
    if value is None:
        return "-"
    return f"¥{value:,.0f}" if abs(value - round(value)) < 0.005 else f"¥{value:,.2f}"


def sales_text(value: int) -> str:
    if value >= 10_000:
        return f"{value / 10_000:.1f}万"
    return f"{value:,}"


class Palette:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def price(self, text: str) -> str:
        return self._wrap("33", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)


COLUMNS = [
    ("排名", 4, "left"),
    ("商品", 32, "left"),
    ("平台", 6, "left"),
    ("价格", 9, "right"),
    ("销量", 8, "right"),
    ("评分", 5, "right"),
    ("性价比", 7, "right"),
    ("标签", 22, "left"),
]


def render_table(result: dict[str, Any], color: bool = True) -> str:
    palette = Palette(color and sys.stdout.isatty())
    stats = result["clean_stats"]
    lines: list[str] = []

    title = f"比价报告 · {result['keyword']}"
    lines.append(palette.bold(title))
    lines.append(
        palette.dim(
            f"数据源 {result['source_label']} ｜ 采集 {stats['raw']} 条 → 有效 {stats['cleaned']} 条 → "
            f"展示 {len(result['products'])} 条 ｜ 排序 {SORTS.get(result['query']['sort'], '价格升序')} ｜ "
            f"耗时 {result['elapsed_ms']} ms"
        )
    )
    if result.get("warnings"):
        for warning in result["warnings"]:
            lines.append(palette.red(f"! {warning}"))
    lines.append("")

    header = "  ".join(pad(name, width, align) for name, width, align in COLUMNS)
    lines.append(palette.bold(header))
    lines.append(palette.dim("─" * display_width(header)))

    for product in result["products"]:
        cells = [
            pad(str(product["rank"]), 4),
            pad(product["title"], 32),
            pad(product["platform_name"], 6),
            pad(price_text(product["price"]), 9, "right"),
            pad(sales_text(product["sales"]), 8, "right"),
            pad(f"{product['rating']:.1f}" if product["rating"] else "-", 5, "right"),
            pad(f"{product['value_score']:.1f}", 7, "right"),
            pad("·".join(product["tags"][:2]), 22),
        ]
        cells[3] = palette.price(cells[3])
        if product["rank"] <= 3:
            cells[0] = palette.green(cells[0])
        lines.append("  ".join(cells))

    lines.append("")
    summary = result.get("stats") or {}
    if summary:
        lines.append(
            f"价格区间 {palette.price(price_text(summary['min']))} – {palette.price(price_text(summary['max']))}"
            f" ｜ 中位数 {price_text(summary['median'])} ｜ 均值 {price_text(summary['avg'])}"
            f" ｜ 价差 {summary['spread_pct']}%"
        )
    lines.append(
        palette.dim(
            f"清洗：去重 {stats['duplicates']} · 异常价 {stats['outliers']} · "
            f"无效 {stats['invalid']} · 补全 {stats['imputed']}"
        )
    )

    if result.get("recommendations"):
        lines.append("")
        lines.append(palette.bold("性价比推荐"))
        for pick in result["recommendations"][:4]:
            product = pick["product"]
            line = (
                f"  [{pick['badge']}] {product['platform_name']} {price_text(product['price'])}  "
                f"{truncate(product['title'], 36)}  ({pick['reason']})"
                f"  {product['url']}"
            )
            lines.append(line)

    if result.get("platforms"):
        lines.append("")
        lines.append(palette.bold("平台横向对比"))
        for row in result["platforms"]:
            lines.append(
                f"  {pad(row['name'], 6)} {pad(str(row['count']) + ' 件', 7, 'right')}  "
                f"最低 {pad(price_text(row['min']), 9, 'right')}  "
                f"中位 {pad(price_text(row['median']), 9, 'right')}  "
                f"最高 {pad(price_text(row['max']), 9, 'right')}"
            )

    trend = result.get("trend") or {}
    if trend.get("platform_series"):
        delta = trend["delta_pct"]
        arrow = "↓" if delta < 0 else "↑"
        tone = palette.green if delta < 0 else palette.red
        lines.append("")
        lines.append(
            palette.bold("近 30 天趋势  ")
            + tone(f"平台均价 {arrow} {abs(delta)}%")
            + palette.dim("（网页端可查看逐日曲线）")
        )

    return "\n".join(lines)


def render_markdown(result: dict[str, Any]) -> str:
    stats = result["clean_stats"]
    summary = result.get("stats") or {}
    trend = result.get("trend") or {}
    lines = [
        f"# 电商比价报告：{result['keyword']}",
        "",
        f"> 数据源：{result['source_label']} ｜ 生成时间：{result['generated_at']} ｜ 耗时：{result['elapsed_ms']} ms",
        f"> 采集 {stats['raw']} 条 → 有效 {stats['cleaned']} 条 → 展示 {len(result['products'])} 条",
        "",
        "## 核心结论",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        f"| 最低价 | {price_text(summary['min'])}（{summary['cheapest']['platform_name']} · {summary['cheapest']['title']}） |",
        f"| 价格中位数 | {price_text(summary['median'])} |",
        f"| 价格均值 | {price_text(summary['avg'])} |",
        f"| 平台价差 | {summary['spread_pct']}% |",
        f"| 性价比最高 | {summary['best_value']['title']}（{summary['best_value']['score']} 分） |",
        f"| 近 30 天均价变化 | {trend.get('delta_pct', 0)}% |",
        "",
        "## 性价比推荐",
        "",
    ]
    for pick in result.get("recommendations", [])[:4]:
        product = pick["product"]
        lines.extend(
            [
                f"### {pick['badge']} · {product['title']}",
                "",
                f"- 平台：{product['platform_name']} ｜ 价格：{price_text(product['price'])} ｜ "
                f"月销：{sales_text(product['sales'])} ｜ 评分：{product['rating']}",
                f"- 理由：{pick['reason']}",
                f"- 链接：<{product['url']}>",
                "",
            ]
        )

    lines.extend(
        [
            "## 商品横向对比",
            "",
            "| # | 商品 | 平台 | 价格 | 月销 | 评分 | 性价比 | 标签 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for product in result["products"]:
        lines.append(
            f"| {product['rank']} | [{product['title']}]({product['url']}) | {product['platform_name']} | "
            f"{price_text(product['price'])} | {sales_text(product['sales'])} | "
            f"{product['rating'] or '-'} | {product['value_score']} | {' '.join(product['tags'])} |"
        )

    lines.extend(["", "## 平台对比", "", "| 平台 | 商品数 | 最低价 | 中位价 | 最高价 |", "| --- | ---: | ---: | ---: | ---: |"])
    for row in result.get("platforms", []):
        lines.append(
            f"| {row['name']} | {row['count']} | {price_text(row['min'])} | "
            f"{price_text(row['median'])} | {price_text(row['max'])} |"
        )

    lines.extend(["", "## 价格趋势", ""])
    for series in trend.get("platform_series", []):
        lines.append(f"- {series['name']}：中位价 {price_text(series['median'])}，近 30 天 {series['delta_pct']}%")

    lines.extend(
        [
            "",
            "## 数据质量",
            "",
            f"- 原始记录：{stats['raw']} 条",
            f"- 字段无效剔除：{stats['invalid']} 条",
            f"- 重复铺货合并：{stats['duplicates']} 条",
            f"- 异常价格剔除：{stats['outliers']} 条",
            f"- 缺失评分补全：{stats['imputed']} 条",
            "",
            "## 说明",
            "",
            "- 演示数据由关键词种子确定性生成，不依赖网络，可重复复现。",
            "- 实时采集需遵守目标平台 robots.txt 与服务条款，并配置登录 Cookie；仅建议用于学习研究。",
            "- 性价比评分为价格 45% + 销量 35% + 店铺评分 20% 的归一化加权结果。",
        ]
    )
    return "\n".join(lines)


def render_csv(result: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "rank",
            "platform",
            "title",
            "price",
            "original_price",
            "sales",
            "rating",
            "value_score",
            "shop",
            "coupon",
            "tags",
            "url",
        ]
    )
    for product in result["products"]:
        writer.writerow(
            [
                product["rank"],
                product["platform_name"],
                product["title"],
                product["price"],
                product["original_price"] or "",
                product["sales"],
                product["rating"] or "",
                product["value_score"],
                product["shop"],
                product["coupon"],
                "|".join(product["tags"]),
                product["url"],
            ]
        )
    return buffer.getvalue()


def render_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)


def render(result: dict[str, Any], fmt: str, color: bool = True) -> str:
    if fmt == "json":
        return render_json(result)
    if fmt == "csv":
        return render_csv(result)
    if fmt == "md":
        return render_markdown(result)
    return render_table(result, color=color)
