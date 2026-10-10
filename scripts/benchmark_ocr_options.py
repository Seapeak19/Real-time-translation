"""实测 RapidOCR 参数对"速度 / 准确率"的影响。

候选参数（来自包内 config.yaml）：

* ``Global.use_cls``      —— 方向分类器，判断文字是否倒置。桌面截图基本不需要
* ``Det.limit_side_len``  —— 检测前把图缩到长边不超过该值。调大更准但更慢

脚本对同一批合成图片分别跑不同配置，输出时延与识别正确率，
用数据决定默认值，而不是凭感觉。

用法::

    .venv\\Scripts\\python scripts\\benchmark_ocr_options.py
"""

from __future__ import annotations

import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import rapidocr_onnxruntime  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

#: 三组测试图：(名称, 尺寸, 文本行, 字号)
CASES = [
    ("界面小字", (900, 220), ["Enable global hotkeys", "Clear translation cache"], 24),
    ("正文中等字", (1100, 300), ["The cache must be cleared before release.",
                              "Remember to restart the service."], 32),
    ("混合中英", (1000, 260), ["截图翻译工具 v0.3.0", "Screenshot translator works offline"], 30),
]


def make_image(size, lines, font_size):
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    font = None
    for path in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\arial.ttf"):
        if Path(path).exists():
            try:
                font = ImageFont.truetype(path, font_size)
                break
            except Exception:
                continue
    y = int(size[1] * 0.12)
    for line in lines:
        draw.text((30, y), line, fill="black", font=font)
        y += int(font_size * 2.1)
    return image


def normalize(text: str) -> str:
    import re

    return re.sub(r"[\s，,。.、·:：;；!！?？]", "", text).lower()


def accuracy(recognized: str, expected: list) -> float:
    """按字符级重合度估算准确率（避免只判"完全命中"过于苛刻）。"""
    import difflib

    got = normalize(recognized)
    want = normalize("".join(expected))
    if not want:
        return 0.0
    return difflib.SequenceMatcher(None, want, got).ratio()


def build_engine(config_overrides: dict):
    """用修改过的 config.yaml 构造 RapidOCR 实例。"""
    base = Path(rapidocr_onnxruntime.__file__).parent
    source = base / "config.yaml"
    text = source.read_text(encoding="utf-8")

    for key, value in config_overrides.items():
        section, _, name = key.partition(".")
        # 只在对应段落内替换该项，避免误改同名键
        lines = text.splitlines()
        out = []
        in_section = False
        for line in lines:
            stripped = line.strip()
            if stripped.endswith(":") and not line.startswith(" " * 4):
                in_section = stripped[:-1] == section
            if in_section and stripped.startswith(name + ":"):
                indent = line[: len(line) - len(line.lstrip())]
                out.append(f"{indent}{name}: {value}")
                continue
            out.append(line)
        text = "\n".join(out) + "\n"

    tmp_dir = Path(tempfile.mkdtemp(prefix="ocr_cfg_"))
    config_path = tmp_dir / "config.yaml"
    config_path.write_text(text, encoding="utf-8")
    # 模型是相对 config.yaml 的路径，需要一并可见
    shutil.copytree(base / "models", tmp_dir / "models", dirs_exist_ok=True)
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR(str(config_path)), tmp_dir


CONFIGS = [
    ("默认（use_cls=true, side=736）", {}),
    ("关方向分类 use_cls=false", {"Global.use_cls": "false"}),
    ("侧长上限 1280", {"Det.limit_side_len": "1280"}),
    ("关分类 + 侧长 1280", {"Global.use_cls": "false", "Det.limit_side_len": "1280"}),
]


def main() -> int:
    arrays = []
    for name, size, lines, font_size in CASES:
        image = make_image(size, lines, font_size)
        arrays.append((name, np.array(image)[:, :, ::-1], lines))

    print("=" * 96)
    print("  RapidOCR 参数对比（每组跑 2 次取较快的一次，排除首次加载）")
    print("=" * 96)

    rows = []
    for label, overrides in CONFIGS:
        engine, tmp_dir = build_engine(overrides)
        try:
            engine(arrays[0][1])  # 预热
        except Exception as exc:
            print(f"  [跳过] {label}: 预热失败 {type(exc).__name__}: {exc}")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            continue

        times, accs = [], []
        print(f"\n  --- {label} ---")
        for name, array, expected in arrays:
            started = time.perf_counter()
            result, _ = engine(array)
            elapsed = time.perf_counter() - started
            text = " ".join(item[1] for item in (result or []))
            ratio = accuracy(text, expected)
            times.append(elapsed)
            accs.append(ratio)
            print(f"    {name:<10} {elapsed:5.2f}s  准确度 {ratio:.0%}  {text[:56]}")

        rows.append((label, statistics.median(times), statistics.mean(accs)))
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print()
    print("=" * 96)
    print("  汇总")
    print("=" * 96)
    print(f"  {'配置':<30}{'中位时延':>10}{'平均准确度':>12}")
    print("  " + "-" * 54)
    for label, median, acc in rows:
        print(f"  {label:<30}{median:>9.2f}s{acc:>11.0%}")

    print()
    print("  判据：时延下降明显且准确度不掉，才值得改默认值。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
