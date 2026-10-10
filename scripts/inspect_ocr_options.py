"""查清 RapidOCR 的可调参数，用于给"识别偏慢"找优化空间。

用法::

    .venv\\Scripts\\python scripts\\inspect_ocr_options.py
"""

from __future__ import annotations

import inspect
import pathlib
import sys

import rapidocr_onnxruntime as pkg
from rapidocr_onnxruntime import RapidOCR


def main() -> int:
    print("==== RapidOCR 构造参数 ====")
    for name, param in inspect.signature(RapidOCR.__init__).parameters.items():
        if name == "self":
            continue
        print(f"  {name} = {param.default!r}")

    base = pathlib.Path(pkg.__file__).parent
    print("\n==== 包内配置文件 ====")
    for path in sorted(base.rglob("*.yaml")) + sorted(base.rglob("*.yml")):
        print(f"  {path.relative_to(base)}")

    config_file = base / "config.yaml"
    if config_file.exists():
        print("\n==== config.yaml 关键项 ====")
        text = config_file.read_text(encoding="utf-8")
        for line in text.splitlines():
            if any(key in line for key in ("use_", "limit_side", "intra_op", "cpu", "threads", "Global", "Det", "Rec", "Cls")):
                print(f"  {line.rstrip()}")

    print("\n==== 模型文件与体积 ====")
    for path in sorted((base / "models").glob("*.onnx")):
        print(f"  {path.name:<40} {path.stat().st_size / 1024 / 1024:.2f} MB")

    print("\n==== 可用的 ONNX Runtime 执行提供者 ====")
    import onnxruntime

    print(f"  {onnxruntime.get_available_providers()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
