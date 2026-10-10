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
| 设置界面 | 独立设置窗口：可视化**录制快捷键**、切换语言、调 OCR 与翻译后端，改完立即生效 |
| 翻译历史 | 自动记录最近若干条翻译，可搜索查看、复制、重译 |
| 免安装分发 | 提供 PyInstaller 打包配置，产出独立目录，目标机器无需装 Python |
| 高 DPI 适配 | 与 GDI 统一使用设备像素，多显示器 / 125% 缩放下框选区与屏幕严丝合缝 |

### 翻译后端实测（国内网络）

`scripts/probe_engines.py` 可复测；下表为默认优先级，可在设置里调整：

| 后端 | 典型时延 | 说明 |
|---|---|---|
| 有道翻译 | **0.2 ~ 1s** | 最快，短句质量好，首选 |
| MyMemory | 1 ~ 3s | 免费额度制，较稳定，第二顺位 |
| Bing 翻译 | 1 ~ 3s | 需先取会话令牌，第三顺位 |
| Google 免费端点 | 视网络 | 国内常被阻断，能直连时质量最好 |

---

## 两种使用方式

### 方式一：直接运行打包好的程序（推荐给最终用户）

进入 `dist\翻译\`，双击 **`翻译.exe`**。整个目录约 335 MB，可以拷到任何 Windows 机器上运行，
**不需要安装 Python**。

> ⚠ **不要把 `翻译.exe` 单独拷出来用**（比如只拖一个 exe 到桌面）。
> 单目录打包的程序运行时依赖同级的 `_internal\` 目录（648 个文件），
> 少了它双击就会报 **「找不到指定的模块」** —— 因为 `python312.dll`、
> ONNX Runtime、Qt 等都在那里面。
>
> 想要桌面入口，请用**快捷方式**（见下），exe 本体留在原目录。

### 建桌面快捷方式

```powershell
.venv\Scripts\python.exe scripts\create_shortcut.py
```

它会：

1. 在真实桌面（识别 OneDrive 重定向）创建 `翻译.lnk`，目标与"起始位置"都指向打包目录；
2. 若发现桌面上存在**单独的 `翻译.exe`**（跑不起来的那个副本），提示并删除；
3. 校验同级 `_internal\` 是否存在——不存在就直接报错，不会给你一个点了打不开的图标。

参数：`--target <目录或exe>` 换目标、`--name <名字>` 换显示名、`--keep-desktop-exe` 保留那个副本。

> 快捷方式指向的是项目里的 `dist\翻译\`，所以**不要移动或改名 `dist` 目录**，
> 否则快捷方式会失效。想放到别处（例如 `D:\工具\翻译\`），把整个
> `dist\翻译\` 目录拷过去，再对这个新位置重新运行一次脚本即可。

### 方式二：从源码运行（推荐给要改代码的人）

见下面的「安装」。

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

改动之后想确认没坏，按下面顺序跑一遍即可（都不是单纯的单元测试，而是真的调用系统能力）：

| 命令 | 作用 |
|---|---|
| `.venv\Scripts\python.exe -m pytest` | 单元测试（纯逻辑，不联网、不弹窗） |
| `.venv\Scripts\python.exe scripts\selfcheck.py` | 环境自检：依赖、OCR、翻译、截图、热键、端到端 |
| `.venv\Scripts\python.exe scripts\gui_smoketest.py` | 界面冒烟：托盘、结果窗、设置、历史、框选覆盖层、后台线程、真实 OCR+翻译 |
| `.venv\Scripts\python.exe scripts\diagnose_ui.py` | 界面外观诊断：真实渲染各窗口为 PNG、检查配色对比度与字体 |
| `.venv\Scripts\python.exe scripts\audit_i18n.py` | 多语言自检：列出漏翻的界面字符串（应为"干净"） |
| `.venv\Scripts\python.exe scripts\i18n_smoketest.py` | 三种界面语言下逐个控件检查文案是否跟随 |
| `.venv\Scripts\python.exe scripts\i18n_e2e.py` | 界面语言切换端到端：选语言 → 落盘 → 重启恢复 |
| `.venv\Scripts\python.exe scripts\launch_check.py` | 真的启动一次主程序，确认常驻、单实例、热键注册与日志 |
| `.venv\Scripts\python.exe scripts\verify_package.py` | 真的启动打包后的 exe，确认它在没有 Python 的环境里也能跑 |
| `.venv\Scripts\python.exe scripts\probe_engines.py` | 逐个探测翻译后端在你的网络下的连通性与时延 |

---

## 打包成免安装程序

```powershell
# 1) 装打包工具（一次性）
.venv\Scripts\python.exe -m pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2) 生成程序图标（可选，改图标时用）
.venv\Scripts\python.exe scripts\make_icon.py

