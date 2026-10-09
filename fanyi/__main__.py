"""支持 ``python -m fanyi`` 直接启动。"""

from __future__ import annotations

import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main())
