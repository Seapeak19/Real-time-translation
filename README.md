# 翻译 · 截图识别翻译工具

在屏幕上随手框一块区域，自动识别里面的文字并翻译成你想要的语言。
**多语言互译**（简体中文 / 繁体中文 / 英语），OCR 完全本地离线，翻译走免费公开接口，无需任何 API Key。

```
按热键 (Ctrl+Alt+Z)  →  拖拽框选屏幕区域  →  本地 OCR 识别文字  →  翻译成目标语言  →  置顶窗展示
```

---

## 功能

| 能力 | 说明 |
|---|---|
| 截图翻译 | 全局热键唤出框选层，拖拽即可翻译任意界面上的文字（图片、视频字幕、游戏、报错信息、PDF…） |
| 本地离线 OCR | RapidOCR（ONNX Runtime），内置中简/中繁/英文模型，**不联网、无次数限制、不上传你的屏幕内容** |
| 多语言互译 | 简体中文 ⇄ 繁体中文 ⇄ English；源语言可选「自动检测」，目标语言随时切换 |
| 多后端自动回退 | 四个免费后端可插拔，任一后端限流或失效会自动换下一个，不会整个工具挂掉 |
| 限流退避 | 被限流的后端会进入 45 秒冷却，界面不再"每次都等超时"，而是直接用可用的那个 |
| 简繁字形归一 | 在线引擎只区分 `zh-CN`，本地再用 OpenCC 校正字形，保证「繁体中文」选项真的输出繁体 |
| 翻译缓存 | 相同内容直接命中缓存，既快又能显著降低被限流的概率 |
| 置顶结果窗 | 原文/译文对照、一键复制、切换目标语言后自动重译、可拖动可调大小 |
| 托盘常驻 | 托盘菜单切换语言、查看历史、清空缓存、修改设置 |
| 翻译历史 | 自动记录最近若干条翻译，可搜索查看、复制、重译 |

### 翻译后端实测（国内网络）

`scripts/probe_engines.py` 可复测；下表为默认优先级，可在设置里调整：

| 后端 | 典型时延 | 说明 |
|---|---|---|
| 有道翻译 | **0.2 ~ 1s** | 最快，短句质量好，首选 |
| MyMemory | 1 ~ 3s | 免费额度制，较稳定，第二顺位 |
| Bing 翻译 | 1 ~ 3s | 需先取会话令牌，第三顺位 |
| Google 免费端点 | 视网络 | 国内常被阻断，能直连时质量最好 |

---

## 环境要求

* Windows 10 / 11（截图走 Windows GDI）
* Python 3.10 ~ 3.12（开发验证于 3.12）
* 首次运行需要联网（仅用于翻译；OCR 模型随依赖一起下载，之后可断网识别）

---

## 安装

```powershell
git clone <仓库地址> 翻译软件
cd 翻译软件

# 创建 .venv 并安装依赖（默认走清华镜像）
python scripts\bootstrap_dev.py
```

装完后做一次自检，确认 OCR / 翻译 / 截图 / 热键都正常：

```powershell
.venv\Scripts\python.exe scripts\selfcheck.py
```

自检会真的识别一张生成的测试图、真的调用翻译接口、真的抓一次屏幕，并打印每个环节的耗时。

---

## 验证工具

改动之后想确认没坏，按下面顺序跑一遍即可（都不是单元测试，而是真的调用系统能力）：

| 命令 | 作用 |
|---|---|
| `.venv\Scripts\python.exe scripts\selfcheck.py` | 环境自检：依赖、OCR、翻译、截图、热键、端到端 |
| `.venv\Scripts\python.exe -m pytest` | 单元测试（纯逻辑，不联网、不弹窗） |
| `.venv\Scripts\python.exe scripts\gui_smoketest.py` | 界面冒烟：托盘、结果窗、设置、历史、框选覆盖层、后台线程、真实 OCR+翻译 |
| `.venv\Scripts\python.exe scripts\launch_check.py` | 真的启动一次主程序，确认常驻、单实例、热键注册与日志 |
| `.venv\Scripts\python.exe scripts\probe_engines.py` | 逐个探测翻译后端在你的网络下的连通性与时延 |

