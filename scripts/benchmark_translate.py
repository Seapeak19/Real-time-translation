"""翻译质量与时延实测：定位"慢 / 常失败 / 不准"的具体来源。

对四个后端逐个跑一组真实样本，记录：
* 成功/失败与失败原因
* 每次请求的时延（区分首次与重复）
* 译文是否命中关键词（粗略准确度判据）

这样能区分问题出在"某个后端"、"某个方向"还是"整条链路"。

用法::

    .venv\\Scripts\\python scripts\\benchmark_translate.py
    .venv\\Scripts\\python scripts\\benchmark_translate.py --repeat 3
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fanyi.config import Config
from fanyi.core.client import HttpClient
from fanyi.core.engines import (
    BingTranslator,
    GoogleTranslator,
    MyMemoryTranslator,
    YoudaoTranslator,
)

#: 样本：(说明, 原文, 目标语言, 期望译文里出现的关键词)
#: 关键词取"必须被翻译出来"的核心词，用来发现"返回原文"或"乱译"
SAMPLES = [
    (
        "英文短句 → 中文",
        "The deployment finished ahead of schedule.",
        "zh-Hans",
        ["部署", "提前", "计划", "完成"],
    ),
    (
        "英文技术句 → 中文",
        "Please check whether the cache is enabled in the settings panel.",
        "zh-Hans",
        ["缓存", "设置", "启用", "检查"],
    ),
    (
        "中文短句 → 英文",
        "这个工具的截图识别速度不错，但翻译接口有时候会被限流。",
        "en",
        ["tool", "screenshot", "translat", "limit", "rate"],
    ),
    (
        "中文长句 → 英文",
        "我们已经修复了高分辨率屏幕下框选区域与屏幕对不齐的问题，"
        "并让界面语言可以自由切换。",
        "en",
        ["fix", "screen", "region", "interface", "language", "switch"],
    ),
    (
        "界面文案 → 中文",
        "Enable global hotkeys",
        "zh-Hans",
        ["快捷键", "热键", "启用", "全局"],
    ),
]

ENGINES = {
    "youdao": YoudaoTranslator,
    "mymemory": MyMemoryTranslator,
    "bing": BingTranslator,
    "google": GoogleTranslator,
}


def hit_ratio(text: str, keywords: list) -> float:
    """译文命中关键词的比例（粗判准确度）。"""
    if not text:
        return 0.0
    low = text.lower()
    return sum(1 for k in keywords if k.lower() in low) / len(keywords)


def main() -> int:
    parser = argparse.ArgumentParser(description="翻译后端实测")
    parser.add_argument("--repeat", type=int, default=1, help="每个样本重复次数（取首次时延与成功率）")
    parser.add_argument("--engine", help="只测指定后端")
    args = parser.parse_args()

    config = Config()
    config.request_timeout = 12.0
    client = HttpClient(timeout=config.request_timeout, retries=0)

    engines = {k: v for k, v in ENGINES.items() if not args.engine or k == args.engine}
    summary = {}

    for name, factory in engines.items():
        translator = factory(client)
        print("=" * 92)
        print(f"  后端: {name}")
        print("=" * 92)

        latencies = []
        hits = []
        failures = []

        for label, text, target, keywords in SAMPLES:
            for attempt in range(max(1, args.repeat)):
                started = time.perf_counter()
                try:
                    result = translator.translate(text, "auto", target)
                except Exception as exc:
                    elapsed = time.perf_counter() - started
                    message = f"{type(exc).__name__}: {exc}"
                    failures.append((label, message))
                    print(f"  [失败] {label:<16} {elapsed:5.2f}s  {message[:70]}")
                    break
                elapsed = time.perf_counter() - started
                ratio = hit_ratio(result.text, keywords)
                latencies.append(elapsed)
                hits.append(ratio)
                flag = "OK  " if ratio >= 0.5 else ("部分" if ratio > 0 else "偏差")
                print(
                    f"  [{flag}] {label:<16} {elapsed:5.2f}s  命中 {ratio:.0%}  "
                    f"{result.text[:56]}"
                )
                break  # 每个样本只跑一次请求，--repeat 用于观察多次调用的稳定性

        ok = len(latencies)
        total = len(SAMPLES)
        summary[name] = {
            "ok": ok,
            "total": total,
            "median": statistics.median(latencies) if latencies else None,
            "mean_hit": statistics.mean(hits) if hits else 0.0,
            "failures": failures,
        }
        print()

    print("=" * 92)
    print("  汇总")
    print("=" * 92)
    print(f"  {'后端':<12}{'成功':>6}{'中位时延':>10}{'平均命中':>10}   失败原因")
    print("  " + "-" * 86)
    for name, item in summary.items():
        median = f"{item['median']:.2f}s" if item["median"] else "-"
        reason = ""
        if item["failures"]:
            reason = item["failures"][0][1][:44]
        print(
            f"  {name:<12}{item['ok']}/{item['total']:>4}{median:>10}"
            f"{item['mean_hit']:>9.0%}   {reason}"
        )

    print()
    print("  说明：命中率是粗判（关键词匹配），低于 50% 通常意味着译文跑偏或返回了原文。")
    print("  时延中位数反映日常体验；若某后端时延高又常失败，应把它排到后面或去掉。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
