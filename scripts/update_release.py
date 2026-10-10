"""更新 GitHub Release 的说明与附件名（用 curl + UTF-8 payload，绕开 PowerShell 编码问题）。

背景：PowerShell 5.1 把中文参数按 GBK 传给原生程序，导致 curl 收到的中文损坏
（附件名里的"翻译"被吞掉、JSON body 报 422）。因此这里一律：
* 用 .NET 以 UTF-8（无 BOM）写 payload 文件；
* 用 curl 的 ``--data-binary @文件`` 发送，不把中文放在命令行参数里。

用法::

    $env:GH_PAT = "..."
    .venv\\Scripts\\python scripts\\update_release.py --notes <说明文件> [--asset-name <新名>]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNER = "Seapeak19"
REPO = "Real-time-translation"
TAG = "v0.6.0"


def api(method: str, url: str, payload: dict | None = None, accept: str = "application/vnd.github+json") -> tuple:
    """调 GitHub API，返回 (状态码, 响应文本)。"""
    token = os.environ.get("GH_PAT", "").strip()
    if not token:
        raise SystemExit("未设置 GH_PAT 环境变量")
    cmd = [
        "curl.exe", "-s", "-S", "-X", method, url,
        "-H", f"Authorization: Bearer {token}",
        "-H", f"Accept: {accept}",
        "-H", "X-GitHub-Api-Version: 2022-11-28",
        "-H", "User-Agent: fanyi-release",
        "-w", "\n__HTTP__%{http_code}",
        "--max-time", "180",
    ]
    tmp: Path | None = None
    if payload is not None:
        tmp = ROOT / ".git" / "_payload.json"
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        cmd += ["-H", "Content-Type: application/json; charset=utf-8", "--data-binary", f"@{tmp}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        body = result.stdout or ""
        code = 0
        if "__HTTP__" in body:
            body, _, code_text = body.rpartition("__HTTP__")
            code = int(code_text.strip() or 0)
        return code, body.strip()
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="更新 Release 说明与附件名")
    parser.add_argument("--notes", help="说明文件路径（Markdown）")
    parser.add_argument("--asset-name", help="要改成的附件名（纯 ASCII 更稳）")
    args = parser.parse_args()

    code, body = api("GET", f"https://api.github.com/repos/{OWNER}/{REPO}/releases/tags/{TAG}")
    if code != 200:
        print(f"取 Release 失败 HTTP {code}: {body[:200]}")
        return 1
    release = json.loads(body)
    release_id = release["id"]
    print(f"Release #{release_id}  附件 {len(release.get('assets', []))} 个")
    for asset in release.get("assets", []):
        print(f"  - {asset['name']}  {asset['size'] / 1048576:.2f} MB")

    failed = False

    # 1) 改附件名
    if args.asset_name:
        for asset in release.get("assets", []):
            if asset["name"] == args.asset_name:
                print(f"附件名已是 {args.asset_name}，跳过")
                continue
            code, body = api(
                "PATCH",
                f"https://api.github.com/repos/{OWNER}/{REPO}/releases/assets/{asset['id']}",
                {"name": args.asset_name},
            )
            if code == 200:
                print(f"附件改名成功: {asset['name']} -> {json.loads(body)['name']}")
            else:
                print(f"附件改名失败 HTTP {code}: {body[:200]}")
                failed = True

    # 2) 更新说明
    if args.notes:
        notes = Path(args.notes).read_text(encoding="utf-8")
        code, body = api(
            "PATCH",
            f"https://api.github.com/repos/{OWNER}/{REPO}/releases/{release_id}",
            {"body": notes},
        )
        if code == 200:
            updated = json.loads(body)
            print(f"说明更新成功（{len(updated['body'])} 字符）")
        else:
            print(f"说明更新失败 HTTP {code}: {body[:300]}")
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
