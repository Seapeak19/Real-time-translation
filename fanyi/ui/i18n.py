"""界面多语言：英语 / 简体中文 / 繁体中文。

设计取舍
--------

**源码里的中文原文就是翻译键**（gettext 的 msgid 风格）：

* 不需要额外维护一份 msgid 清单，改代码时不会出现"键还在、文案已经变了"的脱节；
* 漏翻的字符串会自然回退显示中文原文，而不是显示 ``settings.language.title``
  这种占位符——漏翻只是不够完美，不会变成看不懂的东西；
* 简体中文是作者语言，因此 zh-Hans 目录为空，直接返回原文。

繁体目录由 :func:`fanyi.languages.convert_script` 在加载时自动生成，
既省掉一份人工维护的重复数据，也保证与截图翻译用的简繁转换规则一致。

用法::

    from .translations import tr
    label.setText(tr("源语言"))
    label.setText(tr("{n} 条记录").format(n=3))   # 需要插值时用 format
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from ..languages import ZH_HANS, ZH_HANT, convert_script, set_ui_language_getter

logger = logging.getLogger(__name__)

# 让语言显示名（``lang_label``）跟随界面语言：核心层不能反向导入 ui，
# 因此把"当前界面语言"的取值函数注入进去。
set_ui_language_getter(lambda: current_language())

EN = "en"

#: 界面语言可选值（顺序即设置界面里的展示顺序）
UI_LANGUAGES = (ZH_HANS, ZH_HANT, EN)

#: 界面语言自身的名称，按**当前界面语言**分语言给出。
#: 不能只存一份中文名：英文界面下如果还显示「简体中文」，就成了半中半英。
UI_LANGUAGE_NAMES = {
    ZH_HANS: {
        ZH_HANS: "简体中文",
        ZH_HANT: "繁体中文",
        "en": "英语",
    },
    ZH_HANT: {
        ZH_HANS: "簡體中文",
        ZH_HANT: "繁體中文",
        "en": "英語",
    },
    "en": {
        ZH_HANS: "Chinese (Simplified)",
        ZH_HANT: "Chinese (Traditional)",
        "en": "English",
    },
}

# ---------------------------------------------------------------------------
# 英语目录：键为源码中的简体中文原文
# ---------------------------------------------------------------------------
ENGLISH: Dict[str, str] = {
    # ===== 应用与托盘 =====
    "翻译": "Translate",
    "截图翻译": "Screenshot translate",
    "截图翻译（{hotkey}）": "Screenshot translate ({hotkey})",
    "重译上次区域": "Retranslate last area",
    "目标语言": "Target language",
    "源语言": "Source language",
    "自动检测": "Auto detect",
    "简体中文": "Chinese (Simplified)",
    "繁体中文": "Chinese (Traditional)",
    "英语": "English",
    "翻译历史…": "History…",
    "设置…": "Settings…",
    "清空翻译缓存": "Clear translation cache",
    "退出": "Quit",
    "翻译历史": "Translation history",
    "设置": "Settings",
    "未启用": "Disabled",
    "未设置": "Not set",
    "已退出（code={code}）": "Exited (code={code})",
    "当前系统不支持托盘图标，程序无法常驻运行。": (
        "This system does not support tray icons, so the app cannot run in the background."
    ),
    "已在后台运行，按 {hotkey} 开始截图翻译。": (
        "Running in the background. Press {hotkey} to translate a screenshot."
    ),
    "程序已在运行，按热键开始截图翻译。": (
        "The app is already running. Press the hotkey to translate a screenshot."
    ),
    "{name} 已在运行（托盘图标），已唤起原实例。": (
        "{name} is already running (tray icon); brought the existing instance to the front."
    ),
    "热键注册失败": "Hotkey registration failed",
    "热键注册失败：{reason}": "Hotkey registration failed: {reason}",
    "快捷键已重新注册。": "Hotkeys re-registered.",
    "设置已保存并生效。": "Settings saved and applied.",
    "设置已保存。": "Settings saved.",
    "已清空 {count} 条历史记录。": "Cleared {count} history entries.",
    "已清空翻译缓存（{count} 条）。": "Cleared the translation cache ({count} entries).",
    "配置目录：{path}": "Config folder: {path}",

    # ===== 设置窗口：导航与页头 =====
    "语言": "Language",
    "快捷键": "Hotkeys",
    "识别（OCR）": "OCR",
    "翻译": "Translation",
    "界面": "Interface",
    "开始截图翻译": "Translate a screenshot now",
    "立即进入框选模式（与全局热键等效）": (
        "Enter region-selection mode now (same as the global hotkey)"
    ),
    "关闭窗口": "Close window",
    "设置 · 标题": "Settings",

    # ===== 语言页 =====
    "决定把屏幕上的文字翻译成哪种语言。支持简体中文、繁体中文、英语互译。": (
        "Choose which language the text on your screen is translated into. "
        "Simplified Chinese, Traditional Chinese and English are all supported."
    ),
    "翻译语言": "Translation languages",
    "自动检测（由引擎判断）": "Auto detect (decided by the engine)",
    "「自动检测」由翻译引擎判断原文语言": (
        "\"Auto detect\" lets the engine decide the source language"
    ),
    "译文输出成这个语言": "The translation is produced in this language",
    "⇄ 互换源语言与目标语言": "⇄ Swap source and target",
    "互换源语言与目标语言": "Swap source and target",
    "常用目标：": "Quick target:",
    "自动统一简繁字形（目标为中文时把译文校正为简体/繁体）": (
        "Normalize Chinese script (correct the translation to Simplified/Traditional)"
    ),
    "无法互换": "Cannot swap",
    "源语言是「自动检测」时没有可互换的语言。\n请先把源语言指定为具体语言。": (
        "There is nothing to swap while the source language is \"Auto detect\".\n"
        "Please set a concrete source language first."
    ),
    "语言的改动立即生效。已经显示的译文会按新目标语言自动重译一次；\n"
    "也可以随时在托盘菜单或结果窗口右上角切换目标语言。": (
        "Changes take effect immediately. A translation already on screen is redone "
        "in the new target language;\nyou can also switch the target language any time "
        "from the tray menu or the result window."
    ),

    # ===== 界面语言（新增） =====
    "界面语言": "Interface language",
    "界面显示语言，切换后立即生效": "Language of the interface; applies immediately",
    "界面语言已切换为{language}。": "Interface language switched to {language}.",

    # ===== 快捷键页 =====
    "录制你习惯的按键组合。改动会立即重新注册，无需重启程序。": (
        "Record the key combination you like. Changes are re-registered immediately, "
        "no restart needed."
    ),
    "全局快捷键": "Global hotkeys",
    "启用全局快捷键": "Enable global hotkeys",
    "唤出框选层，框住哪里就翻译哪里": (
        "Brings up the selection overlay: whatever you box gets translated"
    ),
    "不重新截图，直接把上一次框选的区域再翻译一次": (
        "Re-translate the previous selection without taking a new screenshot"
    ),
    "重新注册快捷键": "Re-register hotkeys",
    "录制": "Record",
    "取消": "Cancel",
    "取消录制": "Cancel recording",
    "清除": "Clear",
    "默认": "Default",
    "恢复默认 {hotkey}": "Restore the default {hotkey}",
    "请按下组合键…": "Press a key combination…",
    "点击「录制」后按下组合键即可录入，也支持直接手输。": (
        "Click \"Record\", then press the combination. Typing it in also works."
    ),
    "请同时按下 Ctrl / Alt / Shift 之一与一个主键": (
        "Hold one of Ctrl / Alt / Shift together with another key"
    ),
    "需要至少一个修饰键，例如 Ctrl+Alt+Z": (
        "At least one modifier is required, for example Ctrl+Alt+Z"
    ),
    "怎么设置：点「录制」→ 直接按下想要的组合键（例如 Ctrl+Alt+Z）。\n"
    "录制期间会临时停用全局热键，否则按键会被系统钩子先吃掉，界面录不到。\n"
    "组合必须包含 Ctrl / Alt / Shift / Win 中至少一个修饰键。\n"
    "按 Esc 取消录制；点「默认」恢复出厂快捷键。\n\n"
    "若提示注册失败：多半是组合被别的软件占用，换一个即可；\n"
    "少数机器需要以管理员身份运行才能安装键盘钩子。": (
        "How to set it: click \"Record\" and press the combination you want "
        "(for example Ctrl+Alt+Z).\n"
        "Global hotkeys are temporarily disabled while recording; otherwise the "
        "system hook would swallow the keys and nothing would be captured.\n"
        "The combination must include at least one of Ctrl / Alt / Shift / Win.\n"
        "Press Esc to cancel recording; click \"Default\" to restore the factory hotkey.\n\n"
        "If registration fails, the combination is most likely taken by another "
        "program — just pick a different one.\n"
        "A few machines require running as administrator to install the keyboard hook."
    ),

    # ===== OCR 页 =====
    "屏幕文字先由本地引擎识别成文本，再送去翻译。": (
        "Text on screen is first recognized locally, then sent for translation."
    ),
    "识别引擎": "Recognition engine",
    "OCR 引擎": "OCR engine",
    "本地离线，不联网，不上传屏幕内容": (
        "Local and offline: no network, your screen content never leaves the machine"
    ),
    "识别前放大倍数": "Upscale factor",
    "字太小识别不准时调到 1.5 ~ 2.0": "Raise to 1.5 ~ 2.0 when small text is misread",
    "最低置信度": "Minimum confidence",
    "低于该值的识别结果会被丢弃": "Results below this value are discarded",
    "RapidOCR（本地离线，中简/中繁/英）": (
        "RapidOCR (local, Simplified/Traditional Chinese + English)"
    ),
    "RapidOCR（本地离线）": "RapidOCR (local)",
    "RapidOCR 模型在程序启动后会在后台加载（约 1~3 秒），之后常驻内存，\n"
    "单次识别通常在 1 秒内完成，全程不联网。": (
        "The RapidOCR model loads in the background after start-up (about 1–3 seconds) "
        "and then stays in memory.\n"
        "A single recognition usually finishes within one second, fully offline."
    ),

    # ===== 翻译页 =====
    "译文由在线免费接口生成。任何一个后端不可用都不会让翻译整个失败。": (
        "Translations come from free public endpoints. One backend being down "
        "never fails the whole translation."
    ),
    "后端优先级（自上而下依次尝试，失败自动切换）": (
        "Backend priority (tried top to bottom, switching automatically on failure)"
    ),
    "上移": "Move up",
    "下移": "Move down",
    "单次请求超时": "Request timeout",
    "网络慢时可适当调大": "Increase this on a slow network",
    "启用翻译缓存（相同内容不再请求网络）": (
        "Enable translation cache (identical text is not requested again)"
    ),
    "清空翻译缓存": "Clear translation cache",
    "上面四个后端都是免费公开接口，不需要 API Key。\n"
    "被限流的后端会自动进入冷却并切换到下一个，\n"
    "因此把响应快的排在上面体验最好。\n"
    "想测自己网络下哪个最快：运行 scripts\\benchmark_translate.py。\n"
    "如果觉得译文不够准（尤其是 AI 术语、人名），"
    "建议在下面配置大模型后端——它最准，但需要 API Key 且按量计费。": (
        "The four backends above are free public endpoints and need no API key.\n"
        "A rate-limited backend is cooled down automatically and the next one takes over,\n"
        "so putting the fastest one on top gives the best experience.\n"
        "To measure which is fastest on your network, run "
        "scripts\\benchmark_translate.py.\n"
        "If the translations are not accurate enough (especially AI terms and personal "
        "names), configure the LLM backend below — it is the most accurate, but it needs "
        "an API key and is billed by usage."
    ),
    "译文由在线接口生成。任何一个后端不可用都不会让翻译整个失败。"
    "勾选并拖动可调整优先级。": (
        "Translations come from online endpoints. No single backend being unavailable "
        "will fail the whole translation. Tick and drag to change priority."
    ),
    "大模型翻译（需 API Key，译文质量最好）": (
        "LLM translation (needs an API key, best quality)"
    ),
    "有道翻译（最快，无需 Key）": "Youdao (fastest, no key needed)",
    "MyMemory（免费额度，较稳定）": "MyMemory (free quota, fairly stable)",
    "Bing 翻译（无需 Key，需先取令牌）": "Bing Translate (no key, needs a token first)",
    "Google 免费端点（部分网络不可达）": (
        "Google free endpoint (unreachable on some networks)"
    ),
    "大模型翻译（可选，译文质量最好）": (
        "LLM translation (optional, best quality)"
    ),
    "服务商": "Provider",
    "自定义": "Custom",
    "选择后会自动填好下面的接口地址与模型名": (
        "Selecting one fills in the endpoint and model below"
    ),
    "API Key": "API key",
    "粘贴你的 API Key，留空则不启用": "Paste your API key; leave empty to disable",
    "只保存在本机配置里，不会上传到别处": (
        "Stored only in the local config, never uploaded anywhere"
    ),
    "接口地址": "Endpoint URL",
    "OpenAI 兼容地址，本地模型也可填": (
        "Any OpenAI-compatible URL; a local model works too"
    ),
    "模型名": "Model name",
    "例如 deepseek-chat": "For example deepseek-chat",
    "未填写 API Key：大模型后端不会参与翻译。": (
        "No API key entered: the LLM backend will not be used."
    ),
    "已填写 API Key，但未在上面的列表里勾选「大模型翻译」。": (
        "An API key is entered, but \"LLM translation\" is not ticked in the list above."
    ),
    "已启用：翻译时会按列表顺序尝试它。": (
        "Enabled: it will be tried in the order shown in the list."
    ),
    "有道翻译": "Youdao",
    "MyMemory": "MyMemory",
    "Bing 翻译": "Bing Translate",
    "Google 免费端点": "Google free endpoint",
    "大模型翻译": "LLM translation",

    # ===== 界面页 =====
    "调整结果窗口的显示方式与本地数据规模。": (
        "Control how the result window looks and how much data is kept locally."
    ),
    "结果窗口": "Result window",
    "结果窗口置顶显示": "Keep the result window on top",
    "显示原文区域": "Show the original text",
    "翻译完成后自动复制译文到剪贴板": (
        "Copy the translation to the clipboard automatically"
    ),
    "字号": "Font size",
    "译文字号会比原文大 2pt": "The translation is 2pt larger than the original",
    " 秒": " s",
    " 条": " entries",
    "不设置": "Not set",
    "数据与历史": "Data and history",
    "历史记录上限": "History limit",
    "超出后自动丢弃最旧的记录": "Oldest entries are dropped beyond this limit",
    "查看翻译历史": "View history",
    "打开配置文件目录": "Open config folder",
    "配置文件位置：{path}": "Config file: {path}",

    # ===== 状态栏 =====
    "目标语言：{language}": "Target: {language}",
    "截图热键：{hotkey}": "Hotkey: {hotkey}",
    "截图热键：未设置": "Hotkey: not set",
    "全局热键已停用": "Global hotkeys are disabled",
    "⚠ 热键未生效：{reason}": "⚠ Hotkey inactive: {reason}",

    # ===== 结果窗口 =====
    "翻译结果": "Translation result",
    "原文": "Original",
    "译文": "Translation",
    "原文（{language}）": "Original ({language})",
    "译文（{language}）": "Translation ({language})",
    "收起": "Collapse",
    "展开": "Expand",
    "复制译文": "Copy translation",
    "重译": "Retranslate",
    "置顶": "On top",
    "切换目标语言并重新翻译": "Switch the target language and translate again",
    "对当前原文重新翻译": "Translate the current original text again",
    "切换窗口置顶": "Toggle always-on-top",
    "打开设置：快捷键、语言、OCR 与翻译后端": (
        "Open settings: hotkeys, languages, OCR and translation backends"
    ),
    "关闭 (Esc)": "Close (Esc)",
    "（未识别到文字）": "(no text recognized)",
    "等待结果…": "Waiting for the result…",
    "翻译失败": "Translation failed",
    "正在识别…": "Recognizing…",
    "正在识别文字…": "Recognizing text…",
    "正在翻译…": "Translating…",
    "正在翻译（{engine}）…": "Translating ({engine})…",
    "正在重新翻译…": "Translating again…",
    "已复制译文到剪贴板": "Translation copied to the clipboard",
    "引擎：{engine}": "Engine: {engine}",
    "缓存命中": "Cache hit",
    "耗时 {seconds}s": "Took {seconds}s",
    "原文 {count} 字": "{count} characters",
    "{source} → {target}": "{source} → {target}",
    "目标：{language}": "Target: {language}",

    # ===== 历史窗口 =====
    "自动记录最近若干条翻译，可搜索查看、复制、重译。": (
        "Recent translations are recorded automatically; review, copy or redo them."
    ),
    "时间": "Time",
    "方向": "Direction",
    "重译此条": "Retranslate this",
    "清空历史": "Clear history",
    "关闭": "Close",
    "共 {count} 条": "{count} entries",
    "确定要删除全部 {count} 条历史记录吗？": (
        "Delete all {count} history entries?"
    ),
    "详情：时间 / 方向 / 引擎 / 耗时 / 原文 / 译文": (
        "Details: time / direction / engine / duration / original / translation"
    ),
    "时间：{time}\n方向：{source} → {target}\n引擎：{engine}\n耗时：{seconds}s\n\n"
    "【原文】\n{original}\n\n【译文】\n{translation}": (
        "Time: {time}\nDirection: {source} → {target}\nEngine: {engine}\n"
        "Duration: {seconds}s\n\n[Original]\n{original}\n\n[Translation]\n{translation}"
    ),

    # ===== 框选覆盖层 =====
    "选择要翻译的区域": "Select the area to translate",
    "拖拽选择要翻译的区域    ·    ESC / 右键取消": (
        "Drag to select the area to translate    ·    ESC / right-click to cancel"
    ),

    # ===== 控制器与运行时提示 =====
    "上一次识别还在进行中，请稍候…": "The previous recognition is still running, please wait…",
    "屏幕抓取失败，无法开始截图。": "Screen capture failed, cannot start a screenshot.",
    "没有检测到可用显示器。": "No usable display was detected.",
    "截取区域为空，请重新框选。": "The selected area is empty, please select again.",
    "还没有框选过区域，先按热键截一次图吧。": (
        "Nothing has been selected yet — press the hotkey to capture once."
    ),
    "截图内容为空。": "The captured image is empty.",
    "出现未预期的错误：{type}: {message}": "Unexpected error: {type}: {message}",
    "重译失败：{message}": "Retranslation failed: {message}",
    "未识别到文字，请框选包含清晰文字的区域后重试": (
        "No text was recognized. Select an area with clear text and try again."
    ),
    "翻译失败：所有后端均不可用。\n{detail}\n请检查网络连接，或在设置里调整后端顺序。": (
        "Translation failed: no backend is available.\n{detail}\n"
        "Check your network connection, or change the backend order in settings."
    ),
    "所有翻译后端均失败（{detail}）": "All translation backends failed ({detail})",
    "后端不可用": "backend unavailable",
    "冷却中（{detail}）": "cooling down ({detail})",
    "OCR 引擎不可用：缺少依赖 rapidocr-onnxruntime。\n"
    "请在项目目录执行：.venv\\Scripts\\python -m pip install rapidocr-onnxruntime": (
        "OCR engine unavailable: the rapidocr-onnxruntime dependency is missing.\n"
        "Run this in the project folder: "
        ".venv\\Scripts\\python -m pip install rapidocr-onnxruntime"
    ),
    "未安装 OCR 依赖 rapidocr-onnxruntime，请运行:\n"
    "  .venv\\Scripts\\python -m pip install rapidocr-onnxruntime": (
        "The OCR dependency rapidocr-onnxruntime is not installed. Please run:\n"
        "  .venv\\Scripts\\python -m pip install rapidocr-onnxruntime"
    ),
    "OCR 模型加载失败: {message}": "Failed to load the OCR model: {message}",
    "OCR 识别失败: {message}": "OCR recognition failed: {message}",
    "待识别图片为空": "The image to recognize is empty",
    "未知的 OCR 引擎: {name}": "Unknown OCR engine: {name}",
    "未安装 keyboard 依赖，无法注册全局热键。请运行:\n"
    "  .venv\\Scripts\\python -m pip install keyboard": (
        "The keyboard dependency is missing, global hotkeys cannot be registered. "
        "Please run:\n"
        "  .venv\\Scripts\\python -m pip install keyboard"
    ),
    "注册热键 {hotkey} 失败：{reason}": "Failed to register the hotkey {hotkey}: {reason}",
    "当前系统不支持托盘图标，程序无法常驻运行。": (
        "This system does not support tray icons, so the app cannot stay resident."
    ),
    "程序已在运行，按热键开始截图翻译。": (
        "The app is already running. Press the hotkey to translate a screenshot."
    ),

    # ===== 命令行参数 =====
    "截图识别文本并翻译的桌面工具": "Desktop tool that recognizes and translates screen text",
    "本次启动的目标语言（zh-Hans / zh-Hant / en）": (
        "Target language for this run (zh-Hans / zh-Hant / en)"
    ),
    "本次启动的源语言（默认 auto 自动检测）": (
        "Source language for this run (default: auto detect)"
    ),
    "不注册全局热键": "Do not register global hotkeys",
    "直接翻译指定图片后退出": "Translate the given image and exit",
    "输出调试日志": "Enable debug logging",
    "恢复默认设置": "Restore default settings",
    "忽略无法识别的目标语言: {language}": "Ignoring unrecognized target language: {language}",
    "无法读取图片: {path}": "Cannot read image: {path}",
    "失败: {message}": "Failed: {message}",
    "图片路径": "image path",
    "输出调试日志": "Enable debug logging",
    "恢复默认设置后启动": "Restore defaults before starting",
    "未找到 Python，请设置环境变量 DSH_PYTHON 指向 python.exe": (
        "Python not found. Set the DSH_PYTHON environment variable to python.exe"
    ),
    "无法读取图片: {path}": "Cannot read image: {path}",
    "--- 原文 ---": "--- Original ---",
    "--- 译文 ---": "--- Translation ---",
    "--- 引擎 {engine} · OCR {ocr}s · 翻译 {translation}s ---": (
        "--- Engine {engine} · OCR {ocr}s · translation {translation}s ---"
    ),
}


# ---------------------------------------------------------------------------
# 目录构建
# ---------------------------------------------------------------------------
_HANT_CACHE: Optional[Dict[str, str]] = None


def _traditional_catalog() -> Dict[str, str]:
    """繁体目录由简体原文自动转换而来，加载时生成一次。"""
    global _HANT_CACHE
    if _HANT_CACHE is None:
        _HANT_CACHE = {key: convert_script(key, ZH_HANT) for key in ENGLISH}
    return _HANT_CACHE


def catalog(language: str) -> Dict[str, str]:
    """返回指定界面语言的翻译表（zh-Hans 为空表，直接回退原文）。"""
    if language == EN:
        return ENGLISH
    if language == ZH_HANT:
        return _traditional_catalog()
    return {}


def is_supported(language: str) -> bool:
    return language in UI_LANGUAGES


def language_display_name(language: str, ui_language: Optional[str] = None) -> str:
    """界面语言在给定界面语言下的显示名。

    例如在英文界面下，``zh-Hans`` 显示为 ``Chinese (Simplified)``；
    在繁体界面下显示为 ``簡體中文``。
    """
    target = ui_language or current_language()
    table = UI_LANGUAGE_NAMES.get(target) or UI_LANGUAGE_NAMES[ZH_HANS]
    return table.get(language, language)


# ---------------------------------------------------------------------------
# 当前语言与查询
# ---------------------------------------------------------------------------
_current = ZH_HANS


def set_language(language: str) -> bool:
    """设置当前界面语言。返回是否发生变化。"""
    global _current
    if not is_supported(language):
        logger.warning("不支持的界面语言，保持原样: %s", language)
        return False
    if language == _current:
        return False
    _current = language
    logger.info("界面语言已切换为 %s", language)
    return True


def current_language() -> str:
    return _current


def tr(text: str) -> str:
    """把界面文案翻译成当前界面语言。

    找不到对应条目时返回原文（简体中文），这是刻意的：
    漏翻只会显示中文，不会变成看不懂的占位符。
    """
    if _current == ZH_HANS:
        return text
    return catalog(_current).get(text, text)


def trn(text: str, **kwargs) -> str:
    """翻译并格式化 ``{name}`` 形式占位符。

    ``kwargs`` 为空时也走一遍 ``format``：模板里若还有未替换的占位符，
    说明调用方漏传参数，这时回退成原文（简体中文）——
    比抛异常打断界面，或者把 ``{count}`` 原样显示给用户都要好。
    """
    translated = tr(text)
    try:
        return translated.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        logger.debug("界面文案格式化失败，回退原文: %r", text)
        return text


def untranslated(language: str) -> list:
    """返回该语言下缺失的条目（供自检脚本使用）。"""
    if language == ZH_HANS:
        return []
    table = catalog(language)
    return sorted(key for key in ENGLISH if key not in table)


def app_title() -> str:
    """应用名，跟随界面语言。

    应用名出现在窗口标题、托盘提示、通知里；英文界面下如果不翻译，
    就会变成"翻译 v0.2.1 | Target: …"这种半中半英的提示。
    """
    return tr("翻译")


def engine_label(name: str) -> str:
    """把翻译后端的标识翻成当前界面语言下的显示名。

    ``fanyi.core.translate.ENGINE_LABELS`` 里存的是简体中文名，
    这里用它作为翻译键取出对应语言的名字；未知标识原样返回。
    """
    if not name:
        return ""
    return tr(name)


def key_of(text: str) -> str:
    """把一个已经是"当前语言文案"的字符串还原成目录键。

    界面控件会把文案存成动态属性，切换语言时再取回来重新翻译。
    如果存的是翻译后的文案（例如英文），就需要反查回简体中文键，
    否则切回中文时会把英文原文当成键，导致文案不还原。
    """
    if not text:
        return ""
    if text in ENGLISH:
        return text
    for key, value in catalog(_current).items():
        if value == text:
            return key
    return text


__all__ = [
    "EN",
    "ENGLISH",
    "UI_LANGUAGES",
    "UI_LANGUAGE_NAMES",
    "app_title",
    "catalog",
    "current_language",
    "engine_label",
    "is_supported",
    "key_of",
    "language_display_name",
    "set_language",
    "tr",
    "trn",
    "untranslated",
]
