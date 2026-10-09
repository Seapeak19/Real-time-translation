"""极简 HTTP 客户端：统一 UA、超时、重试与错误分类。

免费翻译端点常见失效模式是限流（429/403）与瞬时网络错误，
这里统一归一化成 TranslationError 的子类，由 TranslationService 决定是否换后端重试。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

#: 这些状态码意味着"换一个后端可能就好了"
FALLBACK_STATUS = {403, 408, 429, 456, 500, 502, 503, 504}


class HttpClient:
    """带重试的 requests 会话封装。"""

    def __init__(
        self,
        timeout: float = 8.0,
        retries: int = 2,
        backoff: float = 0.6,
        user_agent: str = DEFAULT_UA,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.timeout = timeout
        self.retries = max(0, retries)
        self.backoff = backoff
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )

    # ------------------------------------------------------------------
    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self._request("POST", url, **kwargs)

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        from .base import EngineError, NetworkError, RateLimitedError

        kwargs.setdefault("timeout", self.timeout)
        last_error: Optional[Exception] = None

        for attempt in range(self.retries + 1):
            try:
                resp = self.session.request(method, url, **kwargs)
            except requests.exceptions.Timeout as exc:
                last_error = NetworkError(f"请求超时（{self.timeout}s）: {exc}")
            except requests.exceptions.RequestException as exc:
                last_error = NetworkError(f"网络错误: {exc}")
            else:
                if resp.status_code < 400:
                    return resp
                if resp.status_code in (429, 456):
                    last_error = RateLimitedError(
                        f"触发限流 HTTP {resp.status_code}"
                    )
                elif resp.status_code in FALLBACK_STATUS:
                    last_error = EngineError(f"服务返回 HTTP {resp.status_code}")
                else:
                    # 4xx 多为请求本身有问题，重试无意义
                    raise EngineError(f"请求被拒绝 HTTP {resp.status_code}")

            if attempt < self.retries:
                time.sleep(self.backoff * (2**attempt))

        assert last_error is not None
        raise last_error

    # ------------------------------------------------------------------
    @staticmethod
    def json(resp: requests.Response) -> Any:
        from .base import EngineError

        try:
            return resp.json()
        except ValueError as exc:
            raise EngineError(f"返回内容不是合法 JSON: {exc}") from exc

    @staticmethod
    def jsonp(text: str) -> Dict[str, Any]:
        """解析 Google 免费端点返回的 ``/*...*/json`` 形式内容。"""
        import json

        from .base import EngineError

        body = text.strip()
        if body.startswith("/**/"):
            body = body[4:]
        start = body.find("{")
        end = body.rfind("}")
        if start < 0 or end <= start:
            raise EngineError("返回内容中找不到 JSON 主体")
        try:
            return json.loads(body[start : end + 1])
        except ValueError as exc:
            raise EngineError(f"JSON 解析失败: {exc}") from exc
