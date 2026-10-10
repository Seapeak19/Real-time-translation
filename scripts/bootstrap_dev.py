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

#: 依次尝试的 pip 索引。
#:
#: 为什么不只用一家：镜像会单独对某个包返回 403/404 或临时失联
#: （实测清华镜像对 keyboard 持续 403，而阿里云与官方源正常），
#: 而安装是在循环里逐个装包的，任何一个包拉不下来整次安装就失败，
#: 新用户第一步就卡住。多备几家并自动回退，比让用户自己排查划算得多。
DEFAULT_MIRRORS = [
    "https://mirrors.aliyun.com/pypi/simple",
    "https://pypi.org/simple",
    "https://pypi.tuna.tsinghua.edu.cn/simple",
]


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


def pip_install(python: Path, index: str, *extra: str) -> bool:
    """用指定索引执行一次 pip install，返回是否成功（不抛异常）。"""
    cmd = [
        str(python), "-m", "pip", "install", *extra,
        "-i", index, "--disable-pip-version-check",
    ]
    print(f"\n>>> 使用索引 {index}", flush=True)
    result = subprocess.run(cmd)
    return result.returncode == 0


def install_with_fallback(python: Path, mirrors: list, requirements: Path) -> str:
    """按顺序尝试各镜像安装依赖，返回成功的镜像地址。

    只有**全部**镜像都失败才退出，并在报错里列出每个镜像的结果，
    方便用户直接看出是网络问题还是某个镜像的问题。
    """
    failures = []
    for index in mirrors:
        if pip_install(python, index, "-r", str(requirements)):
            return index
        failures.append(index)
        print(f"!!! 该索引安装失败，尝试下一个（{index}）", flush=True)

    lines = "\n".join(f"  - {item}" for item in failures)
    raise SystemExit(
        "所有 pip 索引都安装失败，请检查网络或手动指定可用镜像：\n"
        f"{lines}\n"
        "  手动方式：python scripts\\bootstrap_dev.py --mirror <镜像地址>\n"
        "  也可加 --skip-venv 装到当前解释器。"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化 fanyi 开发环境")
    parser.add_argument(
        "--mirror",
        action="append",
        help="pip 索引地址，可重复指定以自定义回退顺序（默认内置三家）",
    )
    parser.add_argument("--skip-venv", action="store_true", help="不创建虚拟环境")
    parser.add_argument("--upgrade-pip", action="store_true", help="顺带升级 pip")
    args = parser.parse_args()

    mirrors = args.mirror or DEFAULT_MIRRORS

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
        pip_install(python, mirrors[0], "--upgrade", "pip")

    requirements = ROOT / "requirements.txt"
    used = install_with_fallback(python, mirrors, requirements)

    print("\n环境就绪：")
    print(f"  索引     : {used}")
    print(f"  启动工具 : {python} -m fanyi")
    print(f"  自检     : {python} scripts\\selfcheck.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
