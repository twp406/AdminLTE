"""实时采集适配器（最佳努力实现）。

说明：
- 三个平台均存在登录、风控、页面结构变化等限制，适配器使用公开搜索页 +
  尽可能少的请求完成采集，失败时抛出 AdapterError，由上层降级并提示。
- 淘宝 / 拼多多需要登录 Cookie，通过环境变量传入：
      TAOBAO_COOKIE、PDD_COOKIE
- 请遵守目标平台 robots.txt 与服务条款，仅用于学习研究，控制采集频率。
"""

from __future__ import annotations

import gzip
import json
import os
import re
import urllib.parse
import urllib.request
from typing import Any

from .base import AdapterError, BaseAdapter

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _fetch(url: str, headers: dict[str, str] | None = None, timeout: float = 9.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - 统一转换为适配器错误
        raise AdapterError(f"请求失败: {exc}") from exc


def _id_from_url(url: str) -> str:
    query = urllib.parse.urlparse(url if "://" in url else f"https:{url}").query
    params = urllib.parse.parse_qs(query)
    for key in ("id", "goods_id", "itemId"):
        if params.get(key):
            return params[key][0]
    return str(abs(hash(url)) % 10**10)


def _soup_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", "", html)
    return re.sub(r"\s+", " ", text).strip()


class JDAdapter(BaseAdapter):
    code = "jd"
    name = "京东"

    def search(self, keyword: str, limit: int = 40) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode({"keyword": keyword, "enc": "utf-8", "wq": keyword})
        html = _fetch(
            f"https://search.jd.com/Search?{params}",
            {"Referer": "https://www.jd.com/"},
        )
        if "验证" in html and "gl-item" not in html:
            raise AdapterError("京东返回风控验证页，请稍后重试或降低频率")

        chunks = re.split(r'<li[^>]*class="[^"]*gl-item[^"]*"', html)[1:]
        items: list[dict[str, Any]] = []
        for chunk in chunks:
            chunk = chunk.split("</li>", 1)[0]
            sku_m = re.search(r'data-sku="(\d+)"', chunk)
            title_m = re.search(r'class="p-name[^"]*"[\s\S]*?<em>([\s\S]*?)</em>', chunk)
            if not sku_m or not title_m:
                continue
            shop_m = re.search(r'class="p-shop[^"]*"[\s\S]*?<a[^>]*>([\s\S]*?)</a>', chunk)
            commit_m = re.search(r'class="p-commit[^"]*"[\s\S]*?<strong[^>]*>([\s\S]*?)</strong>', chunk)
            items.append(
                {
                    "id": f"jd-{sku_m.group(1)}",
                    "platform": "jd",
                    "platform_name": "京东",
                    "title": _soup_text(title_m.group(1)),
                    "price": None,
                    "original_price": None,
                    "sales": _soup_text(commit_m.group(1)) if commit_m else 0,
                    "rating": None,
                    "shop": _soup_text(shop_m.group(1)) if shop_m else "京东商城",
                    "url": f"https://item.jd.com/{sku_m.group(1)}.html",
                    "coupon": "",
                }
            )
            if len(items) >= limit:
                break

        if not items:
            raise AdapterError("京东搜索页未解析到商品，页面结构可能已变化")

        self._fill_prices(items)
        return [item for item in items if item.get("price")]

    @staticmethod
    def _fill_prices(items: list[dict[str, Any]]) -> None:
        sku_ids = [item["id"].split("-", 1)[1] for item in items]
        ids = ",".join(f"J_{sku}" for sku in sku_ids)
        try:
            raw = _fetch(
                f"https://p.3.cn/prices/mgets?type=1&skuIds={ids}",
                {"Referer": "https://item.jd.com/"},
            )
            prices = {row.get("id", "")[2:]: row.get("p") for row in json.loads(raw)}
        except Exception:  # noqa: BLE001
            return
        for item in items:
            sku = item["id"].split("-", 1)[1]
            value = prices.get(sku)
            try:
                item["price"] = float(value)
            except (TypeError, ValueError):
                continue


class TaobaoAdapter(BaseAdapter):
    code = "tb"
    name = "淘宝"

    def search(self, keyword: str, limit: int = 40) -> list[dict[str, Any]]:
        cookie = os.environ.get("TAOBAO_COOKIE", "").strip()
        if not cookie:
            raise AdapterError("淘宝搜索需要登录态，请设置环境变量 TAOBAO_COOKIE")
        params = urllib.parse.urlencode({"q": keyword, "s": 0, "sort": "default"})
        html = _fetch(
            f"https://s.taobao.com/search?{params}",
            {"Cookie": cookie, "Referer": "https://www.taobao.com/"},
        )
        if "请登录" in html or "login.taobao.com" in html:
            raise AdapterError("淘宝登录态失效，请更新 TAOBAO_COOKIE")

        match = re.search(r"g_page_config\s*=\s*(\{.*?\});", html, re.S)
        if not match:
            raise AdapterError("淘宝搜索页未找到商品数据（可能触发风控）")
        try:
            config = json.loads(match.group(1))
            auctions = config["mods"]["itemlist"]["data"]["auctions"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise AdapterError("淘宝商品数据结构变更，解析失败") from exc

        items: list[dict[str, Any]] = []
        for row in auctions[:limit]:
            url = row.get("detail_url") or ""
            if url.startswith("//"):
                url = "https:" + url
            items.append(
                {
                    "id": f"tb-{row.get('nid') or _id_from_url(url)}",
                    "platform": "tb",
                    "platform_name": "淘宝",
                    "title": _soup_text(str(row.get("raw_title", ""))),
                    "price": row.get("view_price"),
                    "original_price": row.get("reserve_price"),
                    "sales": row.get("view_sales", 0),
                    "rating": None,
                    "shop": row.get("nick", "淘宝店铺"),
                    "url": url,
                    "coupon": "",
                }
            )
        return [item for item in items if item.get("title")]


class PDDAdapter(BaseAdapter):
    code = "pdd"
    name = "拼多多"

    def search(self, keyword: str, limit: int = 40) -> list[dict[str, Any]]:
        cookie = os.environ.get("PDD_COOKIE", "").strip()
        if not cookie:
            raise AdapterError("拼多多搜索需要登录态，请设置环境变量 PDD_COOKIE")
        params = urllib.parse.urlencode({"search_key": keyword})
        html = _fetch(
            f"https://mobile.yangkeduo.com/search_result.html?{params}",
            {"Cookie": cookie, "Referer": "https://mobile.yangkeduo.com/"},
        )
        payload = self._extract_json(html)
        if not payload:
            raise AdapterError("拼多多页面未找到商品数据（可能触发风控或结构变更）")

        rows = self._find_goods(payload)
        items: list[dict[str, Any]] = []
        for row in rows[:limit]:
            gid = str(row.get("goods_id") or row.get("goodsId") or row.get("goodsID") or "")
            title = row.get("goods_name") or row.get("goodsName") or row.get("title")
            if not gid or not title:
                continue
            price = row.get("price") or row.get("min_on_sale_group_price") or row.get("group_price")
            items.append(
                {
                    "id": f"pdd-{gid}",
                    "platform": "pdd",
                    "platform_name": "拼多多",
                    "title": _soup_text(str(title)),
                    "price": self._to_yuan(price),
                    "original_price": None,
                    "sales": row.get("sales_tip") or row.get("salesTip") or 0,
                    "rating": None,
                    "shop": row.get("mall_name") or row.get("mallName") or "拼多多店铺",
                    "url": f"https://mobile.yangkeduo.com/goods.html?goods_id={gid}",
                    "coupon": "",
                }
            )
        return [item for item in items if item.get("price")]

    @staticmethod
    def _extract_json(html: str) -> Any:
        for pattern in (r"window\.rawData\s*=\s*(\{.*?\});", r'id="__NEXT_DATA__"[^>]*>(\{.*?\})<'):
            match = re.search(pattern, html, re.S)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
        return None

    def _find_goods(self, node: Any, found: list[dict] | None = None) -> list[dict]:
        found = found if found is not None else []
        if isinstance(node, dict):
            keys = set(node)
            if keys & {"goods_name", "goodsName"} and keys & {"goods_id", "goodsId", "price"}:
                found.append(node)
            for value in node.values():
                self._find_goods(value, found)
        elif isinstance(node, list):
            for value in node:
                self._find_goods(value, found)
        return found

    @staticmethod
    def _to_yuan(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return round(number / 100, 2) if number >= 10_000 else round(number, 2)
