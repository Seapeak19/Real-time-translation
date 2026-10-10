"""定位「英文直译英文」的触发条件。

diagose_en2zh.py 用整句测试时后端都正常，说明"回显原文"只在特定输入下出现。
本脚本按可疑特征逐个试：短词、术语、全大写、含数字符号、代码/URL、
超长句、只有一两个词等。

用法::

    .venv\\Scripts\\python scripts\\diagnose_echo.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fanyi.core.client import HttpClient
from fanyi.core.engines import BingTranslator, MyMemoryTranslator

#: (特征, 输入)
CASES = [
    ("单个词", "Transformer"),
    ("单个术语", "Embedding"),
    ("两个词", "Prompt engineering"),
    ("专有名词", "OpenAI"),
    ("产品名", "ChatGPT"),
    ("全大写缩写", "RAG"),
    ("全大写缩写", "LLM"),
    ("技术缩写", "GPU utilization"),
    ("带数字", "GPT-4 Turbo"),
    ("带连字符", "state-of-the-art"),
    ("长模型名", "claude-3-5-sonnet"),
    ("代码片段", "print(len(arr))"),
    ("URL", "https://example.com/docs"),
    ("路径", "C:\\Users\\test\\config.json"),
    ("版本号", "v1.2.3-beta"),
    ("单词+符号", "OK?"),
    ("混合", "AI-powered tool"),
    ("人名", "Sam Altman"),
    ("超长单句", "The model was trained on a large corpus and then evaluated on "
                "several benchmarks before being released to the public."),
    ("无空格", "HelloWorldTest"),
    ("下划线标识", "max_tokens"),
    ("JSON 片段", '"temperature": 0.7'),
    ("Emoji 混排", "Great job! 🎉"),
]

CJK = re.compile(r"[\u4e00-\u9fff]")


def classify(source: str, output: str) -> str:
    out = (output or "").strip()
    if not out:
        return "空译文"
    if not CJK.search(out):
        if re.sub(r"[\s\W_]+", "", source).lower() == re.sub(r"[\s\W_]+", "", out).lower():
            return "回显原文"
        return "无中文"
    return "已翻译"


def main() -> int:
    client = HttpClient(timeout=12.0, retries=0)
    engines = {
        "bing": BingTranslator(client),
        "mymemory": MyMemoryTranslator(client),
    }

    findings = []
    for name, translator in engines.items():
        print("=" * 92)
        print(f"  后端 {name} · 英译中（按可疑特征逐个试）")
        print("=" * 92)
        for label, source in CASES:
            try:
                result = translator.translate(source, "auto", "zh-Hans")
            except Exception as exc:
                print(f"  [{type(exc).__name__[:12]:<12}] {label:<12} {source[:34]!r}")
                findings.append((name, label, "请求失败", source, str(exc)[:50]))
                continue
            kind = classify(source, result.text)
            mark = "" if kind == "已翻译" else "  ←"
            print(f"  [{kind:<8}] {label:<12} {source[:34]!r} → {result.text[:34]!r}{mark}")
            if kind in ("回显原文", "无中文", "空译文"):
                findings.append((name, label, kind, source, result.text))
        print()

    print("=" * 92)
    print("  未翻译的情况（这些就是「英文直译英文」的现场）")
    print("=" * 92)
    if not findings:
        print("  未复现。说明回显不是由输入形态触发的。")
    else:
        for name, label, kind, source, output in findings:
            print(f"  {name:<10} {label:<12} {kind:<8} {source[:30]!r} → {output[:34]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
