"""采集适配器接口。"""

from __future__ import annotations

from typing import Any


class AdapterError(RuntimeError):
    """单个平台采集失败。"""


class BaseAdapter:
    code: str = ""
    name: str = ""

    def search(self, keyword: str, limit: int = 40) -> list[dict[str, Any]]:
        """返回原始记录列表（字段允许脏数据，由清洗层统一处理）。"""
        raise NotImplementedError
