from collections import OrderedDict


class MemoryCache:
    """件数上限付きの LRU。"""

    def __init__(self, max_items: int = 1024):
        self._items: OrderedDict[str, dict] = OrderedDict()
        self._max_items = max_items

    def get(self, key: str) -> dict | None:
        if key not in self._items:
            return None
        self._items.move_to_end(key)
        return self._items[key]

    def set(self, key: str, value: dict) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self._max_items:
            self._items.popitem(last=False)
