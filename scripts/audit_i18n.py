"""找出界面代码里尚未多语言化的中文字符串。

改写脚本会跳过三类字符串（f-string、隐式拼接、常量折叠），
这个脚本把它们列出来，用于人工补齐 ``trn(...)``。同时它也是
回归检查：修完之后这里应当为空。

用法::

    .venv\\Scripts\\python scripts\\audit_i18n.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def is_stylesheet(text: str) -> bool:
    markers = ("background:", "border:", "color:", "QWidget", "font-", "padding:")
    return sum(marker in text for marker in markers) >= 2


LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}


def audit(path: Path) -> list:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # 允许清单：docstring、日志、样式表
    allowed = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    allowed.add(id(body[0].value))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in LOG_METHODS:
                for child in ast.walk(node):
                    if isinstance(child, ast.Constant) and isinstance(child.value, str):
                        allowed.add(id(child))
            # setProperty("_i18n", "键") 里的字符串是翻译键，本身不需要再包 tr()
            if node.func.attr == "setProperty":
                for child in ast.walk(node):
                    if isinstance(child, ast.Constant) and isinstance(child.value, str):
                        allowed.add(id(child))

    # tr(...) / trn(...) 的参数与字符串列表里的翻译键都算已处理
    wrapped = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("tr", "trn"):
                for arg in node.args:
                    for child in ast.walk(arg):
                        if isinstance(child, ast.Constant) and isinstance(child.value, str):
                            wrapped.add(id(child))

    # 模块级常量表里的翻译键也已在别处使用（例如 _SIDEBAR_KEYS 会被 tr() 消费），
    # 这里把"赋值给带 KEY/KEYS 名字的常量"里的中文视为已处理
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                name = getattr(target, "id", "")
                if name.endswith("_KEYS") or name.endswith("_KEYS_"):
                    for child in ast.walk(node.value):
                        if isinstance(child, ast.Constant) and isinstance(child.value, str):
                            wrapped.add(id(child))

    problems = []

    # 预先建立"字符串 → 所属顶层赋值语句"的映射，
    # 用于支持把 noqa: i18n 写在多行常量表的第一行
    owner_assignments: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if value is None:
                continue
            for child in ast.walk(value):
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    owner_assignments.setdefault(id(child), []).append(node)

    # 1) 未包裹的普通字符串
    source_lines = source.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in allowed or id(node) in wrapped:
            continue
        if not has_cjk(node.value):
            continue
        if is_stylesheet(node.value):
            continue
        # 带 noqa: i18n 的行表示有意不翻译（例如托盘图标上的标识字）。
        # 常量表常常写成多行元组，标记留在第一行，因此这里按**语句**判断：
        # 只要该字符串所属的顶层赋值语句的起始行带标记，整块都视为有意保留。
        for owner in owner_assignments.get(id(node), ()):
            owner_line = (
                source_lines[owner.lineno - 1] if owner.lineno <= len(source_lines) else ""
            )
            if "noqa: i18n" in owner_line:
                break
        else:
            line = source_lines[node.lineno - 1] if node.lineno <= len(source_lines) else ""
            if "noqa: i18n" in line:
                continue
            segment = ast.get_source_segment(source, node)
            if segment and ("tr(" in segment or "trn(" in segment):
                continue
            problems.append((node.lineno, "未包裹", node.value))

    # 2) f-string 里的中文（需要人工改成 trn）
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            literal = "".join(
                value.value
                for value in node.values
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            )
            if has_cjk(literal):
                segment = ast.get_source_segment(source, node) or ""
                problems.append((node.lineno, "f-string", segment))

    # 3) 主设置窗口里"缺 _i18n 标记"的控件
    #
    # 这一条是补盲区：只包了 tr() 还不够——切换界面语言时，
    # retranslate() 是靠控件上的 _i18n 属性找到并改写文案的。
    # 漏了标记的控件在英文界面下会一直显示中文，而"是否包了 tr"
    # 这类检查完全看不出来（曾经就漏掉了「开始截图翻译」「关闭窗口」）。
    if path.name == "main_window.py":
        tagged_names = _tagged_widget_names(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id not in ("QPushButton", "QLabel", "QCheckBox", "QGroupBox"):
                continue
            # 只关心文案是 tr(...) 的构造
            if not (node.args and isinstance(node.args[0], ast.Call)):
                continue
            inner = node.args[0]
            if not (isinstance(inner.func, ast.Name) and inner.func.id == "tr"):
                continue
            key = inner.args[0].value if inner.args and isinstance(inner.args[0], ast.Constant) else ""
            if _is_tagged(tree, node, tagged_names):
                continue
            problems.append((node.lineno, "缺 _i18n 标记", key))

    problems.sort(key=lambda item: item[0])
    return problems


def _tagged_widget_names(tree: ast.Module) -> set:
    """收集调用过 setProperty("_i18n", ...) 的对象名（含局部变量）。"""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "setProperty" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and first.value == "_i18n":
                    target = node.func.value
                    if isinstance(target, ast.Name):
                        names.add(target.id)
                    elif isinstance(target, ast.Attribute):
                        names.add(target.attr)
    return names


def _is_tagged(tree: ast.Module, call_node: ast.Call, tagged_names: set) -> bool:
    """判断这个控件构造之后有没有被 ``setProperty("_i18n", ...)`` 标记过。

    先找出这次构造被赋给了谁，再看那个名字在不在标记集合里：

    * ``x = QPushButton(tr("..."))``           → 变量名 x
    * ``self.x = QLabel(tr("..."))``           → 属性名 x
    * ``parent.addWidget(QLabel(tr("...")))``  → 行内写法，用临时变量 _label
    """
    if not tagged_names:
        return False

    # 赋值形式：value 正好是这个调用
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and node.value is call_node:
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in tagged_names:
                    return True
                if isinstance(target, ast.Attribute) and target.attr in tagged_names:
                    return True

    # 行内形式：xxx.addWidget(<这个调用>)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "addWidget" and call_node in node.args:
                return "_label" in tagged_names

    return False


def main() -> int:
    total = 0
    for relative in TARGETS:
        path = ROOT / relative
        if not path.exists():
            continue
        problems = audit(path)
        if not problems:
            print(f"{relative:<34} 干净")
            continue
        print(f"{relative:<34} {len(problems)} 处待处理")
        for lineno, kind, text in problems:
            preview = text.replace("\n", "\\n")
            if len(preview) > 88:
                preview = preview[:87] + "…"
            print(f"    L{lineno:<4} [{kind}] {preview}")
        total += len(problems)

    print("-" * 60)
    if total:
        print(f"合计 {total} 处仍需人工多语言化")
        return 1
    print("界面代码已全部完成多语言化 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
