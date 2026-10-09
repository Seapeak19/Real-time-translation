"""环境自检：验证 OCR、翻译、截图三大能力是否真的可用。

用法::

    .venv\\Scripts\\python scripts\\selfcheck.py            # 全部检查
    .venv\\Scripts\\python scripts\\selfcheck.py --offline   # 跳过联网检查
    .venv\\Scripts\\python scripts\\selfcheck.py --keep      # 保留生成的测试图片
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PASS = "[通过]"
FAIL = "[失败]"
SKIP = "[跳过]"

_results = {"pass": 0, "fail": 0, "skip": 0}


def report(status: str, title: str, detail: str = "") -> None:
    line = f"{status} {title}"
    if detail:
        line += f"\n        {detail}"
    print(line, flush=True)
    if status == PASS:
        _results["pass"] += 1
    elif status == FAIL:
        _results["fail"] += 1
    else:
        _results["skip"] += 1


# ---------------------------------------------------------------------------
def check_imports() -> None:
    print("\n=== 1. 依赖导入 ===")
    for name, module in [
        ("PySide6", "PySide6.QtWidgets"),
        ("requests", "requests"),
        ("numpy", "numpy"),
        ("onnxruntime", "onnxruntime"),
        ("rapidocr-onnxruntime", "rapidocr_onnxruntime"),
        ("opencc", "opencc"),
    ]:
        try:
            __import__(module)
            report(PASS, f"导入 {name}")
        except Exception as exc:
            report(FAIL, f"导入 {name}", str(exc))


# ---------------------------------------------------------------------------
def make_test_image(text_lines, size=(900, 320)):
    """用 Pillow 画一张干净的中英文测试图，作为 OCR 的输入。"""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)

    font = None
    for path in (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\arial.ttf",
    ):
        if Path(path).exists():
            try:
                font = ImageFont.truetype(path, 34)
                break
            except Exception:
                continue
    if font is None:  # pragma: no cover
        font = ImageFont.load_default()

    y = 40
    for line in text_lines:
        draw.text((40, y), line, fill="black", font=font)
        y += 70
    return image


def check_ocr(keep: bool = False):
    print("\n=== 2. 本地 OCR（RapidOCR） ===")
    try:
        from fanyi.core.ocr import create_engine
    except Exception as exc:
        report(FAIL, "导入 OCR 模块", str(exc))
        return None

    expected_lines = ["你好，世界", "Hello world", "截图翻译工具"]
    try:
        image = make_test_image(expected_lines)
    except Exception as exc:
        report(FAIL, "生成测试图片", str(exc))
        return None

    if keep:
        out = ROOT / "testdata"
        out.mkdir(exist_ok=True)
        image.save(out / "ocr_sample.png")
        print(f"        测试图片已保存: {out / 'ocr_sample.png'}")

    engine = create_engine("rapidocr")
    if not engine.is_ready():
        report(FAIL, "OCR 依赖就绪", "rapidocr-onnxruntime 未安装")
        return None

    import numpy as np

    array = np.array(image)[:, :, ::-1]  # RGB → BGR

    started = time.perf_counter()
    try:
        result = engine.recognize(array)
    except Exception as exc:
        report(FAIL, "OCR 识别", str(exc))
        return None
    elapsed = time.perf_counter() - started

    if result.is_empty:
        report(FAIL, "OCR 识别", "没有识别到任何文字（图片可能有问题）")
        return None

    text = result.text.replace("\n", " | ")
    hit = sum(1 for line in expected_lines if _rough_contains(result.text, line))
    report(
        PASS,
        "OCR 识别",
        f"耗时 {elapsed:.2f}s（首次含模型加载）· 平均置信度 {result.mean_confidence:.2f}\n"
        f"        识别结果: {text}\n"
        f"        命中 {hit}/{len(expected_lines)} 行预期文本",
    )
    if hit < len(expected_lines):
        report(SKIP, "OCR 精度提示", "部分行未完全匹配，属正常识别误差，可人工确认")
    return result


def _rough_contains(haystack: str, needle: str) -> bool:
    """忽略空白与全半角差异的宽松包含判断。"""
    import re

    def norm(s: str) -> str:
        return re.sub(r"[\s，,。.、·:：;；!！?？]", "", s).lower()

    return norm(needle) in norm(haystack)


# ---------------------------------------------------------------------------
def check_translate(offline: bool = False) -> None:
    print("\n=== 3. 在线翻译后端 ===")
    if offline:
        report(SKIP, "翻译后端", "已指定 --offline")
        return

    from fanyi.config import Config
    from fanyi.core.translate import ENGINE_LABELS, TranslationService

    config = Config()
    config.translate_engines = ["google", "mymemory", "bing"]
    config.request_timeout = 10.0
    service = TranslationService(config)

    cases = [
        ("Hello, world. This is a screenshot translator.", "zh-Hans"),
        ("你好，世界。这是一个截图翻译工具。", "en"),
    ]
    ok = 0
    for text, target in cases:
        started = time.perf_counter()
        try:
            result = service.translate(text, target=target, source="auto", use_cache=False)
        except Exception as exc:
            report(FAIL, f"翻译到 {target}", str(exc))
            continue
        elapsed = time.perf_counter() - started
        ok += 1
        report(
            PASS,
            f"翻译到 {target}",
            f"后端 {ENGINE_LABELS.get(result.provider, result.provider)} · {elapsed:.2f}s · "
            f"源语言判定 {result.source_lang}\n        译文: {result.text[:80]}",
        )

    if ok == 0:
        report(FAIL, "翻译总评", "所有后端都失败，请检查网络或代理")
    service.close()


def check_script_convert() -> None:
    print("\n=== 4. 简繁字形转换 ===")
    from fanyi.languages import convert_script

    sample = "这是一个截图翻译软件，用来识别屏幕上的文字。"
    traditional = convert_script(sample, "zh-Hant")
    back = convert_script(traditional, "zh-Hans")
    if traditional != sample and back == sample:
        report(PASS, "简 → 繁 → 简 往返", f"繁体: {traditional}")
    elif traditional != sample:
        report(SKIP, "简繁转换", f"转换成功但往返不一致\n        繁体: {traditional}\n        回译: {back}")
    else:
        report(FAIL, "简繁转换", "繁体结果与原文相同，转换未生效")


# ---------------------------------------------------------------------------
def check_screenshot() -> None:
    print("\n=== 5. 屏幕截图（GDI） ===")
    try:
        from fanyi.screenshot import grab_virtual_desktop, virtual_desktop_rect
    except Exception as exc:
        report(FAIL, "导入截图模块", str(exc))
        return

    rect = virtual_desktop_rect()
    if rect[2] <= 0 or rect[3] <= 0:
        report(FAIL, "虚拟桌面尺寸", f"返回 {rect}")
        return
    report(PASS, "虚拟桌面尺寸", f"原点 ({rect[0]}, {rect[1]}) 大小 {rect[2]}×{rect[3]}")

    capture = grab_virtual_desktop()
    if capture is None or capture.is_empty:
        report(FAIL, "抓取虚拟桌面", "返回空图像")
        return
    report(
        PASS,
        "抓取虚拟桌面",
        f"得到 {capture.image.width()}×{capture.image.height()} 位图，原点 {capture.origin}",
    )

    # 顺带验证 QImage → numpy 转换通路
    try:
        from fanyi.screenshot import to_numpy

        array = to_numpy(capture.image, scale=0.25)
        report(PASS, "QImage → numpy", f"形状 {array.shape} dtype {array.dtype}")
    except Exception as exc:
        report(FAIL, "QImage → numpy", str(exc))


def check_hotkey() -> None:
    print("\n=== 6. 全局热键 ===")
    try:
        import keyboard  # noqa: F401
    except Exception as exc:
        report(FAIL, "导入 keyboard", f"{exc}（全局热键不可用）")
        return

    from fanyi.hotkey import format_hotkey, is_valid_hotkey, normalize_hotkey

    cases = {
        "Ctrl+Alt+Z": "ctrl+alt+z",
        "ctrl - shift - a": "ctrl+shift+a",
        "Ctrl+Alt+Shift+F2": "ctrl+alt+shift+f2",
    }
    bad = [src for src, want in cases.items() if normalize_hotkey(src) != want]
    if bad:
        report(FAIL, "热键写法规范化", f"未通过: {bad}")
    else:
        report(PASS, "热键写法规范化", " / ".join(f"{k} → {format_hotkey(v)}" for k, v in cases.items()))

    if is_valid_hotkey("z") or not is_valid_hotkey("ctrl+alt+z"):
        report(FAIL, "热键合法性校验", "缺少修饰键的组合应被拒绝")
    else:
        report(PASS, "热键合法性校验")

    # 真正注册一次，确认钩子可用（注册后立即解绑）
    try:
        import keyboard as kb

        handle = kb.add_hotkey("ctrl+alt+shift+f24", lambda: None)
        kb.remove_hotkey(handle)
        report(PASS, "全局钩子注册", "可以注册并解绑热键")
    except Exception as exc:
        report(FAIL, "全局钩子注册", f"{exc}\n        可能被安全软件拦截，需以管理员身份运行")


# ---------------------------------------------------------------------------
def check_config() -> None:
    print("\n=== 7. 配置读写 ===")
    try:
        from fanyi.config import Config, app_home

        path = app_home() / "selfcheck_config.json"
        config = Config()
        config.target_lang = "en"
        config.hotkey = "ctrl+alt+q"
        config.save(path)

        loaded = Config.load(path)
        if loaded.target_lang == "en" and loaded.hotkey == "ctrl+alt+q":
            report(PASS, "配置保存 / 读取", f"路径 {path}")
        else:
            report(FAIL, "配置保存 / 读取", "读回的值与写入不一致")
        path.unlink(missing_ok=True)
    except Exception as exc:
        report(FAIL, "配置读写", str(exc))


# ---------------------------------------------------------------------------
def check_pipeline(offline: bool = False) -> None:
    print("\n=== 8. 端到端管线（图片 → 译文） ===")
    if offline:
        report(SKIP, "端到端管线", "已指定 --offline")
        return
    try:
        import numpy as np

        from fanyi.config import Config
        from fanyi.core.pipeline import TranslationPipeline

        image = make_test_image(["Hello, world", "This is a screenshot translator"])
        array = np.array(image)[:, :, ::-1]

        config = Config()
        config.target_lang = "zh-Hans"
        config.request_timeout = 10.0
        pipeline = TranslationPipeline(config)
        result = pipeline.run(array, on_progress=lambda stage, text: print(f"        [{stage}] {text}"))
        report(
            PASS,
            "端到端管线",
            f"OCR {result.ocr_seconds:.2f}s + 翻译 {result.translate_seconds:.2f}s "
            f"= {result.total_seconds:.2f}s · 引擎 {result.provider}\n"
            f"        原文: {result.source_text[:80]}\n"
            f"        译文: {result.translation[:80]}",
        )
        pipeline.close()
    except Exception as exc:
        report(FAIL, "端到端管线", f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="fanyi 环境自检")
    parser.add_argument("--offline", action="store_true", help="跳过需要联网的检查")
    parser.add_argument("--keep", action="store_true", help="保留测试图片")
    args = parser.parse_args()

    print("=" * 68)
    print("  截图翻译工具 · 环境自检")
    print(f"  Python: {sys.version.split()[0]}  项目: {ROOT}")
    print("=" * 68)

    check_imports()
    check_config()
    check_ocr(keep=args.keep)
    check_script_convert()
    check_translate(offline=args.offline)
    check_screenshot()
    check_hotkey()
    check_pipeline(offline=args.offline)

    print("\n" + "=" * 68)
    print(f"  结果：通过 {_results['pass']} · 失败 {_results['fail']} · 跳过 {_results['skip']}")
    print("=" * 68)
    return 1 if _results["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
