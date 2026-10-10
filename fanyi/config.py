"""应用配置：默认值、加载、保存、路径解析。

配置文件位置: %APPDATA%\\fanyi\\config.json （可用环境变量 FANYI_HOME 覆盖根目录）
"""

from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .languages import EN, ZH_HANS

APP_NAME = "fanyi"
APP_TITLE = "翻译"
APP_VERSION = "0.2.0"

#: 允许的热键修饰键写法（用户输入会被规范化）
DEFAULT_HOTKEY = "ctrl+alt+z"
DEFAULT_REPEAT_HOTKEY = "ctrl+alt+x"

#: 默认后端顺序（按实测时延与稳定性排序，可用 scripts/probe_engines.py 复测）
DEFAULT_ENGINES = ["youdao", "mymemory", "bing", "google"]
#: 早期版本的默认顺序，加载旧配置时自动升级
LEGACY_ENGINES = [
    ["google", "mymemory", "bing"],
    ["google", "bing", "mymemory"],
]


def app_home() -> Path:
    """返回应用数据目录，必要时创建。"""
    override = os.environ.get("FANYI_HOME")
    if override:
        root = Path(override)
    else:
        base = os.environ.get("APPDATA") or str(Path.home())
        root = Path(base) / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def config_path() -> Path:
    return app_home() / "config.json"


def history_path() -> Path:
    return app_home() / "history.json"


@dataclass
class Config:
    """用户配置。字段名即 JSON 键名，新增字段请给默认值以保证向后兼容。"""

    # --- 语言 ---
    target_lang: str = ZH_HANS
    source_lang: str = "auto"
    #: 显示译文时是否按目标字形做本地转换（简繁）
    normalize_script: bool = True

    # --- 热键 ---
    hotkey: str = DEFAULT_HOTKEY
    repeat_hotkey: str = DEFAULT_REPEAT_HOTKEY
    hotkey_enabled: bool = True

    # --- OCR ---
    ocr_engine: str = "rapidocr"
    #: 是否启用中简/中繁/英 全量模型（False 时只加载中英模型，更省内存）
    ocr_use_full_model: bool = True
    #: 识别前按倍数放大图片，小字场景有效
    ocr_scale: float = 1.0
    #: 低于该置信度的结果丢弃
    ocr_min_confidence: float = 0.45

    # --- 翻译 ---
    #: 后端优先级，按顺序尝试
    translate_engines: List[str] = field(default_factory=lambda: list(DEFAULT_ENGINES))
    request_timeout: float = 8.0
    max_chars_per_request: int = 1800
    cache_enabled: bool = True

    # --- 界面 ---
    result_always_on_top: bool = True
    result_auto_copy: bool = False
    result_font_size: int = 12
    show_original: bool = True
    play_sound: bool = False
    history_limit: int = 200

    # --- 其它 ---
    first_run_done: bool = False

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Config":
        """用字典构造配置，忽略未知键，缺失键使用默认值。"""
        known = {f.name: f for f in dataclasses.fields(cls)}
        kwargs: Dict[str, Any] = {}
        for key, value in (raw or {}).items():
            spec = known.get(key)
            if spec is None:
                continue
            kwargs[key] = _coerce(value, spec.type, spec.default)

        # 老配置里的默认后端顺序（当时 Google 排第一，但在部分网络下不可达）自动升级
        engines = kwargs.get("translate_engines")
        if engines and list(engines) in LEGACY_ENGINES:
            kwargs["translate_engines"] = list(DEFAULT_ENGINES)
        return cls(**kwargs)

    # ------------------------------------------------------------------
    # 读写
    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        target = Path(path) if path else config_path()
        if not target.exists():
            return cls()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            # 配置损坏时回到默认值，并把坏文件留档
            try:
                target.replace(target.with_suffix(".json.bad"))
            except Exception:
                pass
            return cls()
        if not isinstance(raw, dict):
            return cls()
        return cls.from_dict(raw)

    def save(self, path: Optional[Path] = None) -> None:
        target = Path(path) if path else config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(target)

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------
    def set_target(self, code: str) -> bool:
        """切换目标语言，返回是否发生变化。"""
        if code == self.target_lang:
            return False
        self.target_lang = code
        return True

    def set_source(self, code: str) -> bool:
        if code == self.source_lang:
            return False
        self.source_lang = code
        return True

    def swap_languages(self) -> bool:
        """源/目标互换；源语言为"自动检测"时不做任何事。"""
        if self.source_lang == "auto":
            return False
        self.source_lang, self.target_lang = self.target_lang, self.source_lang
        return True


def _coerce(value: Any, type_hint: Any, default: Any) -> Any:
    """把 JSON 里读到的值转成字段期望的类型，类型不符时用默认值。"""
    hint = str(type_hint)
    try:
        if hint.startswith("bool"):
            return bool(value) if isinstance(value, (bool, int)) else default
        if hint.startswith("int"):
            return int(value)
        if hint.startswith("float"):
            return float(value)
        if hint.startswith("str"):
            return str(value)
        if hint.startswith("List") or hint.startswith("list"):
            if isinstance(value, list):
                return [str(v) for v in value]
            return default
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


#: 供 UI 选择的 OCR 引擎
OCR_ENGINES = [
    ("rapidocr", "RapidOCR（本地离线，中简/中繁/英）"),
]

#: 供 UI 选择的翻译后端
TRANSLATE_ENGINES = [
    ("youdao", "有道翻译（最快，无需 Key）"),
    ("mymemory", "MyMemory（免费额度，较稳定）"),
    ("bing", "Bing 翻译（无需 Key，需先取令牌）"),
    ("google", "Google 免费端点（部分网络不可达）"),
]
