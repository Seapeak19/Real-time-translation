"""估算大模型翻译的真实用量与费用。

不能凭感觉写"很便宜"——先量出一次典型截图翻译消耗多少 token，
再按各家公开单价折算，README 里的说法才有依据。

用法::

    # 估算模式：按真实提示词统计字符数，用通用经验比例折算 token
    .venv\\Scripts\\python scripts\\estimate_llm_cost.py

    # 实测模式：填了 Key 就真的发一次请求，读接口返回的 usage 字段
    .venv\\Scripts\\python scripts\\estimate_llm_cost.py --live
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fanyi.core.llm import build_prompt  # noqa: E402

#: 典型场景样本：(说明, 原文)
SAMPLES = [
    ("英文网页两行", "The deployment finished ahead of schedule.\n"
                 "Please verify the cache setting before release."),
    ("英文技术段", "Large language models are built on the Transformer architecture. "
               "Retrieval-augmented generation improves factual accuracy by grounding "
               "the model in external documents."),
    ("推文", "Sam Altman said the new model would ship soon, and that fine-tuning "
           "will be much cheaper than before."),
    ("中文段落", "这个工具会自动识别屏幕上的文字并翻译，支持简繁中文和英语互译。"),
]

#: 各家公开单价（人民币元 / 百万 token），input / output。
#: 价格会变，这里只用于量级估算，请以官网为准。
PRICES = {
    "DeepSeek deepseek-chat": (2.0, 8.0),
    "OpenAI gpt-4o-mini": (0.15 * 7.2, 0.60 * 7.2),  # 美元按 7.2 折人民币
    "硅基流动 Qwen2.5-7B": (0.0, 0.0),  # 有免费额度
}


def approx_tokens(text: str) -> int:
    """粗略估算 token 数。

    经验比例：英文约 4 个字符 1 token，中文约 1.5 个字符 1 token。
    只用于量级判断，真实值以接口返回的 usage 为准。
    """
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return int(cjk / 1.5 + other / 4) + 1


def main() -> int:
    parser = argparse.ArgumentParser(description="估算大模型翻译的费用")
    parser.add_argument("--live", action="store_true", help="真的发一次请求读 usage 字段")
    args = parser.parse_args()

    print("=" * 90)
    print("  大模型翻译用量与费用估算")
    print("=" * 90)
    print()
    print(f"  {'场景':<14}{'原文token':>10}{'提示词':>9}{'输入':>8}{'输出':>8}{'合计':>8}")
    print("  " + "-" * 62)

    totals = []
    for label, text in SAMPLES:
        messages = build_prompt(text, "auto", "zh-Hans")
        prompt_tokens = sum(approx_tokens(m["content"]) for m in messages)
        source_tokens = approx_tokens(text)
        input_tokens = prompt_tokens
        # 译文长度与原文同量级，输出按输入的一半估（中文更紧凑）
        output_tokens = max(8, int(source_tokens * 1.2))
        total = input_tokens + output_tokens
        totals.append(total)
        print(
            f"  {label:<14}{source_tokens:>10}{prompt_tokens:>9}"
            f"{input_tokens:>8}{output_tokens:>8}{total:>8}"
        )

    average = sum(totals) / len(totals)
    print()
    print("=" * 90)
    print("  折算费用")
    print("=" * 90)
    print(f"  平均每次翻译约 {average:.0f} token")
    print()
    print(f"  {'服务':<26}{'每次(元)':>12}{'1元可翻':>12}{'10元可翻':>12}")
    print("  " + "-" * 64)
    for name, (price_in, price_out) in PRICES.items():
        # 输入约占七成，输出三成
        cost = (average * 0.7 / 1_000_000) * price_in + (average * 0.3 / 1_000_000) * price_out
        if cost <= 0:
            print(f"  {name:<26}{'免费额度':>12}{'-':>12}{'-':>12}")
            continue
        per_yuan = 1 / cost
        print(f"  {name:<26}{cost:>12.5f}{per_yuan:>11.0f}次{per_yuan * 10:>11.0f}次")

    print()
    print("  按每天翻 100 次估算的月费用：")
    for name, (price_in, price_out) in PRICES.items():
        cost = (average * 0.7 / 1_000_000) * price_in + (average * 0.3 / 1_000_000) * price_out
        if cost <= 0:
            print(f"    {name:<26}免费额度内")
            continue
        print(f"    {name:<26}{cost * 100 * 30:>8.2f} 元/月")

    if args.live:
        print()
        print("=" * 90)
        print("  实测（真实请求，读取接口返回的 usage）")
        print("=" * 90)
        try:
            from fanyi.config import Config
            from fanyi.core.client import HttpClient
            from fanyi.core.llm import LlmTranslator

            config = Config.load()
            if not config.llm_api_key:
                print("  未配置 API Key，跳过实测。")
                print("  在设置里填好 Key 后重跑本脚本即可看到真实用量。")
                return 0
            client = HttpClient(timeout=config.llm_timeout, retries=0)
            translator = LlmTranslator(
                client,
                api_key=config.llm_api_key,
                base_url=config.llm_base_url,
                model=config.llm_model,
                timeout=config.llm_timeout,
            )
            text = SAMPLES[1][1]
            # 直接拿原始响应以读取 usage
            payload = {
                "model": translator.model,
                "messages": build_prompt(text, "auto", "zh-Hans"),
                "temperature": translator.temperature,
                "stream": False,
            }
            resp = client.post(
                translator.endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {translator.api_key}"},
                timeout=translator.timeout,
            )
            import json as _json

            data = _json.loads(resp.text)
            usage = data.get("usage") or {}
            print(f"  模型: {data.get('model')}")
            print(f"  用量: {usage}")
            print(f"  译文: {data.get('choices', [{}])[0].get('message', {}).get('content', '')[:120]}")
            client.close()
        except Exception as exc:
            print(f"  实测失败: {type(exc).__name__}: {exc}")

    print()
    print("  说明：单价会变动，请以各服务商官网为准；这里只判断量级。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
