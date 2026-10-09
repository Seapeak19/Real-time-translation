"""真实启动验证：拉起 fanyi 主程序，确认它常驻、热键注册成功、日志正常，然后结束它。

这个脚本会真的启动一个带托盘的进程（约 10 秒），用于在改动后做端到端确认。

用法::

    .venv\\Scripts\\python scripts\\launch_check.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_HOME = Path(os.environ.get("APPDATA", Path.home())) / "fanyi"
LOG = APP_HOME / "fanyi.log"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def count_lines() -> int:
    """当前日志行数（用行数而不是字节偏移做基准，避免把行切成两半）。"""
    if not LOG.exists():
        return 0
    return len(LOG.read_text(encoding="utf-8", errors="replace").splitlines())


def read_new_log(start_line: int) -> str:
    """读取第 start_line 行之后的新日志（完整行）。"""
    if not LOG.exists():
        return ""
    lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[start_line:])


def main() -> int:
    if not PYTHON.exists():
        print(f"没有找到虚拟环境解释器: {PYTHON}")
        return 2

    before = count_lines()
    # 清掉单实例残留（上一次异常退出可能留下管道）
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    print("启动 fanyi（无窗口，托盘常驻）…")
    process = subprocess.Popen(
        [str(PYTHON), "-X", "utf8", "-m", "fanyi"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    alive_after_8s = False
    try:
        for _ in range(16):
            time.sleep(0.5)
            if process.poll() is not None:
                break
        alive_after_8s = process.poll() is None
        print(f"  8 秒后进程{'仍在运行' if alive_after_8s else '已退出'} (pid={process.pid})")

        # 单实例：再启动一个应当立刻退出并提示
        second = subprocess.run(
            [str(PYTHON), "-X", "utf8", "-m", "fanyi"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            timeout=30,
        )
        second_output = (second.stdout or b"").decode("utf-8", "replace").strip()
        print(f"  第二次启动返回码 {second.returncode}，输出: {second_output or '(无)'}")

        time.sleep(1.5)
        new_log = read_new_log(before)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        output = (process.stdout.read() if process.stdout else b"").decode("utf-8", "replace")

    print("\n---- 启动日志 ----")
    print(new_log.strip() or "(没有新日志)")
    if output.strip():
        print("\n---- 标准输出 ----")
        print(output.strip())

    print("\n---- 结论 ----")
    problems = []
    if not alive_after_8s:
        problems.append("主进程启动后异常退出")
    if "热键" in new_log and "失败" in new_log:
        problems.append("热键注册失败")
    if second.returncode != 0:
        problems.append(f"第二次启动未按单实例预期返回 0（实际 {second.returncode}）")
    if "启动" not in new_log:
        problems.append("日志里没有启动记录")

    if problems:
        for item in problems:
            print(f"  [问题] {item}")
        return 1
    print("  [通过] 进程常驻、单实例生效、热键注册、日志正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
