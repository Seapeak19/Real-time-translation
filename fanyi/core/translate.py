"""翻译服务：多后端自动回退 + 内存/磁盘缓存 + 简繁字形归一化。

对外只暴露 :class:`TranslationService`，GUI 与管线层都不需要关心具体后端。
"""

from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..config import Config, app_home
from ..languages import AUTO, ZH_HANS, ZH_HANT, convert_script, from_provider, info
from .base import (
    NoEngineAvailable,
    RateLimitedError,
    TranslateResult,
    TranslationError,
    Translator,
)
from .client import HttpClient
from .engines import (
    BingTranslator,
    GoogleTranslator,
    MyMemoryTranslator,
    YoudaoTranslator,
)

#: 后端名 → 构造函数
ENGINE_FACTORIES: Dict[str, Callable[[HttpClient], Translator]] = {
    "youdao": YoudaoTranslator,
    "mymemory": MyMemoryTranslator,
    "bing": BingTranslator,
    "google": GoogleTranslator,
}

ENGINE_LABELS: Dict[str, str] = {
    "youdao": "有道翻译",
    "mymemory": "MyMemory",
    "bing": "Bing 翻译",
    "google": "Google 免费端点",
}

#: 触发限流后退避的秒数；期间该后端会被暂时跳过
RATE_LIMIT_COOLDOWN = 45.0
#: 其它失败（网络、结构变更）的冷却时间，短一些
ERROR_COOLDOWN = 12.0


# ---------------------------------------------------------------------------
# 缓存
# ---------------------------------------------------------------------------
@dataclass
class _CacheEntry:
    text: str
    provider: str
    source_lang: str


class TranslationCache:
    """两级缓存：内存 LRU + 磁盘 JSON。

    缓存命中的意义不只是"更快"——免费端点普遍限流，
    重复截图同一区域时走缓存可以显著降低触发 429 的概率。
    """

    def __init__(self, path: Path, limit: int = 1000, persist: bool = True) -> None:
        self.path = Path(path)
        self.limit = max(50, limit)
        self.persist = persist
        self._lock = threading.Lock()
        self._data: "OrderedDict[str, _CacheEntry]" = OrderedDict()
        self._load()

    # ------------------------------------------------------------------
    @staticmethod
    def key(text: str, source: str, target: str) -> str:
        raw = f"{source}\x1f{target}\x1f{text}".encode("utf-8")
        return hashlib.sha1(raw).hexdigest()

    def get(self, key: str) -> Optional[_CacheEntry]:
        with self._lock:
            entry = self._data.get(key)
            if entry is not None:
                self._data.move_to_end(key)
            return entry

    def put(self, key: str, entry: _CacheEntry) -> None:
        with self._lock:
            self._data[key] = entry
            self._data.move_to_end(key)
            while len(self._data) > self.limit:
                self._data.popitem(last=False)

    def clear(self) -> int:
        with self._lock:
            count = len(self._data)
            self._data.clear()
        self.flush()
        return count

    def __len__(self) -> int:
        return len(self._data)

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self.persist or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        items = raw.get("entries")
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            key = item.get("k")
            text = item.get("t")
            if not key or not isinstance(text, str):
                continue
            self._data[key] = _CacheEntry(
                text=text,
                provider=str(item.get("p") or ""),
                source_lang=str(item.get("s") or AUTO),
            )

    def flush(self) -> None:
        if not self.persist:
            return
        with self._lock:
            items = [
                {"k": k, "t": v.text, "p": v.provider, "s": v.source_lang}
                for k, v in list(self._data.items())[-self.limit :]
            ]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"entries": items}, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 服务
