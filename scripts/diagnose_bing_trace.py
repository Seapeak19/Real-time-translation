"""抓取 Bing 在"非英语源 → 中文"时失败的完整堆栈。

diagnose_bing_lang.py 显示原始返回是正常的，说明失败不在 HTTP 层，
而在 translate() 的某处。这里把完整 traceback 打出来。
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fanyi.core.client import HttpClient  # noqa: E402
from fanyi.core.engines import BingTranslator  # noqa: E402

CASES = [
    ("日语", "ja", "大型言語モデルは時々幻覚を起こす。"),
    ("韩语", "ko", "대규모 언어 모델은 때때로 환각을 일으킨다."),
    ("俄语", "ru", "Большие языковые модели могут галлюцинировать."),
    ("法语", "fr", "Les modèles de langue peuvent halluciner."),
    ("英语", "en", "Large language models can hallucinate."),
]


def main() -> int:
    client = HttpClient(timeout=12.0, retries=0)
    translator = BingTranslator(client)

    for label, source, text in CASES:
        print("=" * 90)
        print(f"  {label}  translate(text, {source!r}, 'zh-Hans')")
        print("=" * 90)
        try:
            result = translator.translate(text, source, "zh-Hans")
            print(f"  [成功] {result.text}")
        except Exception:
            print("  [失败] 完整堆栈：")
            for line in traceback.format_exc().splitlines():
                print(f"    {line}")
        print()
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
