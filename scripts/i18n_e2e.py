"""界面语言切换的端到端验证：从设置界面选语言 → 控制器应用 → 落盘 → 重启后生效。

这一层是"接线"验证：单元测试只覆盖 tr()/trn() 与目录，
这里确认信号真的连上了、配置真的写进去了、下次启动真的读得回来。

用法::

    .venv\\Scripts\\python scripts\\i18n_e2e.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

failures: list = []


def check(condition: bool, title: str, detail: str = "") -> None:
    mark = "OK  " if condition else "FAIL"
    print(f"[{mark}] {title}" + (f"\n       {detail}" if detail else ""), flush=True)
    if not condition:
        failures.append(title)


def main() -> int:
    import tempfile

    # 用独立配置目录，避免污染用户真实设置
    sandbox = Path(tempfile.mkdtemp(prefix="fanyi_i18n_"))
    os.environ["FANYI_HOME"] = str(sandbox)

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])

    from fanyi.config import Config, config_path
    from fanyi.ui import i18n
    from fanyi.ui.controller import AppController
    from fanyi.ui.theme import apply_light_theme

    apply_light_theme(app)

    config = Config()
    controller = AppController(config)
    controller.open_settings()
    app.processEvents()

    window = controller._main_window
    check(window is not None and window.isVisible(), "控制器打开了设置窗口")

    # --- 通过界面控件切换语言，而不是直接调 i18n ---
    check(i18n.current_language() == "zh-Hans", "初始界面语言为简体中文", i18n.current_language())

    index = window.ui_language_combo.findData("en")
    check(index >= 0, "设置界面里有 English 选项")
    window.ui_language_combo.setCurrentIndex(index)
    app.processEvents()

    check(i18n.current_language() == "en", "选择后当前界面语言变为 en", i18n.current_language())
    check(controller.config.ui_language == "en", "配置对象已更新", controller.config.ui_language)

    saved = Config.load(config_path())
    check(saved.ui_language == "en", "已写入配置文件", f"{config_path()}")

    # 界面确实换了语言
    sidebar = [window._sidebar.item(i).text() for i in range(window._sidebar.count())]
    check(sidebar[0] == "Language", "侧栏已切换为英文", str(sidebar))

    # 托盘菜单也换了
    check(
        controller.tray.capture_action.text().startswith("Screenshot translate"),
        "托盘菜单已切换为英文",
        controller.tray.capture_action.text(),
    )
    check("Target:" in controller.tray.icon.toolTip(), "托盘提示已切换", controller.tray.icon.toolTip().replace("\n", " | "))

    # --- 切到繁体 ---
    window.ui_language_combo.setCurrentIndex(window.ui_language_combo.findData("zh-Hant"))
    app.processEvents()
    check(i18n.current_language() == "zh-Hant", "可切换到繁体中文", i18n.current_language())
    sidebar = [window._sidebar.item(i).text() for i in range(window._sidebar.count())]
    check(sidebar[1] == "快捷鍵", "侧栏已切换为繁体", str(sidebar))
    check(
        Config.load(config_path()).ui_language == "zh-Hant",
        "繁体选择已落盘",
    )

    # --- 模拟"重启"：重新读配置并应用 ---
    fresh = Config.load(config_path())
    i18n.set_language("zh-Hans")  # 先改回，验证确实是从配置里读出来的
    i18n.set_language(fresh.ui_language)
    check(i18n.current_language() == "zh-Hant", "重启后按配置恢复繁体", i18n.current_language())

    # --- 无效值兜底 ---
    bad = Config.load(config_path())
    bad.ui_language = "ja"
    bad.save(config_path())
    check(
        not i18n.is_supported(Config.load(config_path()).ui_language),
        "非法语言会被 is_supported 拒绝（启动时回退简体）",
    )

    controller.result_window.hide()
    controller.tray.hide()
    controller.pipeline.close()
    window.close()
    app.processEvents()

    print()
    if failures:
        print(f"未通过 {len(failures)} 项：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("界面语言切换端到端验证通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
