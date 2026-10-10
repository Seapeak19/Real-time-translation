"""OCR 适配层：把"图片 → 文本行"的能力抽象出来。

首个实现是本地离线的 RapidOCR（ONNX Runtime，PNG 模型支持中简/中繁/英），
不联网、无次数限制；后续要接云端引擎只需实现 :class:`OcrEngine`。
"""

from __future__ import annotations

import logging
import re
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

import numpy as np

from ..languages import has_cjk

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class TextLine:
    """一行识别结果。"""

    text: str
    confidence: float = 1.0
    #: 四点多边形 [[x, y], ...]，左上角起顺时针
    box: Optional[List[List[float]]] = None

    @property
    def top(self) -> float:
        if not self.box:
            return 0.0
        return min(p[1] for p in self.box)

    @property
    def left(self) -> float:
        if not self.box:
            return 0.0
        return min(p[0] for p in self.box)


@dataclass
class OcrResult:
    """一次识别的完整结果。"""

    lines: List[TextLine] = field(default_factory=list)
    engine: str = ""
    #: 原图尺寸 (width, height)
    image_size: tuple = (0, 0)
    elapsed: float = 0.0

    @property
    def text(self) -> str:
        """按版面顺序整理出的完整文本。

        同一个逻辑行可能被 OCR 切成多个文本框，直接换行连接会破坏句子
        （中文被拆成"翻 / 译"、英文被拆成两个词），因此这里先按行分组，
        再决定行内如何拼接：

        * 行内含有中日韩文字 → 直接相连（避免"翻 译 软 件"式噪声），
          相接之后再跑一次中英空格归一化，处理"中文框 + 英文框"这种混排
        * 纯拉丁文本 → 用空格相连，补回行框之间被吞掉的词间空格
        """
        groups = _group_lines(self.lines)
        if not groups:
            return ""
        rendered = []
        for group in groups:
            parts = [line.text for line in group if line.text and line.text.strip()]
            if not parts:
                continue
            if any(has_cjk(part) for part in parts):
                rendered.append(normalize_cjk_spacing("".join(parts)))
            else:
                rendered.append(" ".join(part.strip() for part in parts))
        return "\n".join(rendered)

    @property
    def raw_text(self) -> str:
        """不做行内合并的原始文本，每个文本框一行（调试用）。"""
        return "\n".join(line.text for line in self.lines if line.text)

    @property
    def is_empty(self) -> bool:
        return not any(line.text.strip() for line in self.lines)

    @property
    def mean_confidence(self) -> float:
        if not self.lines:
            return 0.0
        return sum(l.confidence for l in self.lines) / len(self.lines)


class OcrError(RuntimeError):
    """OCR 失败（模型缺失、依赖未装、图片不可读等）。"""


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------
class OcrEngine(ABC):
    """OCR 引擎接口。"""

    name: str = "base"
    display_name: str = "未命名引擎"

    @abstractmethod
    def recognize(self, image: np.ndarray) -> OcrResult:
        """识别一张 BGR 或灰度图（numpy 数组）。"""

    def is_ready(self) -> bool:
        """引擎依赖是否就绪（模型文件、运行时库）。"""
        return True

    def warmup(self) -> None:
        """预热：提前加载模型，避免首次截图卡顿。"""

    def close(self) -> None:
        """释放资源。"""


