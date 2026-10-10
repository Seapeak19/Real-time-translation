"""探测候选外语在各后端与 OCR 上的支持情况，为选型提供依据。

不修改任何代码，只做"能不能用、要什么代码、模型多大"的调研。

用法::

    .venv\\Scripts\\python scripts\\probe_language_support.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fanyi.core.client import HttpClient  # noqa: E402
from fanyi.core.engines import (  # noqa: E402
    BingTranslator,
    MyMemoryTranslator,
    YoudaoTranslator,
)

#: 候选语言：(名称, 各后端的代码, 探测用样本, 期望译文里出现的中文词)
CANDIDATES = [
    ("日语", {"youdao": "ja", "mymemory": "ja-JP", "bing": "ja"}, "大型言語モデルは時々幻覚を起こす。",
     ["大", "语言", "模型", "幻觉"]),
    ("韩语", {"youdao": "ko", "mymemory": "ko-KR", "bing": "ko"}, "대규모 언어 모델은 때때로 환각을 일으킨다.",
     ["大", "语言", "模型", "幻觉"]),
    ("法语", {"youdao": "fr", "mymemory": "fr-FR", "bing": "fr"}, "Les modèles de langue peuvent halluciner.",
     ["模型", "语言", "幻觉"]),
    ("德语", {"youdao": "de", "mymemory": "de-DE", "bing": "de"}, "Große Sprachmodelle können halluzinieren.",
     ["模型", "语言", "幻觉"]),
    ("俄语", {"youdao": "ru", "mymemory": "ru-RU", "bing": "ru"}, "Большие языковые модели могут галлюцинировать.",
     ["模型", "语言", "幻觉"]),
    ("西班牙语", {"youdao": "es", "mymemory": "es-ES", "bing": "es"}, "Los modelos de lenguaje pueden alucinar.",
     ["模型", "语言", "幻觉"]),
]


def main() -> int:
    client = HttpClient(timeout=12.0, retries=0)
    engines = {
        "youdao": YoudaoTranslator(client),
        "mymemory": MyMemoryTranslator(client),
        "bing": BingTranslator(client),
    }

    print("=" * 96)
    print("  候选外语 → 简体中文 的翻译可用性（免费后端）")
    print("=" * 96)
    print()
    print(f"  {'语言':<10}{'后端':<10}{'代码':<10}{'结果':<8}{'译文'}")
    print("  " + "-" * 92)

    summary = {}
    for label, codes, sample, keywords in CANDIDATES:
        ok_count = 0
        attempted = 0
        for name, translator in engines.items():
            code = codes.get(name, codes.get("bing", ""))
            try:
                result = translator.translate(sample, code, "zh-Hans")
            except Exception as exc:
                print(f"  {label:<10}{name:<10}{code:<10}{'失败':<8}{type(exc).__name__}: {str(exc)[:40]}")
                attempted += 1
                continue
            attempted += 1
            hit = [w for w in keywords if w in result.text]
            good = bool(result.text.strip()) and bool(hit)
            ok_count += good
            flag = "可用" if good else "可疑"
            print(f"  {label:<10}{name:<10}{code:<10}{flag:<8}{result.text[:44]}")
        summary[label] = (ok_count, attempted)
        print()

    print("=" * 96)
    print("  汇总：能正确译成中文的后端数")
    print("=" * 96)
    for label, (ok, total) in summary.items():
        bar = "█" * ok + "░" * (total - ok)
        print(f"  {label:<10}{bar}  {ok}/{total}")

    print()
    print("  说明：这只测「翻译」这一环。新增一门外语还需要 OCR 识别模型支持，")
    print("  模型清单见 docs 里的规划文档（RapidOCR 官方提供多语种识别模型）。")
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
