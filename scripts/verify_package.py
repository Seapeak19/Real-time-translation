"""验证打包产物：真的启动 dist 里的 exe，确认它能常驻、能注册热键、能识别并翻译。

用日志文件作为主要证据来源——打包时 ``console=False``，exe 没有控制台输出，
所以"程序是否真的跑起来了"只能看 %APPDATA%\\fanyi\\fanyi.log。

用法::

    .venv\\Scripts\\python scripts\\verify_package.py
    .venv\\Scripts\\python scripts\\verify_package.py --dir dist\\翻译
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_HOME = Path(os.environ.get("APPDATA", Path.home())) / "fanyi"
LOG = APP_HOME / "fanyi.log"

# 版本号从代码里读，避免每次发版都要手改这个脚本
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    from fanyi.config import APP_TITLE, APP_VERSION as EXPECTED_VERSION
except Exception:  # pragma: no cover - 只在源码结构异常时发生
    APP_TITLE, EXPECTED_VERSION = "翻译", ""

failures: list = []


def check(condition: bool, title: str, detail: str = "") -> None:
    mark = "OK  " if condition else "FAIL"
    print(f"[{mark}] {title}" + (f"\n       {detail}" if detail else ""), flush=True)
    if not condition:
        failures.append(title)


def count_lines() -> int:
    """当前日志行数（以行数而非字节偏移作为"新内容"的基准，避免截断半行）。"""
    if not LOG.exists():
        return 0
    return len(LOG.read_text(encoding="utf-8", errors="replace").splitlines())


def log_since(start_line: int) -> str:
    """读取第 start_line 行之后的新日志（完整行）。"""
    if not LOG.exists():
        return ""
    lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[start_line:])


def main() -> int:
    parser = argparse.ArgumentParser(description="验证打包产物")
    parser.add_argument("--dir", default=str(ROOT / "dist" / "翻译"), help="打包输出目录")
    parser.add_argument("--timeout", type=int, default=90, help="等待启动的秒数")
    args = parser.parse_args()

    out_dir = Path(args.dir)
    exe = out_dir / "翻译.exe"
    internal = out_dir / "_internal"

    print("=" * 72)
    print("  打包产物验证")
    print("=" * 72)

    if not exe.exists():
        print(f"找不到 {exe}\n请先执行: .venv\\Scripts\\pyinstaller --noconfirm 翻译.spec")
        return 2

    # --- 1. 产物结构 ---
    total = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file())
    check(True, "可执行文件存在", f"{exe}  ({exe.stat().st_size / 1024 / 1024:.1f} MB)")
    check(internal.is_dir(), "包含 _internal 运行库目录")
    check(True, "发布目录总体积", f"{total / 1024 / 1024:.1f} MB")

    models = list((internal / "rapidocr_onnxruntime" / "models").glob("*.onnx"))
    check(len(models) >= 3, "OCR 模型已随包分发", f"{len(models)} 个: " + ", ".join(m.name for m in models))
    check(
        any("rec" in m.name for m in models) and any("det" in m.name for m in models),
        "检测与识别模型都在",
    )
    check((internal / "onnxruntime").is_dir(), "ONNX Runtime 动态库已收集")

    # --- 2. 真的启动它 ---
    before = count_lines()
    print("\n启动打包后的 exe…")
    process = subprocess.Popen([str(exe)], cwd=str(out_dir))

    started_ok = False
    deadline = time.time() + args.timeout
    try:
        while time.time() < deadline:
            time.sleep(1.0)
            if process.poll() is not None:
                break
            text = log_since(before)
            # 等到"控制器装配完成"并且热键那条也写完为止
            if "应用已启动" in text and "RapidOCR 模型加载完成" in text and "热键" in text:
                started_ok = True
                break
        time.sleep(0.5)  # 留一点时间让最后几行日志落盘
        alive = process.poll() is None
        new_log = log_since(before)

        check(alive, "exe 启动后保持常驻（托盘程序不应自己退出）")
        # 版本号从源码读取，发版后不用再改这里
        started_line = f"{APP_TITLE} {EXPECTED_VERSION} 启动" if EXPECTED_VERSION else "启动，日志:"
        check(started_line in new_log, "写入启动日志", _line_with(new_log, "启动，日志:"))
        check("全局热键已生效" in new_log, "注册全局热键", _line_with(new_log, "全局热键"))
        check("应用已启动" in new_log, "控制器完成装配")
        check("RapidOCR 模型加载完成" in new_log, "OCR 模型在打包环境中加载成功", _line_with(new_log, "RapidOCR"))

        # --- 3. 单实例：再启一个应当立刻退出 ---
        second = subprocess.Popen([str(exe)], cwd=str(out_dir))
        try:
            code = second.wait(timeout=40)
            check(code == 0, "第二个实例自动退出（单实例生效）", f"退出码 {code}")
        except subprocess.TimeoutExpired:
            second.kill()
            check(False, "第二个实例自动退出（单实例生效）", "第二个实例 40 秒内没有退出")
        finally:
            if second.poll() is None:
                second.kill()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    print("\n---- 本次启动的日志 ----")
    print(new_log.strip() or "(无新日志)")

    print("\n" + "=" * 72)
    if failures:
        print(f"  未通过 {len(failures)} 项：")
        for item in failures:
            print(f"    - {item}")
        print("=" * 72)
        return 1
    print("  打包产物验证通过：可独立运行、常驻、热键生效、OCR 就绪、单实例正常")
    print("=" * 72)
    return 0


def _line_with(text: str, keyword: str) -> str:
    for line in text.splitlines():
        if keyword in line:
            return line.strip()
    return ""


if __name__ == "__main__":
    sys.exit(main())
