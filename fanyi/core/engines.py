"""翻译后端实现。

全部都是"无需 API Key 的免费端点"，任何一个被限流或改接口，
都会由 :class:`~fanyi.core.translate.TranslationService` 自动切换到下一个。

实测（国内网络，2026 年）：

===========  ==========  ==================================================
后端          典型时延     说明
===========  ==========  ==================================================
``youdao``    0.2 ~ 1s    最快，短句质量好，优先使用
``mymemory``  1 ~ 3s      免费额度制，稳定，作为第二顺位
``bing``      1 ~ 3s      需要先取会话令牌，作为第三顺位
``google``    不可达       国内网络下 ``translate.googleapis.com`` 常被阻断，
                          保留它是因为在能直连的网络里它质量最好
===========  ==========  ==================================================

``scripts/probe_engines.py`` 可以在你的网络环境下重新测一遍，
据此在设置里调整后端顺序。
"""

from __future__ import annotations

import html
import json
import re
import time
from typing import Any, Dict, List, Optional

from ..languages import EN, ZH_HANS, ZH_HANT
from .base import (
    EngineError,
    RateLimitedError,
    TextTooLongError,
    TranslateResult,
    Translator,
    join_for_request,
    split_text,
)
from .client import HttpClient

# ---------------------------------------------------------------------------
# 语言代码归一化
# ---------------------------------------------------------------------------


def _normalize_zh(code: str) -> str:
    """把各种中文写法归一到 zh-Hans / zh-Hant。"""
    key = (code or "").replace("_", "-").lower()
    if any(tag in key for tag in ("hant", "tw", "hk", "mo", "cht")):
        return "zh-Hant"
    return "zh-Hans"


# ---------------------------------------------------------------------------
# 1. Google 免费端点
# ---------------------------------------------------------------------------
class GoogleTranslator(Translator):
    """``translate.googleapis.com/translate_a/single`` 免费端点。

    单次请求上限约 5000 字符，这里按 1500 字符切分以留出安全余量。
    """

    name = "google"
    display_name = "Google 免费端点"
    endpoint = "https://translate.googleapis.com/translate_a/single"
    chunk_size = 1500

    def __init__(self, client: HttpClient, timeout: float = 8.0) -> None:
        self.client = client
        self.timeout = timeout

    def translate(self, text: str, source: str, target: str) -> TranslateResult:
        text = (text or "").strip()
        if not text:
            return TranslateResult(text="", provider=self.name, source_lang=source, target_lang=target)
        if source != "auto" and source == target:
            return TranslateResult(text=text, provider=self.name, source_lang=source, target_lang=target)

        src_code = "auto" if source == "auto" else _google_code(source)
        tgt_code = _google_code(target)

        parts: List[str] = []
        detected = source
        for chunk in split_text(text, self.chunk_size, hard_limit=self.chunk_size):
            resp = self.client.get(
                self.endpoint,
                params={
                    "client": "gtx",
                    "sl": src_code,
                    "tl": tgt_code,
                    "dt": "t",
                    "q": chunk,
                },
                timeout=self.timeout,
            )
            payload = HttpClient.jsonp(resp.text)
            if not payload or "sentences" not in payload:
                raise EngineError(f"返回结构异常: {str(payload)[:120]}")

            detected = _from_google_code(payload.get("src")) or detected
            sentences = payload.get("sentences") or []
            piece = "".join(
                s.get("trans", "") for s in sentences if isinstance(s, dict)
            )
            if not piece and sentences:
                raise EngineError("返回内容为空")
            parts.append(piece)

        return TranslateResult(
            text=_join_chunks(parts, detected),
            provider=self.name,
            source_lang=detected,
            target_lang=target,
        )


def _google_code(code: str) -> str:
    if code == ZH_HANS:
        return "zh-CN"
    if code == ZH_HANT:
        return "zh-TW"
    return code


