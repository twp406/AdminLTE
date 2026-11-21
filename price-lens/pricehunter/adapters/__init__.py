"""平台采集适配器。"""

from .base import AdapterError, BaseAdapter
from .demo import DemoAdapter
from .live import JDAdapter, PDDAdapter, TaobaoAdapter

__all__ = [
    "AdapterError",
    "BaseAdapter",
    "DemoAdapter",
    "JDAdapter",
    "TaobaoAdapter",
    "PDDAdapter",
]
