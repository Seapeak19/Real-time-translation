"""复现「英译中时出现英文直译英文 / 新词与人名翻不出来」。

用户反馈：中文→英文正常，问题几乎只出现在英文→中文，表现为
* 译文里整句或整段保持英文原样
* AI 类新词、人名翻不出来

本脚本对多个后端的**英文→中文**方向做细粒度检测，并检查是否存在
"译文与原文相同"的退化输出（那才是真正的 bug）。

用法::

    .venv\\Scripts\\python scripts\\diagnose_en2zh.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fanyi.core.client import HttpClient
from fanyi.core.engines import (
    BingTranslator,
    MyMemoryTranslator,
    YoudaoTranslator,
)

#: (类别, 原文, 期望译文里应出现的词)
CASES = [
    ("普通句子", "The deployment finished ahead of schedule.", ["部署"]),
    ("普通句子", "Please restart the service after the update.", ["重启", "重新启动"]),
    ("AI 词汇", "Large language models can hallucinate facts.", ["大语言模型", "幻觉", "语言模型"]),
    ("AI 词汇", "Fine-tuning a model requires high-quality data.", ["微调", "模型", "数据"]),
    ("AI 词汇", "Retrieval-augmented generation improves accuracy.", ["检索", "生成", "准确"]),
    ("AI 词汇", "The agent uses chain-of-thought prompting.", ["思维链", "提示", "智能体"]),
    ("人名", "Sam Altman said the model would ship soon.", ["奥特曼", "阿尔特曼", "模型"]),
    ("人名", "Elon Musk announced a new AI company.", ["马斯克", "公司"]),
    ("人名+头衔", "Dr. Fei-Fei Li leads the lab.", ["李飞飞", "博士", "实验室"]),
    ("产品名", "We compared Claude, Gemini and GPT-4.", ["对比", "比较"]),
    ("脏话/口语", "This damn thing keeps crashing.", ["崩溃", "崩"]),
    ("长句", "The team spent three weeks fixing a memory leak "
              "that only appeared under heavy load.", ["内存泄漏", "团队", "负载"]),
]

#: 判定"英文直译英文"：译文里几乎不含中日韩文字
CJK = re.compile(r"[\u4e00-\u9fff]")
LATIN = re.compile(r"[A-Za-z]")


def looks_like_echo(source: str, output: str) -> bool:
    """译文是否等于/近似等于原文（退化输出）。"""
    def norm(text: str) -> str:
        return re.sub(r"[\s\W_]+", "", text).lower()

    if not output.strip():
        return True
    if norm(source) == norm(output):
        return True
    return False


def is_untranslated(source: str, output: str) -> bool:
    """译文里几乎没有中文，且大部分英文原文被保留。"""
    if not output.strip():
        return True
    if CJK.search(output):
        return False
    words = [w for w in re.findall(r"[A-Za-z]{3,}", source.lower())]
    if not words:
        return False
    kept = sum(1 for w in words if w in output.lower())
    return kept / len(words) > 0.6


def main() -> int:
    client = HttpClient(timeout=12.0, retries=0)
    engines = {
        "youdao": YoudaoTranslator(client),
        "bing": BingTranslator(client),
        "mymemory": MyMemoryTranslator(client),
    }

    problems = []
    for name, translator in engines.items():
        print("=" * 96)
        print(f"  后端 {name} · 英译中")
        print("=" * 96)
        for label, source, expected in CASES:
            try:
                result = translator.translate(source, "auto", "zh-Hans")
            except Exception as exc:
                print(f"  [请求失败] {label:<10} {type(exc).__name__}: {str(exc)[:60]}")
                problems.append((name, label, "请求失败", str(exc)[:60]))
                continue

            text = result.text
            echo = looks_like_echo(source, text)
            untranslated = is_untranslated(source, text)
            hit = [w for w in expected if w in text]
            flag = "回显原文" if echo else ("几乎未翻译" if untranslated else ("部分" if not hit else "OK"))
            if echo or untranslated or not hit:
                problems.append((name, label, flag, text[:60]))

            print(f"  [{flag:<8}] {label:<10} 命中{len(hit)}/{len(expected)}  {text[:66]}")
        print()

    print("=" * 96)
    print("  问题清单")
    print("=" * 96)
    if not problems:
        print("  未发现回显或未翻译的情况。")
    else:
        for name, label, kind, detail in problems:
            print(f"  {name:<10} {label:<10} {kind:<10} {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