---

## 使用

```powershell
# 方式一：双击
启动翻译.bat

# 方式二：命令行
.venv\Scripts\python.exe -m fanyi
```

启动后**没有主窗口**，只在托盘出现一个「译」字图标。之后：

1. 按 `Ctrl + Alt + Z`（可在设置里改）
2. 屏幕变暗，拖拽框住要翻译的文字
3. 结果窗口弹出，显示原文与译文

### 默认热键

| 热键 | 作用 |
|---|---|
| `Ctrl + Alt + Z` | 框选截图并翻译 |
| `Ctrl + Alt + X` | 重译上次框选的区域（不重新截图） |
| `Esc` / 右键 | 取消框选 |
| 结果窗内 `Ctrl + C` | 复制译文 |
| 结果窗内 `Ctrl + R` | 重译 |
| 结果窗内 `Esc` | 关闭结果窗 |

### 命令行参数

```powershell
python -m fanyi --lang en                 # 本次启动默认目标语言为英语
python -m fanyi --source zh-Hans          # 固定源语言（默认 auto 自动检测）
python -m fanyi --no-hotkey               # 不注册全局热键（排查按键冲突时用）
python -m fanyi --translate-image a.png   # 直接翻译一张图片并打印结果（调试用）
python -m fanyi --reset-config            # 恢复默认设置
python -m fanyi --debug                   # 输出调试日志
```

---

## 配置与数据位置

| 内容 | 路径 |
|---|---|
| 配置文件 | `%APPDATA%\fanyi\config.json` |
| 翻译历史 | `%APPDATA%\fanyi\history.json` |
| 翻译缓存 | `%APPDATA%\fanyi\cache.json` |
| 运行日志 | `%APPDATA%\fanyi\fanyi.log` |

