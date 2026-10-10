"""诊断 Bing 在"非英语源语言 → 中文"时的返回结构。

probe_language_support.py 发现：日语/韩语/俄语 → 中文时报
「返回内容无法解析」，而法语/德语/西班牙语 → 中文正常。
本脚本打印原始返回，定位差异。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fanyi.core.client import HttpClient  # noqa: E402
from fanyi.core.engines import BingTranslator  # noqa: E402

CASES = [
    ("日语 → 中文", "ja", "大型言語モデルは時々幻覚を起こす。"),
    ("韩语 → 中文", "ko", "대규모 언어 모델은 때때로 환각을 일으킨다."),
    ("俄语 → 中文", "ru", "Большие языковые модели могут галлюцинировать."),
    ("法语 → 中文", "fr", "Les modèles de langue peuvent halluciner."),
    ("英语 → 中文", "en", "Large language models can hallucinate."),
    ("中文 → 英语", "zh-Hans", "大语言模型有时会产生幻觉。"),
]


def main() -> int:
    client = HttpClient(timeout=12.0, retries=0)
    translator = BingTranslator(client)

    for label, source, text in CASES:
        src_code = "auto-detect" if source == "auto" else translator_code(source)
        print("=" * 92)
        print(f"  {label}   (fromLang={src_code} → to=zh-Hans)")
        print("=" * 92)
        try:
            token = translator._ensure_token()
            resp = client.post(
                translator.api_url,
                params={"isVertical": "1", "IG": token["ig"], "IID": token["iid"]},
                data={
                    "fromLang": src_code,
                    "text": text,
                    "to": "zh-Hans",
                    "token": token["token"],
                    "key": token["key"],
                },
                headers={
                    "Referer": translator.page_url,
                    "Origin": "https://www.bing.com",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json, text/plain, */*",
                },
                timeout=12,
            )
            body = resp.text
            print(f"  HTTP {resp.status_code}  长度 {len(body)}")
            if body.strip():
                data = json.loads(body)
                print(f"  顶层类型: {type(data).__name__}")
                if isinstance(data, list) and data:
                    print(f"  元素键: {list(data[0]) if isinstance(data[0], dict) else data[0]}")
                    print(f"  内容: {json.dumps(data[0], ensure_ascii=False)[:200]}")
                elif isinstance(data, dict):
                    print(f"  顶层键: {list(data)}")
                    print(f"  内容: {json.dumps(data, ensure_ascii=False)[:200]}")
            else:
                print("  （返回为空）")
        except Exception as exc:
            print(f"  异常: {type(exc).__name__}: {exc}")
        print()


def translator_code(code: str) -> str:
    from fanyi.core.engines import _bing_code

    return _bing_code(code)


if __name__ == "__main__":
    sys.exit(main())
