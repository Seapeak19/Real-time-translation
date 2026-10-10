"""对比串行回退与并发竞速的端到端时延。

关键场景是"首选后端被限流"：串行实现会逐个等后续后端，用户体感很慢。
本脚本分别用两种模式跑同一批文本，输出每次耗时与中位数。

用法::

    .venv\\Scripts\\python scripts\\benchmark_race.py
    .venv\\Scripts\\python scripts\\benchmark_race.py --rounds 8
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
from fanyi.core.translate import TranslationCache, TranslationService

#: 每次用不同内容，避免命中缓存（缓存命中就没有可比性了）
TEMPLATES = [
    "Batch {n}: the deployment finished ahead of schedule.",
    "Batch {n}: please verify the cache setting before release.",
    "Batch {n}: the report shows inventory turnover improved.",
    "Batch {n}: remember to restart the service after the update.",
    "Batch {n}: this sentence exists only to measure latency.",
]


def make_text(round_index: int) -> str:
    template = TEMPLATES[round_index % len(TEMPLATES)]
    return template.format(n=f"R{round_index}-{time.time_ns() % 100000}")


def run_mode(label: str, races: bool, rounds: int, limit_first_engine: bool) -> dict:
    """跑一轮并返回统计结果。"""
    config = Config()
    config.request_timeout = 12.0
    config.cache_enabled = True
    config.race_engines = races
    config.race_size = 2
    config.race_stagger = 1.2

    service = TranslationService(config)
    # 每次用独立缓存文件，保证真的走网络
    service.cache = TranslationCache(
        ROOT / "testdata" / f"race_cache_{'on' if races else 'off'}_{int(time.time())}.json",
        limit=200,
    )

    if limit_first_engine:
        # 模拟"首选被限流"：直接让它进入冷却，等价于用户真实的遭遇
        service._mark_failure(
            config.translate_engines[0],
            __import__("fanyi.core.base", fromlist=["RateLimitedError"]).RateLimitedError(
                "模拟限流"
            ),
        )

    print(f"\n===== {label} =====")
    if limit_first_engine:
        print(f"  （已让首选后端 {config.translate_engines[0]} 进入限流冷却）")

    times = []
    providers = {}
    failures = 0
    for index in range(rounds):
        text = make_text(index)
        started = time.perf_counter()
        try:
            result = service.translate(text, target="zh-Hans", source="auto", use_cache=False)
        except Exception as exc:
            elapsed = time.perf_counter() - started
            failures += 1
            times.append(elapsed)
            print(f"  [失败] {elapsed:5.2f}s  {type(exc).__name__}: {str(exc)[:60]}")
            continue
        elapsed = time.perf_counter() - started
        times.append(elapsed)
        providers[result.provider] = providers.get(result.provider, 0) + 1
        print(f"  {elapsed:5.2f}s  引擎={result.provider:<10} {result.text[:44]}")

    service.close()
    ok_times = times
    return {
        "label": label,
        "median": statistics.median(ok_times) if ok_times else None,
        "max": max(ok_times) if ok_times else None,
        "failures": failures,
        "total": rounds,
        "providers": providers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="串行 vs 竞速时延对比")
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()

    print("=" * 80)
    print("  串行回退 vs 并发竞速")
    print("=" * 80)

    results = [
        run_mode("A. 串行回退（旧行为）", races=False, rounds=args.rounds, limit_first_engine=False),
        run_mode("B. 并发竞速（新行为）", races=True, rounds=args.rounds, limit_first_engine=False),
        run_mode(
            "C. 串行回退 + 首选被限流",
            races=False,
            rounds=args.rounds,
            limit_first_engine=True,
        ),
        run_mode(
            "D. 并发竞速 + 首选被限流",
            races=True,
            rounds=args.rounds,
            limit_first_engine=True,
        ),
    ]

    print()
    print("=" * 80)
    print("  汇总")
    print("=" * 80)
    print(f"  {'场景':<28}{'中位时延':>10}{'最慢':>9}{'失败':>7}   引擎分布")
    print("  " + "-" * 74)
    for item in results:
        median = f"{item['median']:.2f}s" if item["median"] else "-"
        worst = f"{item['max']:.2f}s" if item["max"] else "-"
        spread = ", ".join(f"{k}×{v}" for k, v in item["providers"].items()) or "-"
        print(
            f"  {item['label']:<28}{median:>10}{worst:>9}"
            f"{item['failures']}/{item['total']:<5}  {spread}"
        )

    print()
    print("  关注点：场景 C（限流时串行）通常是用户体感最差的；")
    print("  场景 D 应与 B 接近，说明竞速能把'首选被限流'的代价摊平。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
