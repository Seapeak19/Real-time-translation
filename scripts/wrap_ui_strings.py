"""把界面代码里的中文字符串自动包上 ``tr()``。

为什么用 AST 而不是正则：需要精确排除 docstring、f-string 片段、
``tr()`` 内部已有的键、以及样式表里的中文。正则做不好这件事，
漏改一处就会在英文界面下露出中文。

用法::

    .venv\\Scripts\\python scripts\\wrap_ui_strings.py --check    # 只看会改哪些，不写文件
    .venv\\Scripts\\python scripts\\wrap_ui_strings.py            # 实际改写
    .venv\\Scripts\\python scripts\\wrap_ui_strings.py --file fanyi/ui/tray.py
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TARGETS = [
    "fanyi/app.py",
    "fanyi/instance.py",
    "fanyi/overlay.py",
    "fanyi/ui/activate.py",
    "fanyi/ui/controller.py",
    "fanyi/ui/history_panel.py",
    "fanyi/ui/hotkey_edit.py",
    "fanyi/ui/main_window.py",
    "fanyi/ui/result_window.py",
    "fanyi/ui/tray.py",
]


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf" for ch in text)


def is_stylesheet(text: str) -> bool:
    """样式表里可能出现中文注释，不该被翻译。"""
    markers = ("background:", "border:", "color:", "QWidget", "font-", "padding:")
    return sum(marker in text for marker in markers) >= 2


def collect_docstrings(tree: ast.Module) -> set:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    ids.add(id(body[0].value))
    return ids


def collect_unsafe_strings(tree: ast.Module, source: str) -> set:
    """收集**不能**安全自动包裹的字符串。

    三类必须跳过，否则会写出错误代码或错误语义：

    1. ``f"..."`` —— ``ast`` 只把 f-string 的字面量部分建成常量节点，
       包起来会得到 ``tr(f"引擎：{x}")``：语法合法，但查字典时用的是
       含花括号的模板，永远匹配不到。这类需要人工整句改成
       ``trn("引擎：{engine}", engine=x)``。
    2. 隐式拼接（``"a" "b"``）—— 各片段是独立节点，只包住一部分会让
       这条文案无法完整翻译。
    3. 常量折叠（相邻字面量被编译器合并成一个节点）—— 节点位置覆盖了
       两个字符串字面量，取出的源码片段不是合法表达式，插进 ``tr(...)``
       会造成语法错误。

    判断方式：取节点的源码片段，引号数量超过一对就说明它覆盖了多个字面量。
    """
    ids = set()

    # 1) f-string 内的字面量片段
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    ids.add(id(value))

    # 2) 与 3) 用源码片段里的引号数量判断
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in ids:
            continue
        segment = ast.get_source_segment(source, node)
        if segment is None:
            continue
        if segment.count('"') > 2 or segment.count("'") > 2:
            ids.add(id(node))
    return ids


def collect_tr_keys(tree: ast.Module) -> set:
    """已经在 tr(...) / trn(...) 内部的字符串，不要再包一层。"""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("tr", "trn", "_"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        ids.add(id(arg))
    return ids


#: 日志/异常文案只给开发者看，不进翻译目录
_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}


def collect_log_strings(tree: ast.Module) -> set:
    """收集 logger.xxx("...") 里的字符串，这些不该被翻译。"""
    ids = set()

    def mark(node) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                ids.add(id(child))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in _LOG_METHODS:
                for arg in node.args:
                    mark(arg)
                for keyword in node.keywords:
                    mark(keyword.value)
    return ids


def find_replacements(path: Path) -> list:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    skip = (
        collect_docstrings(tree)
        | collect_tr_keys(tree)
        | collect_log_strings(tree)
        | collect_unsafe_strings(tree, source)
    )

    edits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in skip:
            continue
        if not has_cjk(node.value):
            continue
        if is_stylesheet(node.value):
            continue
        # 已有相邻字符串拼接的位置也跳过（跨行文案，边界容易判断错）
        edits.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, node.value))

    return source, edits


def _char_offset(line_text: str, byte_col: int) -> int:
    """把 ``ast`` 给的 **UTF-8 字节列偏移** 换算成 **字符列偏移**。

    这是本脚本最容易踩的坑：``col_offset`` / ``end_col_offset`` 按 UTF-8
    字节计数，而中文一个字占 3 字节。直接拿去切 Python 字符串（按字符）
    会整体错位，写出的代码变成 ``QAction(tr("截图翻译", self.m)enu)``
    这种语法错误——看起来像"随机"损坏，实际是偏移量算错。
    """
    encoded = line_text.encode("utf-8")
    return len(encoded[:byte_col].decode("utf-8", errors="replace"))


def apply_edits(source: str, edits: list) -> str:
    """按位置从后往前替换，避免前面的改写影响后面的偏移。"""
    lines = source.splitlines(keepends=True)

    # 每行起始的绝对字符偏移
    line_starts = []
    running = 0
    for line in lines:
        line_starts.append(running)
        running += len(line)

    def absolute(lineno: int, byte_col: int) -> int:
        index = min(max(lineno - 1, 0), len(lines) - 1)
        return line_starts[index] + _char_offset(lines[index], byte_col)

    absolute_edits = []
    for lineno, col, end_lineno, end_col, _text in edits:
        start = absolute(lineno, col)
        end = absolute(end_lineno, end_col)
        if end <= start:
            continue
        raw = source[start:end]
        absolute_edits.append((start, end, raw))

    # 校验：片段必须恰好是一个字符串字面量，否则宁可跳过也不要写坏代码
    validated = []
    for start, end, raw in absolute_edits:
        stripped = raw.strip()
        if not stripped:
            continue
        first, last = stripped[0], stripped[-1]
        paired = (first == last and first in "\"'") or (
            stripped.startswith('"""') and stripped.endswith('"""')
        ) or (stripped.startswith("'''") and stripped.endswith("'''"))
        if not paired:
            print(f"    [跳过] 片段不是完整字面量: {stripped[:60]!r}")
            continue
        validated.append((start, end, raw))

    validated.sort(key=lambda item: item[0], reverse=True)
    result = source
    for start, end, raw in validated:
        result = result[:start] + f"tr({raw})" + result[end:]
    return result


def _import_insert_line(source: str) -> int:
    """返回"最后一个顶层 import 结束"的行号（1 起，0 表示没有 import）。

    用 AST 而不是逐行扫描：函数体内的局部 import 同样以 ``from `` 开头，
    逐行判断会把新 import 插进函数体里，产生 IndentationError。
    多行 import 的括号块同理。
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0

    end_line = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            end_line = max(end_line, node.end_lineno or node.lineno)
    return end_line


