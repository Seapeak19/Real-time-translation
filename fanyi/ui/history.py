"""翻译历史：内存 + 磁盘持久化。"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class HistoryEntry:
    """一条翻译记录。"""

    original: str
    translation: str
    source_lang: str = "auto"
    target_lang: str = ""
    provider: str = ""
    elapsed: float = 0.0
    timestamp: float = field(default_factory=time.time)

    @property
    def time_text(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> Optional["HistoryEntry"]:
        if not isinstance(raw, dict):
            return None
        original = raw.get("original")
        translation = raw.get("translation")
        if not isinstance(original, str) or not isinstance(translation, str):
            return None
        return cls(
            original=original,
            translation=translation,
            source_lang=str(raw.get("source_lang") or "auto"),
            target_lang=str(raw.get("target_lang") or ""),
            provider=str(raw.get("provider") or ""),
            elapsed=float(raw.get("elapsed") or 0.0),
            timestamp=float(raw.get("timestamp") or time.time()),
        )


class HistoryStore:
    """按条数上限保存历史，写盘走临时文件替换，避免半截文件。"""

    def __init__(self, path: Path, limit: int = 200) -> None:
        self.path = Path(path)
        self.limit = max(10, limit)
        self._lock = threading.Lock()
        self._entries: List[HistoryEntry] = []
        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        items = raw.get("entries") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return
        entries = []
        for item in items:
            entry = HistoryEntry.from_dict(item)
            if entry is not None:
                entries.append(entry)
        self._entries = entries[-self.limit :]

    def add(self, entry: HistoryEntry) -> None:
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self.limit:
                self._entries = self._entries[-self.limit :]
        self.flush()

    def all(self) -> List[HistoryEntry]:
        with self._lock:
            return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def clear(self) -> int:
        with self._lock:
            count = len(self._entries)
            self._entries = []
        self.flush()
        return count

    def set_limit(self, limit: int) -> None:
        """调整条数上限；调小时立即裁掉超出的旧记录。"""
        new_limit = max(10, int(limit))
        with self._lock:
            self.limit = new_limit
            if len(self._entries) > new_limit:
                self._entries = self._entries[-new_limit:]
                changed = True
            else:
                changed = False
        if changed:
            self.flush()

    def flush(self) -> None:
        with self._lock:
            payload = {"entries": [e.to_dict() for e in self._entries]}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass


__all__ = ["HistoryEntry", "HistoryStore"]