def _from_google_code(code: Optional[str]) -> str:
    if not code:
        return ""
    key = str(code).replace("_", "-").lower()
    if key.startswith("zh"):
        return _normalize_zh(key)
    if key.startswith("en"):
        return EN
    return key


def _join_chunks(parts: List[str], source: str) -> str:
    """拼接分段翻译结果：中日韩直接相连，拉丁语系补空格。"""
    if not parts:
        return ""
    from ..languages import info

    joiner = " " if not info(source).cjk and source != "auto" else ""
    return joiner.join(p.strip() for p in parts).strip()


# ---------------------------------------------------------------------------
# 1. 有道翻译（免费网页接口）
# ---------------------------------------------------------------------------
class YoudaoTranslator(Translator):
    """``aidemo.youdao.com/trans`` 免费接口。

    实测最快（0.2 ~ 1 秒），作为首选后端。
    只区分 ``zh-CHS``，繁体目标由 :mod:`fanyi.languages` 在本地做字形转换。
    """

    name = "youdao"
    display_name = "有道翻译"
    endpoint = "https://aidemo.youdao.com/trans"
    page_url = "https://ai.youdao.com/"
    chunk_size = 1800

    #: 该接口的错误码：0 成功，其余视为失败并切换后端
    #: 411 是频率限制，会触发服务层的退避冷却
    FATAL_CODES = {
        "20": "要翻译的文本过长",
        "30": "无法识别源语言",
        "40": "不支持的语言类型",
        "50": "请求过于频繁或额度用尽",
        "60": "缺少必填参数",
        "411": "请求过于频繁",
    }
    #: 这些错误码按"限流"处理，会让该后端进入退避冷却
    RATE_LIMIT_CODES = {"50", "411"}

    def __init__(self, client: HttpClient, timeout: float = 8.0) -> None:
        self.client = client
        self.timeout = timeout

    def translate(self, text: str, source: str, target: str) -> TranslateResult:
        text = (text or "").strip()
        if not text:
            return TranslateResult(text="", provider=self.name, source_lang=source, target_lang=target)
        if source != "auto" and source == target:
            return TranslateResult(text=text, provider=self.name, source_lang=source, target_lang=target)

        src_code = "Auto" if source == "auto" else _youdao_code(source)
        tgt_code = _youdao_code(target)

        parts: List[str] = []
        for chunk in split_text(text, self.chunk_size, hard_limit=self.chunk_size):
            resp = self.client.post(
                self.endpoint,
                data={"q": chunk, "from": src_code, "to": tgt_code},
                headers={
                    "Referer": self.page_url,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json, text/plain, */*",
                },
                timeout=self.timeout,
            )
            payload = HttpClient.json(resp)
            if not isinstance(payload, dict):
                raise EngineError("有道返回结构异常")

            code = str(payload.get("errorCode", "0"))
            if code not in ("0", ""):
                message = self.FATAL_CODES.get(code, f"错误码 {code}")
                if code in self.RATE_LIMIT_CODES:
                    raise RateLimitedError(f"有道：{message}")
                raise EngineError(f"有道：{message}")

            translation = payload.get("translation") or []
            piece = ""
            if isinstance(translation, list) and translation:
                piece = str(translation[0] or "")
            if not piece:
                raise EngineError("有道返回内容为空")

            if src_code == "Auto":
                detected = str(payload.get("l") or "")
                if detected:
                    source = _normalize_lang_tag(detected) or source
            parts.append(piece)

        return TranslateResult(
            text=_join_chunks(parts, source),
            provider=self.name,
            source_lang=source,
            target_lang=target,
        )


def _youdao_code(code: str) -> str:
    if code == ZH_HANS:
        return "zh-CHS"
    if code == ZH_HANT:
        return "zh-CHT"
    return code


def _normalize_lang_tag(tag: str) -> str:
    """把 ``zh-CHS`` / ``EN`` / ``zh-TW`` 之类的标签归一到内部代码。"""
    key = (tag or "").replace("_", "-").lower()
    if not key:
        return ""
    if key.startswith("zh"):
        if any(t in key for t in ("cht", "hant", "tw", "hk")):
            return ZH_HANT
        return ZH_HANS
    if key.startswith("en"):
        return EN
    return key


# ---------------------------------------------------------------------------
# 2. MyMemory
# ---------------------------------------------------------------------------
class MyMemoryTranslator(Translator):
    """``api.mymemory.translated.net``：匿名可用，按字符数有每日额度。

    不支持"自动检测"，缺少源语言时按目标语言推断一个合理默认值。
    """

    name = "mymemory"
    display_name = "MyMemory"
    endpoint = "https://api.mymemory.translated.net/get"
    chunk_size = 480

    def __init__(self, client: HttpClient, timeout: float = 8.0) -> None:
        self.client = client
        self.timeout = timeout

    def translate(self, text: str, source: str, target: str) -> TranslateResult:
        text = (text or "").strip()
        if not text:
            return TranslateResult(text="", provider=self.name, source_lang=source, target_lang=target)
        if source != "auto" and source == target:
            return TranslateResult(text=text, provider=self.name, source_lang=source, target_lang=target)

        src_code = _mymemory_code(source, target)
        tgt_code = _mymemory_code(target, target)

        parts: List[str] = []
        for chunk in split_text(text, self.chunk_size, hard_limit=480):
            resp = self.client.get(
                self.endpoint,
                params={"q": chunk, "langpair": f"{src_code}|{tgt_code}"},
                timeout=self.timeout,
            )
            payload = HttpClient.json(resp)
            status = payload.get("responseStatus")
            if status not in (200, "200", None):
                message = str(payload.get("responseDetails") or status)
                if "QUERY LENGTH LIMIT" in message.upper():
                    raise EngineError("MyMemory 单次长度超限")
                raise RateLimitedError(f"MyMemory 拒绝请求: {message[:120]}")
            data = payload.get("responseData") or {}
            piece = html.unescape(str(data.get("translatedText") or "")).strip()
            if not piece:
                raise EngineError("MyMemory 返回内容为空")
            parts.append(piece)

        return TranslateResult(
            text=_join_chunks(parts, source),
            provider=self.name,
            source_lang=source if source != "auto" else EN,
            target_lang=target,
        )


def _mymemory_code(code: str, target: str) -> str:
    if code == "auto":
        # 没有自动检测能力：目标是非中文时假定原文是中文，否则假定是英文
        return "en" if target in (ZH_HANS, ZH_HANT) else "zh-CN"
    if code == ZH_HANS:
        return "zh-CN"
    if code == ZH_HANT:
        return "zh-TW"
    return code


# ---------------------------------------------------------------------------
# 3. Bing 翻译（需先取会话令牌）
# ---------------------------------------------------------------------------
class BingTranslator(Translator):
    """Bing 翻译网页接口（先取会话令牌，再调 ``ttranslatev3``）。

    需要先抓一次页面拿到 ``IG``/``IID``/令牌，令牌有有效期，
    过期或结构变化时自动重取一次；仍失败则抛出异常交给下一个后端。

    **域名很重要**：实测 ``cn.bing.com`` 会对请求返回 HTTP 200 但**空内容**
    （反爬收紧），而 ``www.bing.com`` 同一套令牌流程能正常返回 JSON，
    且译文质量明显更好（响应里带 ``usedLLM: true``，用的是大模型翻译）。
    因此这里按 ``www`` → ``cn`` 顺序尝试，任一可用即停。
    """

    name = "bing"
    display_name = "Bing 翻译"

    #: 依次尝试的 (页面地址, 接口地址)。顺序有意义：先用实测可用的那个。
    ENDPOINTS = (
        ("https://www.bing.com/translator", "https://www.bing.com/ttranslatev3"),
        ("https://cn.bing.com/translator", "https://cn.bing.com/ttranslatev3"),
    )

    chunk_size = 900
    ig_re = re.compile(r'IG:"([^"]+)"')
    iid_re = re.compile(r'data-iid="([^"]+)"')
    abuse_re = re.compile(r"params_AbusePreventionHelper\s*=\s*(\[[^\]]*\])")

    def __init__(self, client: HttpClient, timeout: float = 10.0) -> None:
        self.client = client
        self.timeout = timeout
        self._token: Optional[Dict[str, Any]] = None
        #: 上一次成功的域名下标，下次优先用它，避免每次都从头试
        self._endpoint_index = 0

    # ------------------------------------------------------------------
    @property
    def page_url(self) -> str:
        return self.ENDPOINTS[self._endpoint_index][0]

    @property
    def api_url(self) -> str:
        return self.ENDPOINTS[self._endpoint_index][1]

    # ------------------------------------------------------------------
    def _ensure_token(self, force: bool = False) -> Dict[str, Any]:
        if self._token and not force:
            return self._token

        last_error: Optional[Exception] = None
        # 从上次成功的域名开始，绕一圈把所有域名都试一遍
        order = [
            (self._endpoint_index + offset) % len(self.ENDPOINTS)
            for offset in range(len(self.ENDPOINTS))
        ]
        for index in order:
            page_url = self.ENDPOINTS[index][0]
            try:
                resp = self.client.get(page_url, timeout=self.timeout)
            except Exception as exc:
                last_error = exc
                continue

            body = resp.text
            ig = self.ig_re.search(body)
            iid = self.iid_re.search(body)
            abuse = self.abuse_re.search(body)
            if not (ig and abuse):
                last_error = EngineError(f"{page_url} 页面里找不到会话令牌")
                continue

            try:
                key, token, interval = json.loads(abuse.group(1))
            except (ValueError, TypeError) as exc:
                last_error = EngineError(f"Bing 令牌解析失败: {exc}")
                continue

            self._endpoint_index = index
            self._token = {
                "ig": ig.group(1),
                "iid": iid.group(1) if iid else "translator.5028",
                "key": key,
                "token": token,
                "interval": int(interval),
            }
            return self._token

        raise last_error or EngineError("无法从 Bing 页面提取会话令牌")

    # ------------------------------------------------------------------
    def translate(self, text: str, source: str, target: str) -> TranslateResult:
        text = (text or "").strip()
        if not text:
            return TranslateResult(text="", provider=self.name, source_lang=source, target_lang=target)
        if source != "auto" and source == target:
            return TranslateResult(text=text, provider=self.name, source_lang=source, target_lang=target)

        src_code = "auto-detect" if source == "auto" else _bing_code(source)
        tgt_code = _bing_code(target)

        parts: List[str] = []
        detected = source
        for chunk in split_text(text, self.chunk_size, hard_limit=self.chunk_size):
            payload = self._request_chunk(chunk, src_code, tgt_code)
            piece, lang = self._parse_translation(payload)
            if lang:
                detected = lang
            parts.append(piece)

        return TranslateResult(
            text=_join_chunks(parts, detected),
            provider=self.name,
            source_lang=detected,
            target_lang=target,
        )

    @staticmethod
    def _parse_translation(payload: Any) -> tuple:
        """解析 ttranslatev3 的返回，兼容几种实测见过的形状。

        两个域名返回的结构不一样，混用会误判成"结构异常"（译文其实就在里面）：

        * ``www.bing.com`` → ``[{"translations": [...], "detectedLanguage": {...}}]``
          顶层是**数组**，元素直接带 ``translations``
        * ``cn.bing.com``  → ``{"data": {"translations": [...]}}``
          顶层是对象，译文在 ``data`` 里

        返回 ``(译文, 检测到的语言代码或空串)``。
        """
        if isinstance(payload, list):
            payload = payload[0] if payload else None
        elif isinstance(payload, dict) and "translations" not in payload:
            payload = payload.get("data")

        if isinstance(payload, list):
            payload = payload[0] if payload else None
        if not isinstance(payload, dict):
            raise EngineError(f"Bing 返回结构异常: {str(payload)[:120]}")

        piece = ""
        translations = payload.get("translations") or []
        if translations and isinstance(translations[0], dict):
            piece = str(translations[0].get("text") or "")
        if not piece:
            raise EngineError("Bing 返回内容为空")

        detected = ""
        info = payload.get("detectedLanguage") or {}
        if isinstance(info, dict) and info.get("language"):
            detected = _bing_from_code(str(info["language"]))
        return piece, detected

    def _request_chunk(self, chunk: str, src_code: str, tgt_code: str) -> Dict[str, Any]:
        """发一次请求；令牌失效或返回不可解析时重取令牌并重试一次。"""
        last_error: Optional[Exception] = None
        for attempt in (1, 2):
            try:
                token = self._ensure_token(force=attempt == 2)
                resp = self.client.post(
                    self.api_url,
                    params={"isVertical": "1", "IG": token["ig"], "IID": token["iid"]},
                    data={
                        "fromLang": src_code,
                        "text": chunk,
                        "to": tgt_code,
                        "token": token["token"],
                        "key": token["key"],
                    },
                    headers={
                        "Referer": self.page_url,
                        "Origin": "https://cn.bing.com",
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json, text/plain, */*",
                    },
                    timeout=self.timeout,
                )
                payload = self._parse(resp.text)
            except EngineError as exc:
                last_error = exc
            else:
                # 只在这里判"拿到译文了没有"，具体形状交给 _parse_translation：
                # www.bing.com 返回顶层数组，cn.bing.com 返回 {"data": {...}}，
                # 在这里写死形状会把可用域名误判成失败（实测踩过这个坑）。
                if _bing_has_translation(payload):
                    return payload
                last_error = EngineError(f"Bing 返回结构异常: {str(payload)[:120]}")

            # 令牌可能已失效：清掉后重取，再试一次
            self._token = None
            if attempt == 1:
                time.sleep(0.4)

        raise last_error or EngineError("Bing 请求失败")

    @staticmethod
    def _parse(text: str) -> Dict[str, Any]:
        """Bing 可能返回 JSON，也可能是 HTML 转义后的 JSON。"""
        body = (text or "").strip()
        if not body:
            raise EngineError("Bing 返回内容为空")
        if body.startswith("{"):
            try:
                data = json.loads(body)
            except ValueError:
                data = None
            if isinstance(data, dict):
                return data
        unescaped = html.unescape(body)
        for candidate in (unescaped, body.replace('\\"', '"')):
            start = candidate.find('{"data"')
            if start < 0:
                start = candidate.find("{")
            end = candidate.rfind("}")
            if start >= 0 and end > start:
                try:
                    data = json.loads(candidate[start : end + 1])
                except ValueError:
                    continue
                if isinstance(data, dict):
                    return data
        raise EngineError(f"Bing 返回内容无法解析: {body[:120]}")


def _bing_code(code: str) -> str:
    if code == ZH_HANS:
        return "zh-Hans"
    if code == ZH_HANT:
        return "zh-Hant"
    return code


def _bing_from_code(code: str) -> str:
    key = code.replace("_", "-").lower()
    if key.startswith("zh"):
        return _normalize_zh(key)
    if key.startswith("en"):
        return EN
    return key


def _bing_has_translation(payload: Any) -> bool:
    """判断这份返回里到底有没有译文。

    两个域名的形状不同，因此这里做形状无关的判断：
    顶层可能是数组，也可能是 ``{"data": ...}``，译文对象的 ``translations``
    键则在最外层或 ``data`` 里。
    """
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    if not isinstance(payload, dict):
        return False
    if "translations" in payload:
        return True
    inner = payload.get("data")
    if isinstance(inner, list):
        inner = inner[0] if inner else None
    return isinstance(inner, dict) and "translations" in inner


__all__ = ["GoogleTranslator", "MyMemoryTranslator", "BingTranslator"]
