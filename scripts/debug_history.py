"""定位历史面板冒烟测试失败的原因。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])

from fanyi.ui.history import HistoryEntry, HistoryStore  # noqa: E402
from fanyi.ui.history_panel import HistoryPanel  # noqa: E402

path = ROOT / "testdata" / "debug_history.json"
path.unlink(missing_ok=True)

store = HistoryStore(path, limit=5)
print("初始条数:", len(store))
store.clear()
print("clear 后:", len(store))

for index in range(3):
    store.add(HistoryEntry(original=f"原文{index}", translation=f"译文{index}", target_lang="zh-Hans"))
print("写入 3 条后:", len(store))
print("文件存在:", path.exists(), "大小:", path.stat().st_size if path.exists() else 0)

reloaded = HistoryStore(path, limit=5)
print("重新载入:", len(reloaded))
for entry in reloaded.all():
    print("   ", repr(entry.original), repr(entry.translation))

panel = HistoryPanel(store.all())
print("表格行数:", panel.table.rowCount())
print("当前行:", panel.table.currentRow())
print("详情长度:", len(panel.detail.toPlainText()))
print("详情前 60 字:", repr(panel.detail.toPlainText()[:60]))
print("包含 [原文]:", "[原文]" in panel.detail.toPlainText())

print()
print("---- 检查 set_limit ----")
store.set_limit(2)
print("set_limit(2) 后条数:", len(store))
print("内存条数属性:", len(store._entries))
