"""翻服务的端到端验证：多后端回退、退避冷却、缓存、简繁字形。

用法::

    .venv\\Scripts\\python scripts\\test_translate_service.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fanyi.config import Config  # noqa: E402
from fanyi.core.translate import ENGINE_LABELS, TranslationService  # noqa: E402

failures = []


def check(condition: bool, title: str, detail: str = "") -> None:
    mark = "OK  " if condition else "FAIL"
    print(f"  [{mark}] {title}" + (f"\n         {detail}" if detail else ""))
    if not condition:
        failures.append(title)


def main() -> int:
    config = Config()
    config.request_timeout = 8.0
    config.cache_enabled = True
    service = TranslationService(config)
    # 用独立缓存文件，避免污染用户缓存
    from fanyi.core.translate import TranslationCache

    service.cache = TranslationCache(ROOT / "testdata" / "test_cache.json", limit=200)

    print("默认后端顺序:", " → ".join(service.engine_names()))
    print()

    # --- 1. 英 → 简中 ---
    print("1) 英 → 简中")
    started = time.perf_counter()
    try:
        result = service.translate(
            f"Service check {time.time_ns() % 100000}: the deployment finished ahead of schedule.",
            target="zh-Hans",
            source="auto",
            use_cache=False,
        )
        elapsed = time.perf_counter() - started
        check(bool(result.text), "拿到译文", f"{ENGINE_LABELS.get(result.provider)} · {elapsed:.2f}s · {result.text[:70]}")
        check(result.source_lang == "en", "源语言判定为英语", result.source_lang)
    except Exception as exc:
        check(False, "英 → 简中", f"{type(exc).__name__}: {exc}")

    # --- 2. 中 → 英 ---
    print("\n2) 中 → 英")
    try:
        result = service.translate(
            f"第 {time.time_ns() % 1000} 次测试：这个工具在弱网环境下也能自动切换翻译后端。",
            target="en",
            source="auto",
            use_cache=False,
        )
        check(bool(result.text), "拿到译文", f"{ENGINE_LABELS.get(result.provider)} · {result.text[:70]}")
    except Exception as exc:
        check(False, "中 → 英", f"{type(exc).__name__}: {exc}")

    # --- 3. 繁体字形归一 ---
    print("\n3) 繁体字形归一（目标 zh-Hant）")
    try:
        result = service.translate(
            f"Traditional check {time.time_ns() % 100000}: the software runs in the background.",
            target="zh-Hant",
            source="auto",
            use_cache=False,
        )
        traditional_chars = set("軟體翻譯識別這个們為")
        has_traditional = any(ch in result.text for ch in "軟體譯識這們為")
        check(has_traditional, "译文包含繁体字形", f"{result.text[:70]}")
    except Exception as exc:
        check(False, "繁体字形归一", f"{type(exc).__name__}: {exc}")

    # --- 4. 缓存命中 ---
    print("\n4) 缓存命中")
    probe = f"Cache probe {time.time_ns() % 100000}: consistent results should come from cache."
    try:
        first = service.translate(probe, target="zh-Hans", source="auto", use_cache=True)
        started = time.perf_counter()
        second = service.translate(probe, target="zh-Hans", source="auto", use_cache=True)
        elapsed = time.perf_counter() - started
        check(second.from_cache, "第二次命中缓存", f"{elapsed * 1000:.2f}ms")
        check(first.text == second.text, "两次译文一致")
    except Exception as exc:
        check(False, "缓存命中", f"{type(exc).__name__}: {exc}")

    # --- 5. 限流退避 ---
    print("\n5) 限流退避冷却（模拟 429）")
    from fanyi.core.base import RateLimitedError

    service._mark_failure("bing", RateLimitedError("模拟限流"))
    remaining = service.cooldowns()
    check(remaining.get("bing", 0) > 0, "失败后端进入冷却", f"bing 剩余 {remaining.get('bing', 0):.1f}s")
    service.reset_health()
    check(not service.cooldowns(), "reset_health 可清除冷却")

    # --- 6. 全部后端失败时的报错信息 ---
    print("\n6) 全后端失败时的报错可读性")
    config2 = Config()
    config2.translate_engines = ["google"]
    config2.request_timeout = 1.0
    service2 = TranslationService(config2)
    service2.cache = TranslationCache(ROOT / "testdata" / "test_cache2.json", limit=10)
    try:
        service2.translate("connectivity probe", target="zh-Hans", use_cache=False)
        print("  [OK  ] google 竟然可用（当前网络能直连）")
    except Exception as exc:
        message = str(exc)
        check("所有翻译后端均失败" in message, "报错包含可读原因", message[:150])
    service2.close()

    # --- 7. 引擎隔离：某个后端抛异常不影响整体 ---
    print("\n7) 后端异常隔离")
    from fanyi.core.base import TranslateResult

    class BoomEngine:
        name = "boom"
        display_name = "总是失败"
        is_available = lambda self: True
        def translate(self, text, source, target):
            raise RuntimeError("模拟第三方库崩溃")

    from fanyi.core import translate as translate_module

    translate_module.ENGINE_FACTORIES["boom"] = lambda client: BoomEngine()
    config3 = Config()
    config3.translate_engines = ["boom", "mymemory"]
    service3 = TranslationService(config3)
    service3.cache = TranslationCache(ROOT / "testdata" / "test_cache3.json", limit=10)
    try:
        result = service3.translate(
            f"Isolation check {time.time_ns() % 100000}: fallback should still work.",
            target="zh-Hans",
            use_cache=False,
        )
        check(result.provider == "mymemory", "坏后端被跳过，好后端接管", f"provider={result.provider}")
    except Exception as exc:
        check(False, "后端异常隔离", f"{type(exc).__name__}: {exc}")
    service3.close()
    translate_module.ENGINE_FACTORIES.pop("boom", None)

    service.close()

    print()
    if failures:
        print(f"共 {len(failures)} 项未通过：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
