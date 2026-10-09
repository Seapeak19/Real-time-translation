"""生成程序图标 assets/fanyi.ico 与应用内的托盘图标 png。

PyInstaller 与任务栏需要 .ico；托盘图标则直接用 Qt 画（见 fanyi/ui/tray.py），
这里额外落一份 png 便于文档与外部使用。

用法::

    .venv\\Scripts\\python scripts\\make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

ASSETS = ROOT / "assets"
ICON_PATH = ASSETS / "fanyi.ico"
PNG_PATH = ASSETS / "fanyi.png"

#: 与托盘图标保持一致的配色
BG = (37, 99, 235, 255)  # #2563EB
FG = (255, 255, 255, 255)

#: .ico 里包含的尺寸
SIZES = [16, 24, 32, 48, 64, 128, 256]

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]


def load_font(size: int):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render(size: int, supersample: int = 4) -> Image.Image:
    """按 4 倍超采样绘制再缩小，得到边缘平滑的小图标。"""
    scale = size * supersample
    image = Image.new("RGBA", (scale, scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    radius = int(scale * 0.22)
    draw.rounded_rectangle([0, 0, scale - 1, scale - 1], radius=radius, fill=BG)

    font = load_font(int(scale * 0.64))
    text = "译"
    # 用实测包围盒居中，避免不同字体的基线差异导致偏移
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(
        ((scale - (right - left)) / 2 - left, (scale - (bottom - top)) / 2 - top),
        text,
        font=font,
        fill=FG,
    )
    return image.resize((size, size), Image.LANCZOS)


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)

    frames = [render(size) for size in SIZES]
    # 256 单独作为 png 输出
    frames[-1].save(PNG_PATH)
    # .ico 需要显式指定各尺寸，Pillow 会把最大的一张缩放，这里直接给出全部帧
    frames[-1].save(ICON_PATH, format="ICO", sizes=[(s, s) for s in SIZES])

    print(f"已生成 {PNG_PATH.relative_to(ROOT)}  ({PNG_PATH.stat().st_size} 字节)")
    print(f"已生成 {ICON_PATH.relative_to(ROOT)}  ({ICON_PATH.stat().st_size} 字节, 含 {SIZES})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
