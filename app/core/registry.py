"""通用插件注册表。

V1.0 用它统一注册三类扩展点：
  - 测试设计策略（DesignStrategy）
  - 导出器（Exporter）
  - 文档解析器（DocumentParser）

后续追加判定表/因果图/正交实验策略、XMind/CSV 导出器时，
只需在对应模块写一个类 + 装饰器注册，主干代码零改动。
"""
from __future__ import annotations

from typing import Callable, Generic, Iterator, TypeVar

from app.core.exceptions import NotFoundError

T = TypeVar("T")


class Registry(Generic[T]):
    """名称 -> 实现 的注册表。"""

    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._items: dict[str, T] = {}
        self._meta: dict[str, dict] = {}

    @property
    def kind(self) -> str:
        return self._kind

    def register(self, name: str, item: T, *, meta: dict | None = None, override: bool = False) -> T:
        if name in self._items and not override:
            raise ValueError(f"{self._kind} 已注册：{name}")
        self._items[name] = item
        self._meta[name] = meta or {}
        return item

    def decorator(self, name: str, *, meta: dict | None = None, override: bool = False) -> Callable[[T], T]:
        def wrapper(item: T) -> T:
            self.register(name, item, meta=meta, override=override)
            return item

        return wrapper

    def get(self, name: str) -> T:
        try:
            return self._items[name]
        except KeyError as exc:
            raise NotFoundError(
                f"未知的 {self._kind}：{name}，可选值：{', '.join(self.names()) or '(空)'}",
                detail={"kind": self._kind, "name": name, "available": self.names()},
            ) from exc

    def try_get(self, name: str) -> T | None:
        return self._items.get(name)

    def names(self) -> list[str]:
        return sorted(self._items)

    def meta(self, name: str) -> dict:
        return self._meta.get(name, {})

    def items(self) -> Iterator[tuple[str, T]]:
        for name in self.names():
            yield name, self._items[name]

    def __contains__(self, name: object) -> bool:
        return name in self._items

    def __len__(self) -> int:
        return len(self._items)