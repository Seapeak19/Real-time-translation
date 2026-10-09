"""对可用翻译后端做二次验证：用随机生僻文本排除缓存干扰，并测试中→英方向。"""

from __future__ import annotations

import json
import re
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def brief(value: object, limit: int = 100) -> str:
    text = str(value).replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def run_case(name: str, func, text: str, expect_hint: str) -> None:
    started = time.perf_counter()
    try:
        result = func(text)
    except Exception as exc:
        print(f"  {name:<12} 失败 {time.perf_counter() - started:6.2f}s  {type(exc).__name__}: {brief(exc, 70)}")
        return
    elapsed = time.perf_counter() - started
    flag = "OK  " if expect_hint.lower() in str(result).lower() else "?   "
    print(f"  {name:<12} {flag} {elapsed:6.2f}s  {brief(result)}")


# ---------------------------------------------------------------------------
def youdao(text: str, target: str = "zh-CHS") -> str:
    resp = requests.post(
        "https://aidemo.youdao.com/trans",
        data={"q": text, "from": "Auto", "to": target},
        headers={"User-Agent": UA, "Referer": "https://ai.youdao.com/"},
        timeout=8,
    )
    resp.raise_for_status()
    data = resp.json()
    err = data.get("errorCode")
    if err not in ("0", 0, None):
        raise RuntimeError(f"errorCode={err}")
    return data.get("translation", [""])[0]


def mymemory(text: str, langpair: str = "en|zh-CN") -> str:
    resp = requests.get(
        "https://api.mymemory.translated.net/get",
        params={"q": text, "langpair": langpair, "de": "fanyi@example.com"},
        headers={"User-Agent": UA},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["responseData"]["translatedText"]


def bing(text: str, target: str = "zh-Hans") -> str:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    page = session.get("https://cn.bing.com/translator", timeout=10)
    page.raise_for_status()

    ig = re.search(r'IG:"([^"]+)"', page.text)
    iid = re.search(r'data-iid="([^"]+)"', page.text)
    abuse = re.search(r"params_AbusePreventionHelper\s*=\s*(\[[^\]]*\])", page.text)
    if not ig or not abuse:
        raise RuntimeError("找不到会话令牌")
    key, token, _ = json.loads(abuse.group(1))

    resp = session.post(
        "https://cn.bing.com/ttranslatev3",
        params={"isVertical": "1", "IG": ig.group(1), "IID": iid.group(1) if iid else "translator.5028"},
        data={"fromLang": "auto-detect", "text": text, "to": target, "token": token, "key": key},
        headers={"Referer": "https://cn.bing.com/translator"},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    # 结构可能是 {"data":[{...}]} 也可能是 {"data":{...}}
    data = payload.get("data")
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        raise RuntimeError(f"返回结构异常: {brief(payload)}")
    return data["translations"][0]["text"]


def main() -> int:
    token = uuid.uuid4().hex[:8]

    print("=" * 96)
    print("用例 A：英 → 中（每次都是全新文本，确保不吃缓存）")
    print("=" * 96)
    for index in range(1, 3):
        text = (
            f"Probe {token} batch {index}: the quarterly report indicates that inventory "
            f"turnover improved by {index * 7} percent, while logistics costs declined slightly."
        )
        print(f"\n原文: {brief(text, 110)}")
        run_case("youdao", lambda t: youdao(t), text, "库存")
        run_case("mymemory", lambda t: mymemory(t), text, "库存")
        run_case("bing", lambda t: bing(t), text, "库存")

    print("\n" + "=" * 96)
    print("用例 B：中 → 英")
    print("=" * 96)
    for index in range(1, 3):
        text = f"第{index}次探测：这个工具的截图识别速度不错，但是翻译接口有时候会被限流。"
        print(f"\n原文: {brief(text, 110)}")
        run_case("youdao", lambda t: youdao(t, "en"), text, "translat")
        run_case("mymemory", lambda t: mymemory(t, "zh-CN|en"), text, "translat")
        run_case("bing", lambda t: bing(t, "en"), text, "translat")

    print("\n" + "=" * 96)
    print("用例 C：连续 5 次调用看稳定性（youdao）")
    print("=" * 96)
    ok = 0
    for index in range(5):
        text = f"Stability probe {token}-{index}: the system handled {index + 3} concurrent requests."
        started = time.perf_counter()
        try:
            result = youdao(text)
            ok += 1
            print(f"  第{index + 1}次 OK   {time.perf_counter() - started:6.2f}s  {brief(result, 70)}")
        except Exception as exc:
            print(f"  第{index + 1}次 失败 {time.perf_counter() - started:6.2f}s  {brief(exc, 70)}")
        time.sleep(0.4)
    print(f"\n  成功率 {ok}/5")
    return 0


if __name__ == "__main__":
    sys.exit(main())