# ---------------------------------------------------------------------------
class TranslationService:
    """按配置的后端顺序逐个尝试，返回第一个成功的译文。"""

    def __init__(
        self,
        config: Optional[Config] = None,
        client: Optional[HttpClient] = None,
        cache: Optional[TranslationCache] = None,
    ) -> None:
        self.config = config or Config()
        self.client = client or HttpClient(
            timeout=self.config.request_timeout,
            retries=1,
        )
        if cache is None:
            cache = TranslationCache(
                app_home() / "cache.json",
                persist=self.config.cache_enabled,
            )
        self.cache = cache
        self._engines: Dict[str, Translator] = {}
        #: 后端名 → 解禁时间戳（单调时钟）
        self._cooldown: Dict[str, float] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 后端健康度
    # ------------------------------------------------------------------
    def _in_cooldown(self, name: str) -> float:
        """返回该后端剩余的冷却秒数，0 表示可用。"""
        with self._lock:
            until = self._cooldown.get(name)
        if until is None:
            return 0.0
        remain = until - time.monotonic()
        if remain <= 0:
            with self._lock:
                self._cooldown.pop(name, None)
            return 0.0
        return remain

    def _mark_failure(self, name: str, exc: TranslationError) -> None:
        """失败后让该后端短暂退避。

        免费端点普遍限流，如果每次都从头撞一遍，用户体验会退化成"每次都要等超时"。
        退避之后，被限流的后端会被暂时跳过，直接使用可用的那个。
        """
        seconds = RATE_LIMIT_COOLDOWN if isinstance(exc, RateLimitedError) else ERROR_COOLDOWN
        with self._lock:
            self._cooldown[name] = time.monotonic() + seconds

    def _mark_success(self, name: str) -> None:
        with self._lock:
            self._cooldown.pop(name, None)

    def cooldowns(self) -> Dict[str, float]:
        """当前处于冷却中的后端及剩余秒数（供界面展示）。"""
        out: Dict[str, float] = {}
        for name in list(self._cooldown):
            remain = self._in_cooldown(name)
            if remain > 0:
                out[name] = remain
        return out

    def reset_health(self) -> None:
        with self._lock:
            self._cooldown.clear()

    # ------------------------------------------------------------------
    def engine(self, name: str) -> Optional[Translator]:
        """惰性构造后端实例（一个实例可复用连接）。"""
        factory = ENGINE_FACTORIES.get(name)
        if factory is None:
            return None
        if name not in self._engines:
            self._engines[name] = factory(self.client)
        return self._engines[name]

    def engine_names(self) -> List[str]:
        """按配置返回实际会尝试的后端顺序（过滤掉未知项）。"""
        names = [n for n in self.config.translate_engines if n in ENGINE_FACTORIES]
        return names or ["youdao", "mymemory", "bing"]

    def available_engines(self) -> List[str]:
        out = []
        for name in self.engine_names():
            translator = self.engine(name)
            if translator is not None and translator.is_available():
                out.append(name)
        return out

    # ------------------------------------------------------------------
    def translate(
        self,
        text: str,
        target: Optional[str] = None,
        source: Optional[str] = None,
        use_cache: bool = True,
        on_attempt: Optional[Callable[[str], None]] = None,
    ) -> TranslateResult:
        """翻译文本。

        :param text: 待翻译文本（多行会被上游拼成一段）
        :param target: 目标语言内部代码，默认取配置
        :param source: 源语言内部代码，``auto`` 表示自动检测
        :param use_cache: 是否允许读取缓存
        :param on_attempt: 每尝试一个后端前回调其名称，便于 UI 显示进度
        """
        text = (text or "").strip()
        target = target or self.config.target_lang
        source = source or self.config.source_lang

        if not text:
            return TranslateResult(text="", provider="none", source_lang=source, target_lang=target)
        if source != AUTO and source == target:
            return TranslateResult(text=text, provider="none", source_lang=source, target_lang=target)

        key = TranslationCache.key(text, source, target)
        if use_cache and self.config.cache_enabled:
            hit = self.cache.get(key)
            if hit is not None:
                return TranslateResult(
                    text=hit.text,
                    provider=hit.provider,
                    source_lang=hit.source_lang,
                    target_lang=target,
                    from_cache=True,
                    attempts=[],
                )

        errors: Dict[str, str] = {}
        skipped: Dict[str, str] = {}
        attempts: List[str] = []

        candidates: List[str] = []
        for name in self.engine_names():
            remain = self._in_cooldown(name)
            if remain > 0:
                skipped[name] = f"{remain:.0f} 秒后重试"
                continue
            candidates.append(name)
        # 所有后端都在冷却中：直接放行全部，避免用户长时间无法翻译
        if not candidates:
            candidates = self.engine_names()
            skipped.clear()

        # 并发竞速：同时打前几个后端，谁先给出可用译文就用谁。
        # 串行回退的问题是"首选被限流就要逐个等超时"，实测常白等 2~5 秒。
        if self.config.race_engines and len(candidates) > 1:
            result = self._race(candidates, text, source, target, errors, attempts, on_attempt)
            if result is not None:
                return self._finish(result, key, target, attempts)

        for name in candidates:
            translator = self.engine(name)
            if translator is None or not translator.is_available():
                errors[name] = "后端不可用"
                continue
            if on_attempt:
                on_attempt(name)
            try:
                result = translator.translate(text, source, target)
            except TranslationError as exc:
                errors[name] = str(exc)
                self._mark_failure(name, exc)
                continue
            except Exception as exc:  # 第三方库抛出的意外异常也不能中断整体流程
                errors[name] = f"{type(exc).__name__}: {exc}"
                with self._lock:
                    self._cooldown[name] = time.monotonic() + ERROR_COOLDOWN
                continue

            self._mark_success(name)
            return self._finish(result, key, target, attempts)

        problems = dict(errors)
        problems.update({k: f"冷却中（{v}）" for k, v in skipped.items()})
        detail = "；".join(
            f"{ENGINE_LABELS.get(k, k)}: {v}" for k, v in problems.items()
        )
        raise NoEngineAvailable(f"所有翻译后端均失败（{detail}）", problems)

    # ------------------------------------------------------------------
    def _race(
        self,
        candidates: List[str],
        text: str,
        source: str,
        target: str,
        errors: Dict[str, str],
        attempts: List[str],
        on_attempt: Optional[Callable[[str], None]],
    ) -> Optional[TranslateResult]:
        """并发请求多个后端，返回第一个成功的译文；全失败返回 ``None``。

        采用"先冲一组、超时再补一个"的策略：一开始只发前 ``race_size`` 个，
        若 ``race_stagger`` 秒内没人回来，再放一个后端进池。
        这样既避免了把请求量一次性翻几倍（免费接口很容易因此触发限流），
        又不会在首选被限流时干等。

        主线程会阻塞等待（本方法由工作线程调用），因此设有硬超时，
        避免某个后端卡住导致界面一直转圈。
        """
        size = max(1, min(self.config.race_size, len(candidates)))
        stagger = max(0.0, float(self.config.race_stagger))
        results: "queue.Queue[tuple]" = queue.Queue()
        lock = threading.Lock()
        stop = threading.Event()

        def worker(name: str) -> None:
            translator = self.engine(name)
            if translator is None or not translator.is_available():
                results.put((name, None, "后端不可用"))
                return
            if on_attempt:
                on_attempt(name)
            try:
                result = translator.translate(text, source, target)
            except TranslationError as exc:
                results.put((name, None, exc))
            except Exception as exc:
                results.put((name, None, exc))
            else:
                results.put((name, result, None))

        pool: List[threading.Thread] = []

        def launch(name: str) -> None:
            thread = threading.Thread(target=worker, args=(name,), daemon=True)
            thread.start()
            pool.append(thread)

        for name in candidates[:size]:
            launch(name)
        pending = list(candidates[size:])

        deadline = time.monotonic() + max(6.0, float(self.config.request_timeout) * 2)
        started = time.monotonic()
        while True:
            if stop.is_set():
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                with lock:
                    if not errors:
                        errors["(超时)"] = "所有并发后端均超时"
                return None
            try:
                name, result, error = results.get(timeout=min(0.3, remaining))
            except queue.Empty:
                # 到点还没人回来，就再放一个后端进池
                if pending and (time.monotonic() - started) >= stagger * (
                    len(pool) - size + 1
                ):
                    launch(pending.pop(0))
                continue

            if error is not None:
                errors[name] = str(error)
                if isinstance(error, TranslationError):
                    self._mark_failure(name, error)
                else:
                    with self._lock:
                        self._cooldown[name] = time.monotonic() + ERROR_COOLDOWN
                if pending:
                    launch(pending.pop(0))
                continue

            self._mark_success(name)
            stop.set()  # 通知其它仍在跑的后端：不用再等了
            return result

    # ------------------------------------------------------------------
    def _finish(
        self,
        result: TranslateResult,
        key: str,
        target: str,
        attempts: List[str],
    ) -> TranslateResult:
        """归一化结果并写缓存（串行与竞速两条路径共用）。"""
        normalized = self._normalize(result, target, attempts)
        if self.config.cache_enabled:
            self.cache.put(
                key,
                _CacheEntry(
                    text=normalized.text,
                    provider=normalized.provider,
                    source_lang=normalized.source_lang,
                ),
            )
        return normalized

    # ------------------------------------------------------------------
    def _normalize(
        self, result: TranslateResult, target: str, attempts: List[str]
    ) -> TranslateResult:
        """统一源语言代码，并把中文译文/原文归一到用户要求的字形。"""
        provider = result.provider
        source = from_provider(result.source_lang) or AUTO
        text = result.text or ""

        # 后端只区分 zh-CN/zh-TW，字形是否一致取决于它自己；
        # 这里按用户要求的目标字形再校正一次，保证"简体/繁体"选项真的生效。
        if self.config.normalize_script and target in (ZH_HANS, ZH_HANT):
            text = convert_script(text, target)

        result.text = text
        result.source_lang = source
        result.provider = provider
        result.target_lang = target
        result.attempts = list(attempts)
        return result

    # ------------------------------------------------------------------
    def close(self) -> None:
        for translator in self._engines.values():
            try:
                translator.close()
            except Exception:
                pass
        self._engines.clear()
        self.client.close()
        self.cache.flush()