# 3) 打包
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean 翻译.spec

# 4) 验证产物真的能跑（会启动 exe 并检查日志）
.venv\Scripts\python.exe scripts\verify_package.py
```

产物：`dist\翻译\翻译.exe` + `dist\翻译\_internal\`，整体约 335 MB（Qt 与 ONNX Runtime 占大头）。

打包排错：若 exe 一闪而过，用保留控制台的 `翻译-debug.spec` 重新打包，
它会把崩溃堆栈直接打在窗口里（`--distpath dist-debug --workpath build-debug`）。

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

### 界面外观

界面统一为**明亮的纯白主题**：侧栏、内容区、状态栏、结果窗、历史窗全部白底，
只用 1px 淡边框分区。这一点在系统开启深色模式时尤其重要——
Windows 深色模式下 Qt 默认给出深色调色板，若不处理就会出现
「白底白字」和「侧栏深灰、内容区白色」的一明一暗。

实现方式（见 `fanyi/ui/theme.py`）是同时做两件事，而不是逐个控件补颜色：

1. 给 `QApplication` 装一套完整的浅色调色板（含 `Text`/`WindowText`/`ButtonText`
   这些**前景色**，以及激活/非激活/禁用三种状态）；
2. 用 Fusion 样式，避免 `windows11` 样式在深色模式下对原生控件自行染色。

这样新增控件默认就是浅色，不用再操心配色。

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

## 设置界面

打开方式（任选其一）：

* 托盘图标**双击**
* 托盘右键菜单 →「设置…」
* 结果窗口右上角「设置」按钮

窗口左侧是五个分组，右侧是具体选项。**所有改动立即生效并写入配置文件，没有"确定/取消"**。

| 分组 | 能改什么 |
|---|---|
| **语言** | **界面语言**（简体中文 / 繁体中文 / English）；源语言（可自动检测）、目标语言；一键互换；常用目标语言快捷按钮 |
| **快捷键** | 点「录制」后直接按组合键即可；可清除、可恢复默认；显示注册是否成功 |
| **识别（OCR）** | 识别引擎、识别前放大倍数、最低置信度 |
| **翻译** | 后端优先级（勾选 + 上下移）、请求超时、是否启用缓存、清空缓存 |
| **界面** | 结果窗置顶/显示原文/自动复制、字号、历史条数上限、打开配置目录 |

### 界面语言

设置窗口 →「语言」页最上方可切换**界面显示语言**：**简体中文 / 繁体中文 / English**。
选中即刻生效——设置窗口、托盘菜单、结果窗口、历史窗口会一起换语言，并写入配置，下次启动沿用。

注意区分两个"语言"：

| 设置项 | 作用 |
|---|---|
| **界面语言** | 你看到的按钮、菜单、提示是什么语言（本节主题） |
| **源语言 / 目标语言** | 屏幕上的文字要被翻译成什么语言（与界面无关） |

举例：界面语言设为 English、目标语言设为「简体中文」，就是在英文界面上把外文翻成中文。

实现要点（见 `fanyi/ui/i18n.py`）：

* **源码里的简体中文原文就是翻译键**，不额外维护 msgid 清单，
  改代码时不会出现"键还在、文案已经变了"的脱节；
* 漏翻的字符串回退显示中文原文，而不是 `settings.language.title` 这种占位符——
  漏翻只是不够完美，不会变成看不懂的东西；
* **繁体目录由简体自动转换生成**，与截图翻译用的简繁规则同源，不存在两份数据不一致；
* 引擎名、语言名、应用名这些动态内容也跟随界面语言（不会出现"英文界面里冒出中文引擎名"）；
* 控件把翻译键挂在动态属性 `_i18n` 上，切换语言时遍历刷新，不重建窗口
  （重建会丢窗口位置、当前页签和正在录制的热键状态）。

**新增一条界面文案**：在代码里用 `tr("中文原文")`（带插值用 `trn("共 {count} 条", count=n)`），
然后把中文原文作为键补进 `fanyi/ui/i18n.py` 的 `ENGLISH` 字典。繁体会自动生成。
漏补键不会静默失败——`tests/test_i18n.py` 会扫描源码把缺失的键报出来。

### 快捷键是怎么录进去的

点「录制」→ 按下组合键 → 自动保存并**立即重新注册**，不需要重启程序。

几个实现上的细节，决定了它好不好用：

* **录制期间会自动解绑全局热键**。否则你按下的组合会先被系统钩子截走、
  直接触发截图翻译，界面根本录不到任何东西。
* 必须包含 `Ctrl` / `Alt` / `Shift` / `Win` 中至少一个修饰键，
  没有修饰键的按键会被拒绝并给出提示——这类组合会吞掉正常输入。
* 按 `Esc` 取消录制，不会改掉已有快捷键。
* 状态栏会实时显示注册结果；失败时明确提示（多半是被别的软件占用）。

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
| `ui_language` | `zh-Hans` | **界面**显示语言：`zh-Hans` / `zh-Hant` / `en` |
| `target_lang` | `zh-Hans` | 翻译目标语言：`zh-Hans` / `zh-Hant` / `en` |
| `source_lang` | `auto` | 翻译源语言，`auto` 为自动检测 |
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
│   ├── overlay.py        多屏框选覆盖层（调暗 + 挖洞 + 十字线 + 前台提升）
│   ├── hotkey.py         全局热键注册（keyboard 钩子 → Qt 信号）
│   ├── instance.py       单实例保护（命名互斥体 + 本地套接字）
│   ├── core/             无界面核心层（可独立测试/复用）
│   │   ├── base.py       翻译后端契约、异常体系、长文本切分
│   │   ├── client.py     带重试的 HTTP 客户端与错误分类
│   │   ├── engines.py    有道 / MyMemory / Bing / Google 四个免费后端
│   │   ├── translate.py  多后端回退、限流退避、缓存、字形归一化
│   │   ├── ocr.py        本地离线 OCR（RapidOCR）与引擎接口
│   │   └── pipeline.py   图像 → 文本 → 译文 的完整流程
│   └── ui/
│       ├── controller.py     总控制器：串起托盘/热键/覆盖层/管线/窗口
│       ├── theme.py          统一明亮主题（浅色调色板 + 全局样式表）
│       ├── i18n.py           界面多语言（英语目录 + 自动生成繁体 + tr/trn）
│       ├── main_window.py    设置主窗口（语言/快捷键/OCR/翻译/界面）
│       ├── hotkey_edit.py    快捷键录制控件
│       ├── tray.py           托盘图标与菜单
│       ├── result_window.py  置顶结果卡片
│       ├── history.py        历史记录存储
│       ├── history_panel.py  历史记录面板
│       ├── worker.py         工作线程（识别与网络请求不阻塞界面）
│       └── activate.py       唤起已运行实例
├── scripts/
│   ├── bootstrap_dev.py  环境初始化
│   ├── selfcheck.py      环境自检（OCR/翻译/截图/热键/端到端）
│   ├── gui_smoketest.py  界面冒烟测试（含设置窗口与快捷键录制）
│   ├── diagnose_dpi.py   框选坐标体系诊断（排查高 DPI 错位）
│   ├── diagnose_ui.py    界面外观诊断（渲染截图 + 配色对比度 + 字体）
│   ├── audit_i18n.py     多语言自检：找出漏翻的界面字符串
│   ├── i18n_smoketest.py 三种界面语言下的控件文案检查
│   ├── i18n_e2e.py       界面语言切换端到端（含落盘与重启恢复）
│   ├── scan_ui_strings.py 扫描待翻译字符串（新语种时用）
│   ├── wrap_ui_strings.py 自动给界面字符串包 tr()（AST 改写）
│   ├── launch_check.py   真实启动验证（常驻/单实例/热键）
│   ├── verify_package.py 验证打包产物可独立运行
│   ├── create_shortcut.py 建桌面快捷方式（并清理跑不起来的单独 exe 副本）
│   ├── make_icon.py      生成程序图标
│   └── probe_engines.py  翻译后端可用性与时延探测
├── tests/                单元测试
├── launcher.py           打包入口
├── 翻译.spec             PyInstaller 打包配置
├── 启动翻译.bat
└── requirements.txt
```

