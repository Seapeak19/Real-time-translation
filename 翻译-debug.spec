# -*- mode: python ; coding: utf-8 -*-
"""诊断用打包配置：与 翻译.spec 相同，但保留控制台窗口以便看到崩溃堆栈。

用法::

    .venv\\Scripts\\pyinstaller --noconfirm --distpath dist-debug --workpath build-debug 翻译-debug.spec
    dist-debug\\翻译-debug\\翻译-debug.exe
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(os.path.abspath(SPECPATH))

datas = []
binaries = []
hiddenimports = []

for package in ("rapidocr_onnxruntime", "onnxruntime"):
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
    except Exception as exc:
        print(f"[spec] 收集 {package} 失败: {exc}")
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

hiddenimports += collect_submodules("cv2")

models_dir = ROOT / ".venv" / "Lib" / "site-packages" / "rapidocr_onnxruntime" / "models"
if models_dir.exists():
    datas.append((str(models_dir), "rapidocr_onnxruntime/models"))

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["keyboard", "requests", "fanyi.app"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="翻译-debug",
    debug=False,
    strip=False,
    upx=False,
    console=True,  # 关键：保留控制台，崩溃信息才看得见
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="翻译-debug",
)
