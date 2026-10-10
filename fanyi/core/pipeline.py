"""截图翻译管线：把"图像 → 文本 → 译文"串成一次可测试的调用。

这一层不依赖 Qt，因此可以在命令行/单测里直接跑，GUI 只是它的调用方。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from ..config import Config
from ..languages import join_lines
from .base import NoEngineAvailable
from .ocr import OcrEngine, OcrError, OcrResult, TextLine, create_engine
from .translate import ENGINE_LABELS as TRANSLATE_LABELS
from .translate import TranslationService

logger = logging.getLogger(__name__)

#: 进度阶段标识。核心层只发标识，**文案由界面层翻译**——
#: 这样核心层不必知道界面语言，也能被命令行/测试独立使用。
OCR_STAGE = "ocr"
TRANSLATE_STAGE = "translate"

#: 进度回调：阶段标识 + 中性文案（界面层通常会按 stage 换成自己的语言）
ProgressFn = Callable[[str, str], None]


class PipelineError(RuntimeError):
    """管线可预期的失败（图片为空、没识别到文字、OCR 不可用…）。

    ``code`` 是稳定的机器可读标识，界面层据此选翻译键；
    ``str(exc)`` 仍是可读的中文，供命令行与日志使用。
    """

    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class PipelineResult:
    """一次完整流程的结果。"""

    #: 用于翻译的源文本（多行已按语言习惯拼接）
    source_text: str
    translation: str
    source_lang: str
    target_lang: str
    provider: str = ""
    from_cache: bool = False
    ocr_engine: str = ""
    ocr_lines: List[TextLine] = field(default_factory=list)
    ocr_confidence: float = 0.0
    ocr_seconds: float = 0.0
    translate_seconds: float = 0.0
    total_seconds: float = 0.0


class TranslationPipeline:
    """持有 OCR 引擎与翻译服务，供多次调用复用（模型只加载一次）。"""

    def __init__(
        self,
        config: Config,
        translation: Optional[TranslationService] = None,
    ) -> None:
        self.config = config
        self.translation = translation or TranslationService(config)
        self._ocr: Optional[OcrEngine] = None
        self._ocr_name: str = ""

    # ------------------------------------------------------------------
    @property
    def ocr(self) -> OcrEngine:
        name = (self.config.ocr_engine or "rapidocr").strip().lower()
        if self._ocr is None or self._ocr_name != name:
            if self._ocr is not None:
                try:
                    self._ocr.close()
                except Exception:
                    pass
            self._ocr = create_engine(name)
            self._ocr_name = name
        return self._ocr

    def warmup(self) -> None:
        """提前加载 OCR 模型，避免用户第一次截图时等待。"""
        try:
            self.ocr.warmup()
        except Exception as exc:
            logger.warning("OCR 预热失败: %s", exc)

    # ------------------------------------------------------------------
    def recognize(self, image, on_progress: Optional[ProgressFn] = None) -> OcrResult:
        """只做 OCR。"""
        if on_progress:
            on_progress(OCR_STAGE, "正在识别文字…")
        engine = self.ocr
        if not engine.is_ready():
            raise PipelineError(
                "OCR 引擎不可用：缺少依赖 rapidocr-onnxruntime。\n"
                "请在项目目录执行：.venv\\Scripts\\python -m pip install rapidocr-onnxruntime"
            )
        try:
            result = engine.recognize(image)
        except OcrError as exc:
            raise PipelineError(str(exc)) from exc

        # 过滤低置信度行
        threshold = float(self.config.ocr_min_confidence or 0.0)
        if threshold > 0:
            result.lines = [l for l in result.lines if l.confidence >= threshold]
        return result

    # ------------------------------------------------------------------
    def run(
        self,
        image,
        on_progress: Optional[ProgressFn] = None,
        use_cache: bool = True,
    ) -> PipelineResult:
        """完整流程：图像 → OCR → 翻译。"""
        started = time.perf_counter()

        # 注意：OCR 阶段的进度由 recognize() 自己上报，这里不要再发一次，
        # 否则界面会连续收到两条"正在识别文字…"（表现为状态文字闪一下）
        ocr_result = self.recognize(image, on_progress)
        source_text = join_lines([l.text for l in ocr_result.lines], self.config.source_lang)

        if not source_text.strip():
            raise PipelineError("未识别到文字，请框选包含清晰文字的区域后重试", code="no_text")

        if on_progress:
            on_progress(TRANSLATE_STAGE, "正在翻译…")

        translate_started = time.perf_counter()
        try:
            result = self.translation.translate(
                source_text,
                target=self.config.target_lang,
                source=self.config.source_lang,
                use_cache=use_cache,
                # 每次切换后端只报告"阶段 + 后端名"，界面自己决定怎么显示
                on_attempt=lambda name: on_progress(TRANSLATE_STAGE, name)
                if on_progress
                else None,
            )
        except NoEngineAvailable as exc:
            raise PipelineError(
                f"翻译失败：所有后端均不可用。\n{exc}\n"
                "请检查网络连接，或在设置里调整后端顺序。",
                code="all_backends_failed",
            ) from exc

        translate_seconds = time.perf_counter() - translate_started
        return PipelineResult(
            source_text=source_text,
            translation=result.text,
            source_lang=result.source_lang,
            target_lang=self.config.target_lang,
            provider=TRANSLATE_LABELS.get(result.provider, result.provider),
            from_cache=result.from_cache,
            ocr_engine=ocr_result.engine,
            ocr_lines=ocr_result.lines,
            ocr_confidence=ocr_result.mean_confidence,
            ocr_seconds=ocr_result.elapsed,
            translate_seconds=translate_seconds,
            total_seconds=time.perf_counter() - started,
        )

    # ------------------------------------------------------------------
    def close(self) -> None:
        if self._ocr is not None:
            try:
                self._ocr.close()
            except Exception:
                pass
            self._ocr = None
        self.translation.close()


def _join_lines(lines: List[str], source_lang: str) -> str:
    """兼容旧调用点：真正的实现在 :func:`fanyi.languages.join_lines`。"""
    return join_lines(lines, source_lang)


__all__ = ["PipelineError", "PipelineResult", "TranslationPipeline"]
