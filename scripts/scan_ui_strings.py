"""扫描界面代码里的中文字符串字面量，输出待翻译清单。

用途：做界面多语言化时，先精确知道有多少条、分别在哪里，
而不是靠肉眼数。

用法::

    .venv\\Scripts\\python scripts\\scan_ui_strings.py
    .venv\\Scripts\\python scripts\\scan_ui_strings.py --json testdata/ui_strings.json
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 需要扫描的文件（界面层 + 少量入口提示）
TARGETS = [
    "fanyi/app.py",
    "fanyi/instance.py",
    "fanyi/overlay.py",
    "fanyi/ui/activate.py",
    "fanyi/ui/controller.py",
    "fanyi/ui/history.py",
    "fanyi/ui/history_panel.py",
    "fanyi/ui/hotkey_edit.py",
    "fanyi/ui/main_window.py",
    "fanyi/ui/result_window.py",
    "fanyi/ui/settings_dialog.py",
    "fanyi/ui/tray.py",
    "fanyi/ui/worker.py",
]

#: 含中日韩文字
def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf" for ch in text)


def scan(path: Path) -> list:
    """用 AST 抓字符串字面量，天然排除注释与代码。

    同时记录它是不是 docstring（模块/类/函数的首个语句），
    docstring 不需要翻译。
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            if not has_cjk(node.value):
                continue
            found.append(
                {
                    "file": str(path.relative_to(ROOT)).replace("\\", "/"),
                    "line": node.lineno,
                    "text": node.value,
                }
            )
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描界面待翻译字符串")
    parser.add_argument("--json", help="把结果写成 JSON")
    args = parser.parse_args()

    all_items = []
    print(f"{'文件':<34}{'条数':>6}")
    print("-" * 44)
    for relative in TARGETS:
        path = ROOT / relative
        if not path.exists():
            print(f"{relative:<34}{'(不存在)':>6}")
            continue
        items = scan(path)
        all_items.extend(items)
        print(f"{relative:<34}{len(items):>6}")

    unique = sorted({item["text"] for item in all_items})
    multi_line = [text for text in unique if "\n" in text]

    print("-" * 44)
    print(f"{'合计字面量':<34}{len(all_items):>6}")
    print(f"{'去重后':<34}{len(unique):>6}")
    print(f"{'其中多行文本':<34}{len(multi_line):>6}")

    print("\n===== 去重后的字符串清单 =====")
    for index, text in enumerate(unique, 1):
        preview = text.replace("\n", "\\n")
        if len(preview) > 78:
            preview = preview[:77] + "…"
        print(f"{index:>4}. {preview}")

    if args.json:
        out = Path(args.json)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {"items": all_items, "unique": unique},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n已写出 {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
