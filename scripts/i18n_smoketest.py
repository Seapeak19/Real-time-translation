"""界面语言检查：各界面语言下检查各控件文案是否漏翻。

用法::

    .venv\\Scripts\\python scripts\\i18n_smoketest.py

会构造真实的设置窗口（可能触发配置写入），因此先把 ``FANYI_HOME``
指向临时目录，避免覆盖用户的热键等设置。
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_SANDBOX = Path(tempfile.mkdtemp(prefix="fanyi_i18n_smoke_"))
os.environ["FANYI_HOME"] = str(_SANDBOX)
atexit.register(lambda: shutil.rmtree(_SANDBOX, ignore_errors=True))

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

#: 判定"是否仍含中文"，用于发现漏翻
def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    from fanyi.config import Config
    from fanyi.ui import i18n
    from fanyi.ui.i18n import set_language
    from fanyi.ui.main_window import MainWindow
    from fanyi.ui.theme import apply_light_theme

    apply_light_theme(app)

    window = MainWindow(Config())
    window.show()
    app.processEvents()

    problems = []
    for language in ("zh-Hans", "en"):
        set_language(language)
        window.retranslate()
        app.processEvents()

        sidebar = [window._sidebar.item(i).text() for i in range(window._sidebar.count())]
        targets = [window.target_combo.itemText(i) for i in range(window.target_combo.count())]
        engines = [window.engine_list.item(i).text() for i in range(window.engine_list.count())]
        ocr = [window.ocr_combo.itemText(i) for i in range(window.ocr_combo.count())]
        ui_langs = [window.ui_language_combo.itemText(i) for i in range(window.ui_language_combo.count())]
        status = window.status_label.text()

        print(f"===== {language} =====")
        print(f"  窗口标题    : {window.windowTitle()}")
        print(f"  侧栏        : {sidebar}")
        print(f"  界面语言下拉: {ui_langs}")
        print(f"  目标语言下拉: {targets}")
        print(f"  OCR 下拉    : {ocr}")
        print(f"  引擎列表    : {engines}")
        print(f"  状态栏      : {status}")

        if language == "en":
            # 英文界面下这些位置不该再出现中文
            for name, values in (
                ("侧栏", sidebar),
                ("目标语言下拉", targets),
                ("引擎列表", engines),
                ("OCR 下拉", ocr),
                ("状态栏", [status]),
            ):
                for value in values:
                    # 语言名本身在英文界面下应是英文；数值单位除外
                    if has_cjk(value):
                        problems.append(f"[en] {name} 仍是中文: {value!r}")

    # 界面语言下拉在各语言下都应显示对应写法
    set_language("en")
    window.retranslate()
    app.processEvents()
    ui_langs_en = [window.ui_language_combo.itemText(i) for i in range(window.ui_language_combo.count())]
    if not all(not has_cjk(item) for item in ui_langs_en):
        problems.append(f"[en] 界面语言下拉含中文: {ui_langs_en}")

    # 繁体界面语言已移除：下拉里不该再出现繁体选项（简体的「简体中文」除外）
    set_language("zh-Hans")
    window.retranslate()
    app.processEvents()
    ui_langs_zh = [window.ui_language_combo.itemText(i) for i in range(window.ui_language_combo.count())]
    if any("繁體" in item or "繁体" in item for item in ui_langs_zh):
        problems.append(f"[zh-Hans] 界面语言下拉仍有繁体选项: {ui_langs_zh}")

    # 下拉选中项在切换语言后不应丢失
    set_language("zh-Hans")
    window.retranslate()
    from fanyi.ui.main_window import _select_data

    _select_data(window.target_combo, "en")
    set_language("en")
    window.retranslate()
    app.processEvents()
    if window.target_combo.currentData() != "en":
        problems.append(f"切换界面语言后目标语言选中项丢失: {window.target_combo.currentData()}")

    window.close()
    app.processEvents()

    print()
    if problems:
        print(f"发现 {len(problems)} 个问题：")
        for item in problems:
            print(f"  - {item}")
        return 1
    print(f"{len(i18n.UI_LANGUAGES)} 种界面语言下文案检查通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
