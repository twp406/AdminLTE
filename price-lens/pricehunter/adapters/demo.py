"""离线演示数据源。

用「关键词 + 固定随机种子」生成确定性的商品数据，并刻意混入
带货币符号的价格、带 HTML 标签的标题、缺失字段、重复记录和异常价格，
用于完整演示采集 → 清洗 → 去重 → 分析流水线，且不依赖任何网络。
"""

from __future__ import annotations

import hashlib
import random
from typing import Any

from .base import BaseAdapter

PLATFORMS = [
    ("jd", "京东", 1.00),
    ("tb", "淘宝", 0.955),
    ("pdd", "拼多多", 0.865),
]

SERIES = ["Pro", "Air", "Max", "Neo", "Lite", "Plus", "Ultra", "Mini", "S", "X", "SE", "Ace"]
EDITIONS = ["", "降噪版", "2025款", "旗舰版", "青春版", "长续航版"]

BRAND_TIERS = [
    ("premium", ["索尼", "华为", "Bose", "三星", "森海塞尔"], (599, 1899), 0.25),
    ("mid", ["小米", "漫步者", "倍思", "绿联", "罗技", "飞利浦", "JBL", "万魔"], (129, 699), 0.45),
    ("value", ["京东京造", "网易严选", "品胜", "纽曼", "QCY", "唐麦"], (39, 299), 0.30),
]

SHOP_SUFFIXES = ["官方旗舰店", "数码专营店", "官方直营店", "严选旗舰店"]
COUPONS = ["", "", "", "满199减20", "满99减10", "新人立减15", "跨店每满300减50"]


def _seed(keyword: str) -> int:
    digest = hashlib.blake2b(keyword.strip().lower().encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def _round_price(value: float) -> float:
    return float(max(19, round(value / 10) * 10 - 1))


def _pick_brand(rnd: random.Random) -> tuple[str, tuple[int, int]]:
    roll = rnd.random()
    acc = 0.0
    for _tier, brands, price_range, weight in BRAND_TIERS:
        acc += weight
        if roll <= acc:
            return rnd.choice(brands), price_range
    _tier, brands, price_range, _w = BRAND_TIERS[-1]
    return rnd.choice(brands), price_range


class DemoAdapter(BaseAdapter):
    code = "demo"
    name = "演示数据"

    def search(self, keyword: str, limit: int = 60) -> list[dict[str, Any]]:
        keyword = keyword.strip() or "蓝牙耳机"
        rnd = random.Random(_seed(keyword))
        records: list[dict[str, Any]] = []

        for code, pname, factor in PLATFORMS:
            platform_records: list[dict[str, Any]] = []
            for i in range(12):
                brand, price_range = _pick_brand(rnd)
                series = SERIES[i % len(SERIES)]
                edition = rnd.choice(EDITIONS)
                title = f"{brand} {keyword} {series}{(' ' + edition) if edition else ''}"
                base = rnd.uniform(*price_range) * factor
                price = _round_price(base)
                original = _round_price(price * rnd.uniform(1.10, 1.42))
                sku = rnd.randint(10_000_000, 99_999_999)
                sales = int(10 ** rnd.uniform(1.85, 4.65))
                rating = round(rnd.uniform(4.20, 4.95), 1)
                shop = f"{brand}{rnd.choice(SHOP_SUFFIXES)}"
                record = {
                    "id": f"{code}-{sku}",
                    "platform": code,
                    "platform_name": pname,
                    "title": title,
                    "price": price,
                    "original_price": original if original > price else None,
                    "sales": sales,
                    "rating": rating,
                    "shop": shop,
                    "url": self._url(code, sku),
                    "coupon": rnd.choice(COUPONS),
                }
                records.append(record)
                platform_records.append(record)

            # 1) 重复铺货：标题加营销后缀，价格略作浮动
            for _ in range(2):
                src = rnd.choice(platform_records)
                dup = dict(src)
                dup["id"] = f"{src['id']}-dup{rnd.randint(10, 99)}"
                dup["title"] = f"{src['title']} 官方正品"
                dup["price"] = round(src["price"] + rnd.choice([0.0, 1.0, 3.0, 5.0]), 2)
                dup["sales"] = max(1, int(src["sales"] * rnd.uniform(0.55, 1.25)))
                records.append(dup)

            # 2) 字段缺失：无价格，清洗时应被丢弃
            broken = dict(rnd.choice(platform_records))
            broken["id"] = f"{code}-broken-{rnd.randint(1000, 9999)}"
            broken["price"] = rnd.choice([None, "", "面议"])
            records.append(broken)

            # 3) 异常价格：秒杀占位价 / 离谱高价
            outlier_price = rnd.choice([0.01, 88888.0])
            outlier_sku = rnd.randint(10_000_000, 99_999_999)
            records.append(
                {
                    "id": f"{code}-{outlier_sku}",
                    "platform": code,
                    "platform_name": pname,
                    "title": f"【秒杀】{keyword} 福利占位款",
                    "price": outlier_price,
                    "original_price": None,
                    "sales": rnd.randint(1, 50),
                    "rating": None,
                    "shop": f"{pname}福利店",
                    "url": self._url(code, outlier_sku),
                    "coupon": "",
                }
            )

            # 4) 脏格式：货币符号、千分位、HTML 标签、中文销量单位
            src = rnd.choice(platform_records)
            dirty_sku = rnd.randint(10_000_000, 99_999_999)
            records.append(
                {
                    "id": f"{code}-{dirty_sku}",
                    "platform": code,
                    "platform_name": pname,
                    "title": f"<em>{src['title']}</em> 礼盒装",
                    "price": f"¥{src['price']:,.2f}",
                    "original_price": f"￥{src['price'] * 1.3:,.2f}",
                    "sales": f"{rnd.uniform(0.3, 9.9):.1f}万+",
                    "rating": None,
                    "shop": f"{src['shop']}&amp;礼盒装",
                    "url": self._url(code, dirty_sku),
                    "coupon": "赠运费险",
                }
            )

        rnd.shuffle(records)
        return records[: max(limit, 60)]

    @staticmethod
    def _url(code: str, sku: int) -> str:
        if code == "jd":
            return f"https://item.jd.com/{sku}.html"
        if code == "tb":
            return f"https://item.taobao.com/item.htm?id={sku}"
        return f"https://mobile.yangkeduo.com/goods.html?goods_id={sku}"
