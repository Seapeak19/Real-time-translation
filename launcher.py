"""打包入口脚本。

单独放一个仓库根目录的启动文件，而不是直接冻结 ``fanyi/__main__.py``，
原因是后者用的是包内相对导入（``from .app import main``）。
作为顶层脚本被 PyInstaller 冻结时包上下文不一定成立，
用一个做**绝对导入**的小启动器最稳，也让打包配置更直观。
"""

from __future__ import annotations

import sys


def main() -> int:
    from fanyi.app import main as app_main

    return app_main()


if __name__ == "__main__":
    sys.exit(main())
