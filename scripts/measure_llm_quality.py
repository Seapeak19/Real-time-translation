"""用真实 API Key 实测大模型翻译：质量、时延、真实 token 用量。

与 estimate_llm_cost.py 的分工：
* ``estimate_llm_cost.py`` 用经验比例**估算**费用（无需 Key）；
* 本脚本**真的发请求**，读接口返回的 ``usage``，用真实数字说话。

输出可直接用于文档：每次翻译的 token 数、按官方单价的折算费用、
以及免费后端常译错的词在大模型下的结果对比。

用法::

    .venv\\Scripts\\python scripts\\measure_llm_quality.py
    .venv\\Scripts\\python scripts\\measure_llm_quality.py --repeat 3
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fanyi.config import Config  # noqa: E402
from fanyi.core.client import HttpClient  # noqa: E402
from fanyi.core.llm import build_prompt  # noqa: E402

#: (说明, 原文, 免费后端实测的错译)
CASES = [
    ("AI 架构", "Transformer", "变压器（当成电力设备）"),
    ("AI 缩写", "RAG", "破布（当成抹布）"),
    ("模型名", "claude-3-5-sonnet", "克劳德-3-5-十四行诗"),
    ("模型名", "GPT-4 Turbo", "GPT-4 终极版"),
    ("AI 缩写", "LLM", "（有时直接不译）"),
    ("AI 术语", "Prompt engineering", "提示工程"),
    ("人名", "Sam Altman", "山姆·奥特曼"),
    ("AI 术语", "Embedding", "包埋 / 嵌入"),
    ("技术句", "Fine-tuning a model requires high-quality data.", "—"),
    ("技术句", "Retrieval-augmented generation improves factual accuracy.", "—"),
    ("长句", "The team spent three weeks fixing a memory leak that only "
            "appeared under heavy load.", "—"),
]

#: DeepSeek 官方单价（美元 / 百万 token）。价格会更动，请以官网为准。
#: 见 https://api-docs.deepseek.com/quick_start/pricing
PRICE_IN_MISS_OFFPEAK = 0.15
PRICE_IN_MISS_PEAK = 0.30
PRICE_IN_HIT_OFFPEAK = 0.003
PRICE_IN_HIT_PEAK = 0.006
PRICE_OUT_OFFPEAK = 0.60
PRICE_OUT_PEAK = 1.20
USD_TO_CNY = 7.2


def cny(tokens_in: int, tokens_out: int, *, hit: bool, peak: bool) -> float:
    """按官方单价折算人民币。"""
    if hit:
        price_in = PRICE_IN_HIT_PEAK if peak else PRICE_IN_HIT_OFFPEAK
    else:
        price_in = PRICE_IN_MISS_PEAK if peak else PRICE_IN_MISS_OFFPEAK
    price_out = PRICE_OUT_PEAK if peak else PRICE_OUT_OFFPEAK
    usd = tokens_in / 1_000_000 * price_in + tokens_out / 1_000_000 * price_out
    return usd * USD_TO_CNY


def main() -> int:
    parser = argparse.ArgumentParser(description="实测大模型翻译质量与用量")
    parser.add_argument("--repeat", type=int, default=1, help="每条重复次数（取中位）")
    parser.add_argument("--model", help="覆盖配置里的模型名，便于对比不同模型")
    args = parser.parse_args()

    config = Config.load()
    if args.model:
        config.llm_model = args.model
    if not config.llm_api_key:
        print("未配置 API Key。请在程序设置里填写后再运行本脚本。")
        return 1

    client = HttpClient(timeout=config.llm_timeout, retries=0)
    endpoint = config.llm_base_url.rstrip("/") + "/chat/completions"

    print("=" * 100)
    print(f"  大模型翻译实测 · 模型 {config.llm_model}")
    print("=" * 100)
    print()
    print(f"  {'类别':<10}{'原文':<44}{'大模型译文':<34}")
    print("  " + "-" * 94)

    times: list = []
    tokens_in: list = []
    tokens_out: list = []
    hits: list = []
    results = []

    for label, text, free_wrong in CASES:
        best = None
        for _ in range(max(1, args.repeat)):
            payload = {
                "model": config.llm_model,
                "messages": build_prompt(text, "auto", "zh-Hans"),
                "temperature": config.llm_temperature,
                "stream": False,
            }
            started = time.perf_counter()
            resp = client.post(
                endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {config.llm_api_key}"},
                timeout=config.llm_timeout,
            )
            elapsed = time.perf_counter() - started
            if resp.status_code != 200:
                print(f"  [HTTP {resp.status_code}] {resp.text[:120]}")
                continue
            data = json.loads(resp.text)
            usage = data.get("usage") or {}
            text_out = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            best = (elapsed, usage, text_out.strip(), data.get("model"))
        if best is None:
            continue

        elapsed, usage, text_out, model_name = best
        times.append(elapsed)
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        cached = int(usage.get("prompt_cache_hit_tokens") or 0)
        tokens_in.append(prompt_tokens)
        tokens_out.append(completion_tokens)
        hits.append(cached)
        results.append((label, text, free_wrong, text_out, prompt_tokens, completion_tokens))

        short = text if len(text) <= 42 else text[:41] + "…"
        shown = text_out if len(text_out) <= 32 else text_out[:31] + "…"
        print(f"  {label:<10}{short:<44}{shown:<34}")

    if not results:
        print("\n  没有拿到任何结果，请检查 Key、接口地址与模型名。")
        client.close()
        return 1

    print()
    print("=" * 100)
    print("  与免费后端的对比（同一批术语）")
    print("=" * 100)
    print(f"  {'原文':<42}{'免费后端（常错）':<28}{'大模型':<28}")
    print("  " + "-" * 96)
    for label, text, free_wrong, text_out, _i, _o in results:
        short = text if len(text) <= 40 else text[:39] + "…"
        wrong = free_wrong if len(free_wrong) <= 26 else free_wrong[:25] + "…"
        good = text_out if len(text_out) <= 26 else text_out[:25] + "…"
        print(f"  {short:<42}{wrong:<28}{good:<28}")

    total_in = sum(tokens_in)
    total_out = sum(tokens_out)
    total_hit = sum(hits)
    average_in = total_in / len(tokens_in)
    average_out = total_out / len(tokens_out)

    print()
    print("=" * 100)
    print("  真实用量与费用（数据来自接口返回的 usage 字段）")
    print("=" * 100)
    print(f"  样本数        : {len(tokens_in)}")
    print(f"  中位时延      : {statistics.median(times):.2f}s")
    print(f"  平均输入 token: {average_in:.0f}（其中命中缓存 {total_hit / len(tokens_in):.0f}）")
    print(f"  平均输出 token: {average_out:.0f}")
    print(f"  平均合计      : {average_in + average_out:.0f} token/次")
    print()

    scenarios = [
        ("缓存未命中 + 低谷价", False, False),
        ("缓存未命中 + 高峰价", False, True),
        ("缓存命中 + 低谷价", True, False),
    ]
    print(f"  {'场景':<24}{'每次(元)':>12}{'1元可翻':>12}{'100元可翻':>12}{'每天100次/月':>14}")
    print("  " + "-" * 76)
    for name, hit, peak in scenarios:
        cost = cny(int(average_in), int(average_out), hit=hit, peak=peak)
        if cost <= 0:
            continue
        print(
            f"  {name:<24}{cost:>12.5f}{1 / cost:>11.0f}次"
            f"{100 / cost:>11.0f}次{cost * 100 * 30:>13.2f}元"
        )

    print()
    print("  说明：")
    print("  * 提示词前缀固定，第二次起通常命中缓存，输入成本可降到约 1/50；")
    print("  * 低谷价为高峰价的一半，高峰时段为 UTC 周一至周五 01:00-04:00、06:00-10:00；")
    print("  * 单价以 DeepSeek 官网为准，此处仅用于判断量级。")
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
