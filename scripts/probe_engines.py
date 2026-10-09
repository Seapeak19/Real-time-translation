"""翻译后端可用性诊断：同时探测多个免费端点，报告时延与质量。

用途：当某个后端被限流/封锁时，用它快速判断该把哪个后端排在前面。

用法::

    .venv\\Scripts\\python scripts\\probe_engines.py
    .venv\\Scripts\\python scripts\\probe_engines.py --text "自定义文本"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def brief(value: object, limit: int = 90) -> str:
    text = str(value).replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def timeit(func, *args, **kwargs):
    started = time.perf_counter()
    try:
        result = func(*args, **kwargs)
    except Exception as exc:
        return None, time.perf_counter() - started, f"{type(exc).__name__}: {exc}"
    return result, time.perf_counter() - started, ""


# ---------------------------------------------------------------------------
# 候选后端
# ---------------------------------------------------------------------------
def probe_google_apis(text: str):
    """translate.googleapis.com（免费端点）。"""
    resp = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": text},
        headers={"User-Agent": UA},
        timeout=8,
    )
    resp.raise_for_status()
    payload = json.loads(resp.text[4:] if resp.text.startswith("/**/") else resp.text)
    return "".join(s.get("trans", "") for s in payload.get("sentences", []))


def probe_google_com(text: str):
    """translate.google.com（网页端点，国内常被 DNS 污染）。"""
    resp = requests.get(
        "https://translate.google.com/translate_a/single",
        params={"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": text},
        headers={"User-Agent": UA},
        timeout=8,
    )
    resp.raise_for_status()
    payload = json.loads(resp.text[4:] if resp.text.startswith("/**/") else resp.text)
    return "".join(s.get("trans", "") for s in payload.get("sentences", []))


def probe_bing(text: str):
    """cn.bing.com 的 ttranslatev3 网页接口。"""
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    page = session.get("https://cn.bing.com/translator", timeout=10)
    page.raise_for_status()

    import re

    ig = re.search(r'IG:"([^"]+)"', page.text)
    iid = re.search(r'data-iid="([^"]+)"', page.text)
    abuse = re.search(r"params_AbusePreventionHelper\s*=\s*(\[[^\]]*\])", page.text)
    if not ig or not abuse:
        raise RuntimeError("页面里找不到会话令牌（结构可能已变更）")
    key, token, _ = json.loads(abuse.group(1))

    resp = session.post(
        "https://cn.bing.com/ttranslatev3",
        params={"isVertical": "1", "IG": ig.group(1), "IID": iid.group(1) if iid else "translator.5028"},
        data={"fromLang": "auto-detect", "text": text, "to": "zh-Hans", "token": token, "key": key},
        headers={"Referer": "https://cn.bing.com/translator"},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    data = payload["data"]
    if isinstance(data, list):
        data = data[0]
    return data["translations"][0]["text"]


def probe_mymemory(text: str):
    """api.mymemory.translated.net（免费额度制）。"""
    resp = requests.get(
        "https://api.mymemory.translated.net/get",
        params={"q": text, "langpair": "en|zh-CN"},
        headers={"User-Agent": UA},
        timeout=12,
    )
    resp.raise_for_status()
    return resp.json()["responseData"]["translatedText"]


def probe_baidu_suggest(text: str):
    """百度翻译的免费建议接口（无需 Key，适合短句）。"""
    resp = requests.get(
        "https://fanyi.baidu.com/sug",
        data={"kw": text},
        headers={"User-Agent": UA, "Referer": "https://fanyi.baidu.com/"},
        timeout=8,
    )
    resp.raise_for_status()
    data = resp.json()
    items = data.get("data") or []
    if not items:
        raise RuntimeError(f"没有结果: {brief(data)}")
    return items[0].get("v")


def probe_youdao(text: str):
    """有道翻译的免费网页接口（可能要求签名，作为候选探测）。"""
    resp = requests.post(
        "https://aidemo.youdao.com/trans",
        data={"q": text, "from": "Auto", "to": "zh-CHS"},
        headers={"User-Agent": UA, "Referer": "https://ai.youdao.com/"},
        timeout=8,
    )
    resp.raise_for_status()
    return resp.json().get("translation", [""])[0]


CANDIDATES = [
    ("google:translate.googleapis.com", probe_google_apis),
    ("google:translate.google.com", probe_google_com),
    ("bing:cn.bing.com/ttranslatev3", probe_bing),
    ("mymemory:api.mymemory.translated.net", probe_mymemory),
    ("baidu:fanyi.baidu.com/sug", probe_baidu_suggest),
    ("youdao:aidemo.youdao.com/trans", probe_youdao),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="探测各翻译免费后端的可用性与时延")
    parser.add_argument("--text", default="Hello, world. This is a screenshot translator.")
    parser.add_argument("--repeat", type=int, default=1, help="每个后端重复次数（取最快）")
    args = parser.parse_args()

    print(f"探测文本: {args.text}\n")
    print(f"{'后端':<38} {'结果':<10} {'最快':>8}  返回")
    print("-" * 100)

    available = []
    for name, func in CANDIDATES:
        best = None
        error = ""
        for _ in range(max(1, args.repeat)):
            result, elapsed, err = timeit(func, args.text)
            if result:
                if best is None or elapsed < best[1]:
                    best = (result, elapsed)
            else:
                error = err
        if best is not None:
            available.append((name, best[1]))
            print(f"{name:<38} {'可用':<10} {best[1]:>7.2f}s  {brief(best[0])}")
        else:
            print(f"{name:<38} {'失败':<10} {'-':>8}  {brief(error)}")

    print("\n按速度排序的可用后端：")
    for name, elapsed in sorted(available, key=lambda x: x[1]):
        print(f"  {elapsed:6.2f}s  {name}")
    return 0 if available else 1


if __name__ == "__main__":
    sys.exit(main())
