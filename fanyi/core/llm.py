"""大模型翻译后端（OpenAI 兼容接口）。

为什么需要它：免费机器翻译接口是**通用句对模型**，缺领域知识，实测会给出
``Transformer → 变压器``、``RAG → 破布`` 这类结果——术语在它的训练语料里
就是普通词。大模型能靠上下文判断出这是 AI 领域术语，并正确译成
「Transformer 架构」「检索增强生成」。

同一套接口可以对接多家（都是 OpenAI 兼容协议）：

* **DeepSeek**  https://api.deepseek.com/v1          model=deepseek-chat
* **硅基流动**   https://api.siliconflow.cn/v1        model=Qwen/Qwen2.5-7B-Instruct
* **OpenAI**    https://api.openai.com/v1           model=gpt-4o-mini
* **本地 Ollama** http://localhost:11434/v1          model=qwen2.5

约定：像官方示例一样只要求 ``/chat/completions`` 兼容，因此换家只需改
``llm_base_url`` 与 ``llm_model``。

设计上的两点取舍：

* 提示词要求**只输出译文**，但模型偶尔会加"译文："前缀或反引号，
  因此响应做一次清洗，避免这些噪声出现在结果窗里；
* 译文不受简繁转换以外的改写，以保持与其它后端一致的输出形态。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from ..languages import AUTO, ZH_HANS, info, normalize_code
from .base import (
    EngineError,
    RateLimitedError,
    TranslateResult,
    TranslationError,
    Translator,
    join_for_request,
    split_text,
)

logger = logging.getLogger(__name__)

#: 非重试类错误：密钥无效、额度用尽等，换后端比原地重试更有意义
FATAL_STATUS = {400, 401, 403, 404, 422}

#: 模型有时会加上的包裹：代码块、引号、"译文："前缀。
#:
#: 开头的围栏要能容忍**字面量 ``\n``**（模型偶尔返回 `` ```\n译文 `` 这种
#: 把反斜杠也写出来的形式），因此用 ``\\?n`` 同时匹配真换行与转义写法；
#: 结尾围栏可能缺失或带前后空白，单独匹配。
_FENCE_OPEN = re.compile(r"^\s*```[a-zA-Z0-9_+-]*\s*(?:\\n)?\s*")
_FENCE_CLOSE = re.compile(r"\s*(?:\\n)?\s*```\s*$")
_PREFIX = re.compile(r"^\s*(译文|翻译|translation|output)\s*[:：]\s*", re.IGNORECASE)

#: 目标语言的写法，让模型明确输出哪种语言。
#: 简体中文特意加一句"不要输出繁体字"：模型默认可能按训练语料输出繁体，
#: 而我们只提供简体中文这一种中文目标。
_TARGET_NAMES = {
    ZH_HANS: "简体中文（不要输出繁体字）",
    "en": "English",
}


def build_prompt(text: str, source: str, target: str) -> List[Dict[str, str]]:
    """构造对话消息。

    明确要求"只输出译文"，否则模型很容易加上"以下是翻译："之类的开场白。
    同时给出源语言线索（auto 时不写死，交给模型判断）。

    目标语言先做一次规范化：旧配置可能还写着 ``zh-Hant``，
    不处理的话提示词会变成"翻译成 Unknown"，模型只能瞎猜。
    """
    resolved = normalize_code(target)
    target_name = _TARGET_NAMES.get(resolved) or info(resolved).label_en or resolved
    if source == AUTO:
        hint = "源语言未知，请自行判断。"
    else:
        hint = f"源语言是 {info(source).label_en}。"

    system = (
        "你是专业的翻译引擎。请把用户给出的文本翻译成"
        f"{target_name}。{hint}\n"
        "要求：\n"
        "1. 只输出译文本身，不要任何解释、前缀、引号或代码块；\n"
        "2. 保留原文的换行结构；\n"
        "3. 保留专有名词、模型名、代码标识符、URL 与数字的原有形式；\n"
        "4. 如果是技术术语，按该领域的通用译法翻译（例如 AI 领域的 "
        "Transformer、RAG、embedding 等）。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]


def clean_output(raw: str) -> str:
    """清掉模型偶尔加上的前缀与代码块包裹。

    模型常见的几种多余包装：
    `` ``` `` 围栏（含写坏成字面量 ``\\n`` 的形式）、语言标注、
    ``译文：`` 前缀。循环清理到稳定，因为可能同时出现多种。
    """
    text = (raw or "").strip()
    if not text:
        return ""
    previous = None
    while previous != text:
        previous = text
        text = _FENCE_OPEN.sub("", text)
        text = _FENCE_CLOSE.sub("", text)
        text = _PREFIX.sub("", text)
        text = text.strip()
    return text


class LlmTranslator(Translator):
    """OpenAI 兼容的大模型翻译后端。"""

    name = "llm"
    display_name = "大模型翻译"

    #: 单次请求的字符上限（模型上下文很大，但仍切分以便流式反馈与容错）
    chunk_size = 3000

    def __init__(
        self,
        client,
        api_key: str = "",
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
        temperature: float = 0.2,
        timeout: float = 30.0,
    ) -> None:
        self.client = client
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "").strip().rstrip("/")
        self.model = (model or "").strip()
        self.temperature = float(temperature)
        self.timeout = timeout

    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        """没配密钥时视为不可用，让服务直接跳过而不是发一次注定失败的请求。"""
        return bool(self.api_key and self.base_url and self.model)

    @property
    def endpoint(self) -> str:
        # 允许用户直接写完整的 /chat/completions 地址
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    # ------------------------------------------------------------------
    def translate(self, text: str, source: str, target: str) -> TranslateResult:
        text = (text or "").strip()
        if not text:
            return TranslateResult(text="", provider=self.name, source_lang=source, target_lang=target)
        if source != AUTO and source == target:
            return TranslateResult(text=text, provider=self.name, source_lang=source, target_lang=target)
        if not self.is_available():
            raise EngineError(
                "大模型后端未配置：请在设置里填写 API Key（以及可选的接口地址与模型名）"
            )

        parts: List[str] = []
        for chunk in split_text(text, self.chunk_size, hard_limit=self.chunk_size):
            parts.append(self._translate_chunk(chunk, source, target))

        # 大模型返回的换行是它自己排的，按原文结构拼接即可
        return TranslateResult(
            text="\n".join(part for part in parts if part).strip(),
            provider=self.name,
            source_lang=source,
            target_lang=target,
        )

    # ------------------------------------------------------------------
    def _translate_chunk(self, chunk: str, source: str, target: str) -> str:
        messages = build_prompt(chunk, source, target)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }

        last_error: Optional[Exception] = None
        for attempt in (1, 2):
            try:
                resp = self.client.post(
                    self.endpoint,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    timeout=self.timeout,
                )
            except TranslationError:
                raise
            except Exception as exc:
                last_error = EngineError(f"大模型请求失败: {exc}")
                if attempt == 1:
                    time.sleep(0.6)
                continue

            status = getattr(resp, "status_code", 0)
            body = getattr(resp, "text", "") or ""

            if status in FATAL_STATUS:
                raise EngineError(self._describe_error(status, body))
            if status == 429:
                raise RateLimitedError(self._describe_error(status, body))
            if status >= 400:
                last_error = EngineError(self._describe_error(status, body))
                if attempt == 1:
                    time.sleep(0.6)
                continue

            content = self._extract_content(body)
            cleaned = clean_output(content)
            if cleaned:
                return cleaned
            last_error = EngineError("大模型返回内容为空")
            if attempt == 1:
                time.sleep(0.6)

        raise last_error or EngineError("大模型翻译失败")

    # ------------------------------------------------------------------
    def _extract_content(self, body: str) -> str:
        """从响应里取 ``choices[0].message.content``，兼容少数变体。

        **内容为空不在这里报错**，而是返回空串：调用方会重试一次，
        仍为空才放弃——模型偶尔会返回空内容，重试往往就好了。
        但"结构不对"（没有 choices）属于配置或协议问题，重试无意义，
        直接抛出以便上层立刻切到别的后端。
        """
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise EngineError(f"大模型返回不是合法 JSON: {body[:120]}") from exc
        if not isinstance(data, dict):
            raise EngineError(f"大模型返回结构异常: {body[:120]}")

        choices = data.get("choices") or []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
            # 少数兼容实现把内容放在 text 字段
            text = choices[0].get("text")
            if isinstance(text, str):
                return text
        raise EngineError(f"大模型返回里找不到译文: {body[:160]}")

    @staticmethod
    def _describe_error(status: int, body: str) -> str:
        detail = ""
        try:
            data = json.loads(body)
            if isinstance(data, dict):
                error = data.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message") or error.get("type") or "")
                elif isinstance(error, str):
                    detail = error
                detail = detail or str(data.get("message") or "")
        except ValueError:
            detail = body[:120]
        hint = {
            401: "（API Key 无效或未授权）",
            403: "（无权限或余额不足）",
            404: "（接口地址或模型名不对）",
            429: "（请求过于频繁或额度用尽）",
        }.get(status, "")
        return f"大模型接口返回 HTTP {status}{hint} {detail}".strip()


__all__ = ["LlmTranslator", "build_prompt", "clean_output"]
