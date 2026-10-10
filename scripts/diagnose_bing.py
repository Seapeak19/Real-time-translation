"""诊断 Bing 翻译接口为何返回空内容。

Bing 网页接口分两步：先抓 /translator 页面拿 IG/IID/令牌，再 POST 到
/ttranslatev3。任何一步结构变化都会失败，这个脚本把每一步的原始返回打出来，
而不是只说"失败了"。

用法::

    .venv\\Scripts\\python scripts\\diagnose_bing.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
PAGE = "https://cn.bing.com/translator"
API = "https://cn.bing.com/ttranslatev3"
TEXT = "The deployment finished ahead of schedule."


def brief(value: object, limit: int = 200) -> str:
    text = str(value).replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main() -> int:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})

    print("=" * 84)
    print("  步骤 1：抓 /translator 页面并解析令牌")
    print("=" * 84)
    try:
        page = session.get(PAGE, timeout=12)
    except Exception as exc:
        print(f"  请求失败: {type(exc).__name__}: {exc}")
        return 1

    print(f"  HTTP {page.status_code}  长度 {len(page.text)}  编码 {page.encoding}")
    body = page.text

    ig = re.search(r'IG:"([^"]+)"', body)
    iid = re.search(r'data-iid="([^"]+)"', body)
    abuse = re.search(r"params_AbusePreventionHelper\s*=\s*(\[[^\]]*\])", body)
    print(f"  IG  匹配: {ig.group(1) if ig else '未找到'}")
    print(f"  IID 匹配: {iid.group(1) if iid else '未找到'}")
    print(f"  令牌匹配: {brief(abuse.group(1), 80) if abuse else '未找到'}")

    if not (ig and abuse):
        print("\n  → 页面里没有预期结构，Bing 很可能已改版。")
        print("  页面里与令牌相关的片段（前 300 字）：")
        for keyword in ("AbusePrevention", "IG:", "data-iid", "ttranslatev3"):
            index = body.find(keyword)
            if index >= 0:
                print(f"    [{keyword}] …{brief(body[max(0, index - 60): index + 160])}")
        return 1

    key, token, interval = json.loads(abuse.group(1))
    print(f"  key={brief(key, 20)}  token={brief(token, 20)}  interval={interval}")

    print()
    print("=" * 84)
    print("  步骤 2：POST /ttranslatev3")
    print("=" * 84)
    resp = session.post(
        API,
        params={"isVertical": "1", "IG": ig.group(1), "IID": iid.group(1) if iid else "translator.5028"},
        data={
            "fromLang": "auto-detect",
            "text": TEXT,
            "to": "zh-Hans",
            "token": token,
            "key": key,
        },
        headers={
            "Referer": PAGE,
            "Origin": "https://cn.bing.com",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json, text/plain, */*",
        },
        timeout=12,
    )
    print(f"  HTTP {resp.status_code}  长度 {len(resp.text)}")
    print(f"  Content-Type: {resp.headers.get('Content-Type')}")
    print(f"  原始返回（前 500 字）:")
    print(f"    {brief(resp.text, 500)}")

    print()
    # 尝试多种解析方式，看看到底是"结构变了"还是"内容为空"
    body = resp.text.strip()
    print("  各种解析尝试：")
    try:
        data = json.loads(body)
        print(f"    直接 json.loads 成功: {brief(data, 300)}")
        if isinstance(data, dict):
            print(f"    顶层键: {list(data.keys())}")
            inner = data.get("data")
            print(f"    data 类型: {type(inner).__name__}")
            if isinstance(inner, list) and inner:
                print(f"    data[0] 键: {list(inner[0].keys()) if isinstance(inner[0], dict) else inner[0]}")
            elif isinstance(inner, dict):
                print(f"    data 键: {list(inner.keys())}")
    except ValueError as exc:
        print(f"    直接 json.loads 失败: {exc}")

    import html

    unescaped = html.unescape(body)
    if unescaped != body:
        print(f"    HTML 反转义后不同，长度 {len(unescaped)}：{brief(unescaped, 300)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