> 设置根目录可用环境变量 `FANYI_HOME` 覆盖（便于做便携版）。
>
> 出问题时先看 `fanyi.log`：热键注册结果、OCR 模型加载、翻译后端失败原因都会记在里面。
> 截图产物、测试缓存等临时数据放在项目的 `testdata\` 下，不进版本库。

### 常用配置项

| 键 | 默认值 | 说明 |
|---|---|---|
| `target_lang` | `zh-Hans` | 目标语言：`zh-Hans` / `zh-Hant` / `en` |
| `source_lang` | `auto` | 源语言，`auto` 为自动检测 |
| `hotkey` | `ctrl+alt+z` | 截图翻译热键 |
| `repeat_hotkey` | `ctrl+alt+x` | 重译上次区域热键 |
| `ocr_scale` | `1.0` | 识别前放大倍数，小字识别不准时调到 `1.5` ~ `2.0` |
| `ocr_min_confidence` | `0.45` | 低于该置信度的识别结果会被丢弃 |
| `translate_engines` | `["youdao","mymemory","bing","google"]` | 后端尝试顺序 |
| `request_timeout` | `8.0` | 单次请求超时（秒） |
| `result_font_size` | `12` | 结果窗字号 |

---

## 项目结构

```
翻译软件/
├── fanyi/
│   ├── app.py            程序入口：日志、单实例、Qt 初始化、命令行参数
│   ├── config.py         配置模型与读写
│   ├── languages.py      语言定义、简繁字形转换、分行拼接策略
│   ├── screenshot.py     Windows GDI 抓屏、DPI 感知、QImage ↔ numpy
│   ├── overlay.py        多屏框选覆盖层（调暗 + 挖洞 + 十字线）
│   ├── hotkey.py         全局热键注册（keyboard 钩子 → Qt 信号）
│   ├── instance.py       单实例保护（本地套接字）
│   ├── core/             无界面核心层（可独立测试/复用）
│   │   ├── base.py       翻译后端契约、异常体系、长文本切分
│   │   ├── client.py     带重试的 HTTP 客户端与错误分类
│   │   ├── engines.py    Google / MyMemory / Bing 三个免费后端
│   │   ├── translate.py  多后端回退、缓存、字形归一化
│   │   ├── ocr.py        本地离线 OCR（RapidOCR）与引擎接口
│   │   └── pipeline.py   图像 → 文本 → 译文 的完整流程
│   └── ui/
│       ├── controller.py     总控制器：串起托盘/热键/覆盖层/管线/结果窗
│       ├── tray.py           托盘图标与菜单
│       ├── result_window.py  置顶结果卡片
│       ├── settings_dialog.py 设置面板
│       ├── history.py        历史记录存储
│       ├── history_panel.py  历史记录面板
│       ├── worker.py         工作线程（识别与网络请求不阻塞界面）
│       └── activate.py       唤起已运行实例
├── scripts/
│   ├── bootstrap_dev.py  环境初始化
│   ├── selfcheck.py      环境自检（OCR/翻译/截图/热键/端到端）
│   ├── gui_smoketest.py  界面冒烟测试
│   ├── launch_check.py   真实启动验证（常驻/单实例/热键）
│   └── probe_engines.py  翻译后端可用性与时延探测
├── tests/                单元测试
├── 启动翻译.bat
└── requirements.txt
```

### 架构要点

* **core 层不依赖 Qt**：OCR、翻译、管线都可以在命令行单独调用和测试。
* **后端可插拔**：新增翻译后端只需继承 `Translator` 实现 `translate()`，
  再在 `core/translate.py` 的 `ENGINE_FACTORIES` 里注册，回退/缓存/字形处理自动生效。
* **OCR 可插拔**：新增识别引擎只需继承 `OcrEngine` 并实现 `recognize()`。
* **线程模型**：界面全部在主线程；热键回调经 Qt 信号转入主线程；OCR 与网络请求跑在工作线程。

---

## 常见问题

**热键没反应？**
1. 看托盘气泡或 `%APPDATA%\fanyi\fanyi.log` 是否有「热键注册失败」；
2. 常见原因是被安全软件 / 输入法 / 其它托盘工具占用，换个组合或在设置里改；
3. 少数机器需要以管理员身份运行才能安装键盘钩子。

**翻译很慢或者报「所有翻译后端均失败」？**
免费端点会限流，也会因为网络环境不可达。先跑诊断：

```powershell
.venv\Scripts\python.exe scripts\probe_engines.py
```

它会逐个探测各后端的连通性与时延，据此在设置里调整后端顺序（把快的放前面）。

**OCR 识别不准？**
把设置里的「识别前放大倍数」调到 `1.5` ~ `2.0`，并适当提高框选区域的清晰度（避免缩放过小的文字）。

**识别结果串行了？**
管线会按版面顺序（先上下后左右）重排文本行；若原文本身是分栏排版，建议分次框选。

**想让它不要弹出托盘提示？**
托盘提示只在启动、失败、清空缓存等场景出现，且几秒后自动消失。

---

## 开发

```powershell
# 安装开发依赖
.venv\Scripts\python.exe -m pip install pytest pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple

# 跑单元测试
.venv\Scripts\python.exe -m pytest

# 打包成单文件 exe（可选，体积约 200MB+，因为包含 ONNX 模型与 Qt）
.venv\Scripts\pyinstaller --noconfirm --windowed --name 翻译 ^
  --collect-all rapidocr_onnxruntime ^
  --collect-all onnxruntime ^
  --collect-all opencc ^
  fanyi\__main__.py
```

---

## 已知限制

* 仅支持 Windows（截图用 GDI，热键用 Windows 钩子）。
* 翻译需要联网；离线时只能识别文字、无法翻译（架构上已预留本地翻译后端的接入位）。
* 免费翻译端点属于公开接口，可能随时变更或被限流，这是选用「多后端自动回退」的原因。
* 暂不支持「译文覆盖回原位置」的沉浸式翻译，如需可作为后续迭代。