### 架构要点

* **core 层不依赖 Qt**：OCR、翻译、管线都可以在命令行单独调用和测试。
* **后端可插拔**：新增翻译后端只需继承 `Translator` 实现 `translate()`，
  再在 `core/translate.py` 的 `ENGINE_FACTORIES` 里注册，回退/缓存/字形处理自动生效。
* **OCR 可插拔**：新增识别引擎只需继承 `OcrEngine` 并实现 `recognize()`。
* **线程模型**：界面全部在主线程；热键回调经 Qt 信号转入主线程；OCR 与网络请求跑在工作线程
  （Python 线程 + QObject 信号桥，避免 QThread 跨线程回收的坑）。
* **坐标体系**：启动时关闭 Qt 的高 DPI 自动缩放，让 Qt 与 GDI 同处设备像素坐标系。
  这是框选区能严丝合缝贴合屏幕的前提，详见下方「常见问题」。

---

## 常见问题

**双击 exe 报「找不到指定的模块」？**
九成是 **exe 与 `_internal\` 目录分开了**。单目录打包的程序必须整目录使用：

1. 确认 `翻译.exe` 旁边有 `_internal\` 目录（应含 600+ 个文件）；
2. 不要只拷 exe（拖到桌面、发微信单文件都会触发这个问题）；
3. 桌面入口请用 `scripts\create_shortcut.py` 建快捷方式。

排查命令：

```powershell
# 确认打包产物完整
dir "dist\翻译\_internal" | Measure-Object          # 应有 600+ 项

