# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把工具打成免安装的单目录程序。

用法::

    .venv\\Scripts\\pyinstaller --noconfirm 翻译.spec

产物在 ``dist\\翻译\\``，双击其中的 ``翻译.exe`` 即可运行（无需装 Python）。

为什么用**单目录**而不是 ``--onefile``：
onefile 每次启动都要把几百 MB 内容解压到临时目录，冷启动要十几秒，
而托盘常驻工具对启动速度很敏感。单目录形态启动只需 1~2 秒。

体积主要来自 Qt 与 ONNX Runtime；下面 excludes 里排掉的是本项目用不到的模块。
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(os.path.abspath(SPECPATH))

# ---------------------------------------------------------------------------
# 需要完整收集的数据/动态库：这些包都有模型文件或非 Python 资源
# ---------------------------------------------------------------------------
datas = []
binaries = []
hiddenimports = []

for package in ("rapidocr_onnxruntime", "onnxruntime"):
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
    except Exception as exc:  # pragma: no cover - 打包环境问题
        print(f"[spec] 收集 {package} 失败: {exc}")
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# cv2 被 rapidocr 以函数内导入的方式使用，需要显式带上
hiddenimports += collect_submodules("cv2")

# OCR 模型文件（RapidOCR 自带 .onnx）必须随包分发，否则运行时无法识别
models_dir = ROOT / ".venv" / "Lib" / "site-packages" / "rapidocr_onnxruntime" / "models"
if models_dir.exists():
    datas.append((str(models_dir), "rapidocr_onnxruntime/models"))

# 应用图标资源
assets_dir = ROOT / "assets"
if assets_dir.exists():
    datas.append((str(assets_dir), "assets"))

# 可执行文件图标（缺失时退回无图标，不影响打包成功）
icon_file = ROOT / "assets" / "fanyi.ico"
icon_path = str(icon_file) if icon_file.exists() else None
if icon_path is None:
    print("[spec] 未找到 assets/fanyi.ico，将打成无图标 exe；"
          "可先运行 python scripts/make_icon.py 生成")
# ---------------------------------------------------------------------------
# 排除用不到的重量级模块
# ---------------------------------------------------------------------------
excludes = [
    # Qt 里本工具用不到的大块头
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQml",
    "PySide6.Qt3DCore",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSerialPort",
    "PySide6.QtSensors",
    "PySide6.QtSpatialAudio",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    # 数据分析栈与本工具无关，但常被间接拉进来
    "matplotlib",
    "pandas",
    "scipy",
    "sklearn",
    "IPython",
    "notebook",
    "tkinter",
    "pytest",
    "PIL.ImageQt",  # 用到的是 PIL 本体，ImageQt 会拉 Qt 绑定
]

a = Analysis(
    # 用仓库根的 launcher.py 作为入口：它做绝对导入，
    # 直接冻结 fanyi/__main__.py 会因为包内相对导入而在运行时 ImportError。
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["keyboard", "requests", "fanyi.app"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="翻译",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # 托盘程序不需要控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="翻译",
)
