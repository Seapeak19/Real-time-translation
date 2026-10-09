"""开发环境引导：创建 .venv 并安装依赖。

比 PowerShell 版本更可靠（Windows PowerShell 5.1 会用 GBK 解析无 BOM 的脚本，
中文字符容易把脚本读坏）。

用法::

    python scripts/bootstrap_dev.py                      # 默认清华镜像
    python scripts/bootstrap_dev.py --mirror https://pypi.org/simple
    python scripts/bootstrap_dev.py --skip-venv          # 只用当前解释器装依赖
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
DEFAULT_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"


def find_base_python() -> Path:
    """定位用于创建虚拟环境的基础解释器。"""
    candidates = []
    env = os.environ.get("DSH_PYTHON")
    if env:
        candidates.append(Path(env))
    candidates.append(Path(sys.executable))
    for name in ("python", "py"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    raise SystemExit("未找到可用的 Python 解释器，请设置环境变量 DSH_PYTHON")


def venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def run(cmd: list, what: str) -> None:
    print(f"\n>>> {what}\n    {' '.join(str(c) for c in cmd)}", flush=True)
    result = subprocess.run([str(c) for c in cmd])
    if result.returncode != 0:
        raise SystemExit(f"{what} 失败 (exit {result.returncode})")


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化 fanyi 开发环境")
    parser.add_argument("--mirror", default=DEFAULT_MIRROR, help="pip 索引地址")
    parser.add_argument("--skip-venv", action="store_true", help="不创建虚拟环境")
    parser.add_argument("--upgrade-pip", action="store_true", help="顺带升级 pip")
    args = parser.parse_args()

    if args.skip_venv:
        python = Path(sys.executable)
        print(f"使用当前解释器: {python}")
    else:
        base = find_base_python()
        print(f"基础解释器: {base}")
        python = venv_python(VENV)
        if python.exists():
            print(f"复用已有虚拟环境: {VENV}")
        else:
            run([base, "-m", "venv", VENV], "创建虚拟环境")
            if not python.exists():
                raise SystemExit(f"虚拟环境创建失败: {python} 不存在")

    if args.upgrade_pip:
        run([python, "-m", "pip", "install", "--upgrade", "pip",
             "-i", args.mirror, "--disable-pip-version-check"], "升级 pip")

    run(
        [python, "-m", "pip", "install", "-r", ROOT / "requirements.txt",
         "-i", args.mirror, "--disable-pip-version-check"],
        "安装依赖",
    )

    print("\n环境就绪：")
    print(f"  启动工具 : {python} -m fanyi")
    print(f"  自检     : {python} scripts\\selfcheck.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