# ---------------------------------------------------------------------------
# RapidOCR 实现
# ---------------------------------------------------------------------------
class RapidOcrEngine(OcrEngine):
    """基于 rapidocr-onnxruntime 的本地离线引擎。

    模型在首次 :meth:`recognize` 或显式 :meth:`warmup` 时加载（约 1~3 秒），
    之后常驻内存，单次识别在百毫秒级。
    """

    name = "rapidocr"
    display_name = "RapidOCR（本地离线）"

    def __init__(self) -> None:
        self._engine: Any = None
        self._lock = threading.Lock()
        self._load_error: Optional[str] = None

    # ------------------------------------------------------------------
    def is_ready(self) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except Exception as exc:  # pragma: no cover - 取决于安装环境
            self._load_error = str(exc)
            return False
        return True

    def _ensure_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        with self._lock:
            if self._engine is not None:
                return self._engine
            try:
                from rapidocr_onnxruntime import RapidOCR
            except Exception as exc:
                self._load_error = str(exc)
                raise OcrError(
                    "未安装 OCR 依赖 rapidocr-onnxruntime，请运行:\n"
                    "  .venv\\Scripts\\python -m pip install rapidocr-onnxruntime"
                ) from exc
            try:
                self._engine = RapidOCR(**self._engine_kwargs())
            except Exception as exc:
                self._load_error = str(exc)
                raise OcrError(f"OCR 模型加载失败: {exc}") from exc
            logger.info("RapidOCR 模型加载完成（参数 %s）", self._engine_kwargs())
        return self._engine

    @staticmethod
    def _engine_kwargs() -> Dict[str, Any]:
        """构造参数。

        ``use_cls=False`` 关掉**文字方向分类器**：它的作用是把倒置的文字转正，
        而桌面截图里的文字几乎总是横向的，这一步属于白跑。
        实测（``scripts/benchmark_ocr_options.py``，三组合成图）：

        ==========================  ==========  ==========
        配置                         中位时延     准确度
        ==========================  ==========  ==========
        默认（use_cls=true）          2.08s       100%
        关方向分类                    1.71s       100%
        侧长上限调到 1280             3.17s       100%
        ==========================  ==========  ==========

        因此关掉分类器（省约 18% 且准确度不变），而 ``limit_side_len``
        保持默认 736 —— 调大只会更慢，准确度没有提升。
        """
        return {"use_cls": False}

    def warmup(self) -> None:
        try:
            self._ensure_engine()
        except OcrError as exc:
            logger.warning("OCR 预热失败: %s", exc)

    # ------------------------------------------------------------------
    def recognize(self, image: np.ndarray) -> OcrResult:
        import time

        if image is None or getattr(image, "size", 0) == 0:
            raise OcrError("待识别图片为空")

        engine = self._ensure_engine()
        height, width = image.shape[:2]

        started = time.perf_counter()
        try:
            raw = engine(image)
        except Exception as exc:
            raise OcrError(f"OCR 识别失败: {exc}") from exc
        elapsed = time.perf_counter() - started

        lines = self._parse(raw, width, height)
        return OcrResult(
            lines=lines,
            engine=self.name,
            image_size=(width, height),
            elapsed=elapsed,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _parse(raw: Any, width: int, height: int) -> List[TextLine]:
        """兼容 RapidOCR 的多种返回形式。

        - ``(result, elapse)`` 二元组，result 为 ``[[box, text, score], ...]``
        - 直接返回 ``[[box, text, score], ...]``
        - ``None`` / 空列表表示没有识别到文字
        """
        if raw is None:
            return []
        if isinstance(raw, tuple) and len(raw) == 2 and isinstance(raw[0], (list, type(None))):
            raw = raw[0]
        if raw is None:
            return []
        if not isinstance(raw, (list, tuple)):
            logger.warning("无法识别的 OCR 返回类型: %s", type(raw))
            return []

        lines: List[TextLine] = []
        for item in raw:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            box, text = item[0], item[1]
            score = 1.0
            if len(item) >= 3:
                try:
                    score = float(item[2])
                except (TypeError, ValueError):
                    score = 1.0
            text = str(text).strip()
            if not text:
                continue
            # 在这里就补回中英之间的空格，而不是只在 OcrResult.text 里补：
            # 管线用的是 lines[].text，如果两种取法结果不一致，
            # 就会出现"界面上有空格、送进翻译的却没有"这种难查的不一致。
            text = normalize_cjk_spacing(text)
            coords: Optional[List[List[float]]] = None
            try:
                coords = [[float(p[0]), float(p[1])] for p in box]
            except (TypeError, ValueError, IndexError):
                coords = None
            lines.append(TextLine(text=text, confidence=score, box=coords))

        return _sort_lines(lines, height)


def normalize_cjk_spacing(text: str) -> str:
    """在中文与紧邻的英文/数字之间补一个空格。

    OCR 文本框只覆盖墨迹，中文与英文之间的空隙往往被吞掉，
    结果是 ``截图翻译OCR识别`` 这种连写；补上空格后译文质量会明显更好。
    标点（括号、引号、顿号等）周围的空隙属于排版习惯，保持原样。
    """
    if not text or not has_cjk(text):
        return text

    # 1) 在 CJK 与 ASCII 字母数字的交界处补空格
    spaced = re.sub(r"(?<=[\u3400-\u4dbf\u4e00-\u9fff])(?=[A-Za-z0-9])", " ", text)
    spaced = re.sub(r"(?<=[A-Za-z0-9])(?=[\u3400-\u4dbf\u4e00-\u9fff])", " ", spaced)

    # 2) 收起标点两侧多补出来的空格
    spaced = re.sub(r"([（(【\[「『《])\s+", r"\1", spaced)
    spaced = re.sub(r"\s+([）)】\]」』》])", r"\1", spaced)
    spaced = re.sub(r"\s+([，。、；：！？])", r"\1", spaced)
    return re.sub(r" {2,}", " ", spaced).strip()


def _row_tolerance(lines: Sequence[TextLine], image_height: int = 0) -> float:
    """同一行的判定容差：取行高的一定比例，并设下限。

    行高差异很大的版面（标题 + 正文）用平均行高会误判，
    这里用各行高度的中位数，避免被个别大标题带偏。
    """
    heights = []
    for line in lines:
        if line.box:
            ys = [p[1] for p in line.box]
            heights.append(abs(max(ys) - min(ys)))
    if not heights:
        return max(6.0, image_height * 0.01)
    heights.sort()
    median = heights[len(heights) // 2]
    return max(6.0, median * 0.6)


def _group_lines(lines: Sequence[TextLine]) -> List[List[TextLine]]:
    """把文本框按"行"分组，每组内左右排序，组间上下排序。

    OCR 引擎通常已按阅读顺序返回，但多栏/多行场景下偶尔会错乱，
    分组后重排可以保证阅读顺序，也让行内拼接可以按语言选择连接方式。
    """
    if not lines:
        return []

    # 没有坐标信息时无法分组，每个框各自成行
    if all(line.box is None for line in lines):
        return [[line] for line in lines]

    tolerance = _row_tolerance(lines)
    ordered = sorted(lines, key=lambda l: (l.top, l.left))

    rows: List[List[TextLine]] = []
    for line in ordered:
        if rows and abs(line.top - rows[-1][0].top) <= tolerance:
            rows[-1].append(line)
        else:
            rows.append([line])

    for row in rows:
        row.sort(key=lambda l: l.left)
    return rows


def _sort_lines(lines: Sequence[TextLine], image_height: int) -> List[TextLine]:
    """按版面顺序重排：先上下（同一行容差内视为一行），再左右。"""
    return [line for row in _group_lines(lines) for line in row]


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------
ENGINE_LABELS = {
    "rapidocr": "RapidOCR（本地离线，中简/中繁/英）",
}


def create_engine(name: str) -> OcrEngine:
    """按名字创建 OCR 引擎实例。"""
    key = (name or "rapidocr").strip().lower()
    if key == "rapidocr":
        return RapidOcrEngine()
    raise OcrError(f"未知的 OCR 引擎: {name!r}")


__all__ = [
    "OcrEngine",
    "OcrError",
    "OcrResult",
    "RapidOcrEngine",
    "TextLine",
    "create_engine",
    "ENGINE_LABELS",
]