# 换到纯 ASCII 路径再试，排除路径编码因素
Copy-Item "dist\翻译" "D:\fanyi-test\翻译" -Recurse; Start-Process "D:\fanyi-test\翻译\翻译.exe"
```

如果整目录完整、装过 VC++ 运行库（[下载](https://aka.ms/vs/17/release/vc_redist.x64.exe)）后仍报错，
用保留控制台的 debug 配置重打包，它会直接把缺失的模块名打在窗口里：

```powershell
.venv\Scripts\python.exe -m PyInstaller --noconfirm 翻译-debug.spec --distpath dist-debug --workpath build-debug
dist-debug\翻译-debug\翻译-debug.exe
```

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

**框选区域和实际屏幕对不上 / 边角截不到？**
这是高 DPI 坐标系错位，程序已经处理（Qt 与 GDI 统一用设备像素）。若仍异常，跑诊断：

```powershell
.venv\Scripts\python.exe scripts\diagnose_dpi.py
```

它会对比 GDI 抓屏尺寸、Qt 屏幕尺寸、覆盖层窗口尺寸与缩放比，直接指出哪一环不一致。
期望结果是「覆盖层尺寸与屏幕一致，缩放比为 1.0，可覆盖全屏」。

**改了快捷键没生效？**
设置窗口底部状态栏会显示注册结果。若提示失败，多半是组合已被别的软件占用；
换一个组合，或点「重新注册快捷键」再试。

**想让设置窗口跟随系统缩放（字更大）？**
程序为了让框选坐标精确，主动关闭了 Qt 的高 DPI 自动缩放。
界面字体偏小是这一取舍的结果，可以改用结果窗字号设置来放大译文。

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

# 打包（会读取 翻译.spec，产出 dist\翻译\）
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean 翻译.spec
```

改动之后建议按这个顺序验证一遍，都是真的调用系统能力而不是纯逻辑测试：

```powershell
.venv\Scripts\python.exe -m pytest                      # 单元测试
.venv\Scripts\python.exe scripts\diagnose_dpi.py        # 框选坐标是否与屏幕一致
.venv\Scripts\python.exe scripts\gui_smoketest.py       # 界面与快捷键录制
.venv\Scripts\python.exe scripts\launch_check.py        # 真实启动
.venv\Scripts\python.exe scripts\verify_package.py      # 打包产物
```

---

## 版本历史

| 版本 | 提交 | 内容 |
|---|---|---|
| **v0.3.0** | 本次 | 界面语言自定义：简体中文 / 繁体中文 / English 即时切换；全部界面文案多语言化 |
| **v0.2.1** | `4d8bdcc` | 修复设置界面「白底白字（像乱码）」与一明一暗，界面统一为明亮白色 |
| **v0.2.0** | `8bedbf4` | 设置主窗口（可视化录制快捷键/切换语言）、免安装打包、修复高 DPI 框选错位与多词热键失效 |
| `v0.1.2-rc` | `f43d73e` | 中间快照：高 DPI 坐标修复 + 设置主窗口 |
| `v0.1.1-rc` | `5185069` | 中间快照：免安装打包 + 单实例/焦点/文本拼接修复 |
| **v0.1.0** | `1962786` | 首个可用版本：热键框选截图 + 本地离线 OCR + 可插拔翻译层 + 托盘常驻 |

带 `-rc` 的是开发过程中的中间快照，用来在需要时回退比对，不是正式发布点。

```powershell
# 查看所有版本
git tag -n1 --sort=version:refname

# 回到某个版本（只读查看，看完记得切回 main）
git checkout v0.1.0
git switch main

# 查看某个版本改了什么
git show v0.2.0 --stat
```

---

## 已知限制

* 仅支持 Windows（截图用 GDI，热键用 Windows 钩子）。
* 翻译需要联网；离线时只能识别文字、无法翻译（架构上已预留本地翻译后端的接入位）。
* 免费翻译端点属于公开接口，可能随时变更或被限流，这是选用「多后端自动回退」的原因。
* 暂不支持「译文覆盖回原位置」的沉浸式翻译，如需可作为后续迭代。