def ensure_import(source: str, path: Path) -> str:
    """补上正确的 ``tr`` 导入。

    相对层级按文件在包里的深度算：

    * ``fanyi/app.py``            → ``from .ui.i18n import tr``
    * ``fanyi/ui/tray.py``        → ``from .i18n import tr``
    * ``fanyi/ui/sub/x.py``       → ``from ..i18n import tr``
    """
    if "import tr" in source:
        return source

    relative = path.relative_to(ROOT)
    depth = len(relative.parts) - 1  # fanyi/app.py → 1；fanyi/ui/tray.py → 2

    if depth == 1:
        statement = "from .ui.i18n import tr"
    else:
        statement = f"from {'.' * (depth - 1)}i18n import tr"

    lines = source.splitlines(keepends=True)
    index = _import_insert_line(source)
    if index <= 0:
        return source
    lines.insert(index, statement + "\n")
    return "".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="给界面字符串包上 tr()")
    parser.add_argument("--check", action="store_true", help="只报告，不写文件")
    parser.add_argument("--file", help="只处理指定文件")
    args = parser.parse_args()

    targets = [args.file] if args.file else TARGETS
    grand_total = 0

    for relative in targets:
        path = ROOT / relative
        if not path.exists():
            print(f"跳过（不存在）: {relative}")
            continue

        source, edits = find_replacements(path)
        grand_total += len(edits)
        print(f"{relative:<34} 待包裹 {len(edits):>4} 处")

        if args.check or not edits:
            for _lineno, _col, _el, _ec, text in edits[:3]:
                preview = text.replace("\n", "\\n")
                print(f"      例: {preview[:70]}")
            continue

        updated = apply_edits(source, edits)
        updated = ensure_import(updated, path)
        path.write_text(updated, encoding="utf-8")

    print("-" * 44)
    print(f"合计 {grand_total} 处")
    if args.check:
        print("（--check 模式，未写入文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
