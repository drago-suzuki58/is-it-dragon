import json
from pathlib import Path


class DiskCache:
    """キーごとに JSON ファイルを1つ置く。"""

    def __init__(self, directory: Path):
        self._dir = directory

    def get(self, key: str) -> dict | None:
        path = self._dir / f"{key}.json"
        return json.loads(path.read_text()) if path.exists() else None

    def set(self, key: str, value: dict) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / f"{key}.json").write_text(json.dumps(value, ensure_ascii=False))
