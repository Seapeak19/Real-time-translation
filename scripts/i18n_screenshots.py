"""把设置窗口在三种界面语言下各渲染一遍，用于目视确认。

输出到 testdata/i18n_<lang>.png。

用法::

    .venv\\Scripts\\python scripts\\i18n_screenshots.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

OUT = ROOT / "testdata"


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])

    from fanyi.config import Config
    from fanyi.ui.i18n import set_language
    from fanyi.ui.main_window import MainWindow
    from fanyi.ui.theme import apply_light_theme

    apply_light_theme(app)
    OUT.mkdir(exist_ok=True)

    window = MainWindow(Config())
    window.resize(960, 660)
    window.show()
    app.processEvents()

    pages = ["语言", "快捷键", "识别OCR", "翻译", "界面"]
    for language in ("zh-Hans", "zh-Hant", "en"):
        set_language(language)
        window.retranslate()
        app.processEvents()

        # 每页渲染一张；只存语言页 + 快捷键页，够看清是否漏翻
        for index in (0, 1):
            window._sidebar.setCurrentRow(index)
            app.processEvents()
            path = OUT / f"i18n_{language}_p{index}.png"
            window.grab().save(str(path))
            print(f"  已保存 {path.relative_to(ROOT)}")

    window.close()
    app.processEvents()
    print("\n打开 testdata/i18n_*.png 确认：三种语言下都不应出现其它语言残留")
    return 0


if __name__ == "__main__":
    sys.exit(main())
