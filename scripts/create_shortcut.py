"""在桌面创建启动快捷方式（可选：顺带清理桌面上单个 exe 副本）。

背景：本程序是 PyInstaller **单目录**打包，``翻译.exe`` 必须和同级的
``_internal`` 目录放在一起才能运行。把 exe 单独拷到桌面会报
「找不到指定的模块」——这也是本脚本存在的原因：正确做法是放**快捷方式**，
exe 本体留在项目目录里。

用法（无需管理员权限）::

    .venv\\Scripts\\python scripts\\create_shortcut.py
    .venv\\Scripts\\python scripts\\create_shortcut.py --target "D:\\其他位置\\翻译"
    .venv\\Scripts\\python scripts\\create_shortcut.py --name "截图翻译"
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET_DIR = ROOT / "dist" / "翻译"
SHORTCUT_NAME = "翻译"


def desktop_dir() -> Path:
    """取真实桌面路径。

    不能直接用 ``~/Desktop``：OneDrive 会把桌面重定向，
    此时 ``SHGetKnownFolderPath`` 才给出真正在用的目录。
    """
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "[Environment]::GetFolderPath('Desktop')",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    path = (result.stdout or "").strip()
    return Path(path) if path else Path.home() / "Desktop"


def working_dir_of(target_dir: Path) -> Path:
    """返回应该作为"起始位置"的目录，兼容传入 exe 或目录。"""
    return target_dir.parent if target_dir.suffix.lower() == ".exe" else target_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="创建桌面快捷方式")
    parser.add_argument("--target", default=str(DEFAULT_TARGET_DIR), help="打包产物目录或 exe 路径")
    parser.add_argument("--name", default=SHORTCUT_NAME, help="快捷方式显示名")
    parser.add_argument(
        "--keep-desktop-exe",
        action="store_true",
        help="保留桌面上单独的 翻译.exe（默认会提示删除，因为它无法运行）",
    )
    args = parser.parse_args()

    target = Path(args.target)
    workdir = working_dir_of(target)
    exe = target if target.suffix.lower() == ".exe" else target / "翻译.exe"

    print("=" * 68)
    print("  创建桌面快捷方式")
    print("=" * 68)

    if not exe.exists():
        print(f"\n[失败] 找不到可执行文件：{exe}")
        print("       请先打包：.venv\\Scripts\\python -m PyInstaller --noconfirm 翻译.spec")
        return 1

    internal = workdir / "_internal"
    if not internal.is_dir():
        print(f"\n[警告] 同级目录里没有 _internal：{internal}")
        print("       单目录打包的程序缺少它就无法运行，快捷方式建了也打不开。")
        print("       请确认打包完整，或改用 --target 指向正确的目录。")
        return 1

    files = sum(1 for _ in internal.rglob("*") if _.is_file())
    print(f"\n  程序        : {exe}")
    print(f"  运行时目录  : {internal}（{files} 个文件）")
    print(f"  起始位置    : {workdir}")

    # --- 用 PowerShell 创建 .lnk ---
    link = desktop_dir() / f"{args.name}.lnk"
    # 图标指向 exe 自身（打包时已嵌入图标）
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$sc = $ws.CreateShortcut('{link}'); "
        f"$sc.TargetPath = '{exe}'; "
        f"$sc.WorkingDirectory = '{workdir}'; "
        f"$sc.IconLocation = '{exe},0'; "
        "$sc.Description = '截图翻译工具：按热键框选屏幕，识别文字并翻译'; "
        "$sc.WindowStyle = 1; "
        "$sc.Save()"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0 or not link.exists():
        print(f"\n[失败] 创建快捷方式出错：{result.stderr.strip() or result.stdout.strip()}")
        return 1

    print(f"\n[通过] 已创建快捷方式：{link}")

    # --- 清理桌面上那个跑不起来的 exe 副本 ---
    stray = desktop_dir() / "翻译.exe"
    if stray.exists():
        if args.keep_desktop_exe:
            print(f"\n[提示] 桌面上还留着单独的 exe（已按参数保留）：{stray}")
            print("       它旁边没有 _internal 目录，双击会报「找不到指定的模块」，建议删掉。")
        else:
            try:
                stray.unlink()
                print(f"\n[通过] 已删除桌面上无法运行的副本：{stray}")
            except OSError as exc:
                print(f"\n[提示] 删除失败（可能被占用）：{exc}")
                print(f"       请手动删除 {stray}")

    print("\n双击桌面上的「翻译」图标即可启动（托盘常驻，按 Ctrl+Alt+Z 开始截图翻译）。")
    print("注意：exe 本体必须留在原目录，不要把 exe 单独拷走。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
