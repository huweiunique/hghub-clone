#!/usr/bin/env python3
"""把本地扩展（local_ext/）以"最小钩子"方式接入上游代码。

    python tools/apply_local_patches.py           # 打补丁（幂等，可反复运行）
    python tools/apply_local_patches.py --check   # 只检查，不写文件
    python tools/apply_local_patches.py --revert  # 撤掉补丁（回到纯上游代码）

为什么要这样：上游 vps1986/hghub-clone 还在更新，如果直接改 web/server.py、
web/index.html 的正文，每次 merge 都会冲突。所以：
  * 上游文件只插入 **锚点 + BEGIN/END 标记包围的几行**（总行数 < 20）；
  * 真正的逻辑（鉴权、IP 白名单、Cookie 签发）全在 local_ext/ 里；
  * 前端注入逻辑在 local_ext/web_patch.js 里，index.html 只加一行 <script>。

上游大改后如果锚点找不到，脚本会明确报错，告诉你该更新哪个锚点，
而不是静默写出一个坏文件。所有改动都是幂等的：已经打过就跳过。
"""

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BEGIN = "HGHUB_LOCAL_PATCH BEGIN (tools/apply_local_patches.py)"
END = "HGHUB_LOCAL_PATCH END"


def _marker(rel_path, which, syntax=None):
    """按文件类型返回合法注释形式的标记行（不含缩进）。"""
    if syntax == "js":
        return f"/* ==== HGHUB_LOCAL_PATCH {which} ==== */"
    if rel_path.endswith(".py"):
        return f"# ==== HGHUB_LOCAL_PATCH {which} (tools/apply_local_patches.py) ===="
    if rel_path.endswith((".html", ".htm")):
        return f"<!-- HGhub local patch {which.lower()} (tools/apply_local_patches.py) -->"
    return f"/* ==== HGHUB_LOCAL_PATCH {which} ==== */"


def _marker_block(rel_path, insert):
    """按文件类型生成带注释的补丁块：Python 用 #，其余用 /* */。"""
    if rel_path.endswith(".py"):
        return (f"# ==== {BEGIN} ====\n{insert}"
                f"# ==== {END} ====\n")
    return (f"/* ==== {BEGIN} ==== */\n{insert}"
            f"/* ==== {END} ==== */\n")

PATCHES = {}


def patch(rel_path, name, anchor, insert, where="after", syntax=None):
    """注册一个补丁：在 anchor 出现处之后/之前插入 insert（若尚未插入）。"""
    PATCHES.setdefault(rel_path, []).append(
        {"name": name, "anchor": anchor, "insert": insert, "where": where, "syntax": syntax})


# ---------------------------------------------------------------------------
# 1) web/server.py —— 访问密钥：导入 + 3 个钩子
# ---------------------------------------------------------------------------
patch(
    "web/server.py", "import local_ext",
    "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer",
    """
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from local_ext import access_key as _local_auth  # noqa: E402  本地扩展，上游更新不受影响
LOCAL_EXT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "local_ext")
""",
)

patch(
    "web/server.py", "auth hook in do_GET",
    "qs = urllib.parse.parse_qs(parsed.query)",
    """
        _st, _body, _ctype, _hdrs = _local_auth.pre_serve(self, "GET")
        self._local_headers = _hdrs
        if _st:
            self._send(_st, _body, _ctype or "application/json")
            return
""",
)

patch(
    "web/server.py", "auth hook in do_POST",
    'def do_POST(self):\n        parsed = urllib.parse.urlparse(self.path)',
    """
        _st, _body, _ctype, _hdrs = _local_auth.pre_serve(self, "POST")
        self._local_headers = _hdrs
        if _st:
            self._send(_st, _body, _ctype or "application/json")
            return
""",
    where="after-anchor-line",  # 插在 parsed = ... 这一行之后
)

patch(
    "web/server.py", "flush extra headers in _send",
    'self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")',
    """
        for _k, _v in getattr(self, "_local_headers", None) or []:
            self.send_header(_k, _v)
        self._local_headers = []
""",
)

patch(
    "web/server.py", "serve local_ext static",
    'if path == "/hls.min.js":',
    """if path.startswith("/local_ext/") and "/" not in path[len("/local_ext/"):]:
    _f = os.path.join(LOCAL_EXT_DIR, path.rsplit("/", 1)[1])
    try:
        with open(_f, "rb") as fh:
            self._send(200, fh.read(), "application/javascript; charset=utf-8")
    except FileNotFoundError:
        self._json(404, {"status": 0, "msg": "local_ext not found"})
    return
""",
    where="before-anchor-line",
)

# ---------------------------------------------------------------------------
# 2) web/index.html —— 前端：只加一行 <script>，逻辑全在 local_ext/web_patch.js
#    必须放在 </head> 之前（不能塞进 <style> 里，否则标记会被当成 CSS 文本渲染出来）
# ---------------------------------------------------------------------------
patch(
    "web/index.html", "local frontend patch",
    "</head>",
    """<script src="/local_ext/web_patch.js"></script>
""",
    where="before-anchor-line",
)

# ---------------------------------------------------------------------------
# 3) android/.../assets/hghub/index.html —— APK 内置页面同样是本地副本
# ---------------------------------------------------------------------------
patch(
    "android/app/src/main/assets/hghub/index.html", "local frontend patch (apk)",
    "</head>",
    """<script src="/local_ext/web_patch.js"></script>
""",
    where="before-anchor-line",
)


# ---------------------------------------------------------------------------
# 播放增强在上游脚本之后加载，复用其播放器、进度与历史存储。
for _page in ("web/index.html", "android/app/src/main/assets/hghub/index.html"):
    patch(_page, "player enhancements", "</body>",
          '<script src="/local_ext/player_patch.js"></script>\n',
          where="before-anchor-line")
    patch(_page, "unified player controls", "</body>",
          '<script src="/local_ext/player_controls.js"></script>\n',
          where="before-anchor-line")
    patch(_page, "GPU video enhancement", "</body>",
          '<script src="/local_ext/video_enhance.js"></script>\n',
          where="before-anchor-line")
    patch(_page, "immersive viewing UI", "</body>",
          '<script src="/local_ext/viewing_ui.js"></script>\n',
          where="before-anchor-line")
    patch(_page, "bounded player recovery", '    if (data && data.fatal && !tried){',
          'if (window.hgRecoverHls && window.hgRecoverHls(hls, data, tried)) return;\n',
          where="before-anchor-line", syntax="js")
    patch(_page, "managed resume", '    if (prog && prog.ep === curEp && prog.t > 10 && prog.dur && prog.t < prog.dur - 10){',
          'if (window.__hgResumeManaged) return; // 本地扩展使用媒体就绪事件恢复，避免旧定时器串集。\n',
          where="before-anchor-line", syntax="js")

# CF 设置在业务脚本后加载；iOS 同时随包注入，可连接未部署扩展的旧后端。
for _page in ("web/index.html", "android/app/src/main/assets/hghub/index.html"):
    patch(_page, "preferred IP settings", "</body>",
          '<script src="/local_ext/prefip_patch.js"></script>\n',
          where="before-anchor-line")

patch("web/server.py", "preferred IP refresh", 'if path == "/api/prefip":',
      '''if path == "/api/prefip":
    from local_ext import preferred_ip
    preferred_ip.serve(self, qs)
    return
''', where="before-anchor-line")

# 应用逻辑
# ---------------------------------------------------------------------------
BEGIN_RE = re.compile(r"^[ \t]*(?:#|/\*|<!--).*?"
                      r"(?:HGHUB_LOCAL_PATCH BEGIN|HGhub local patch begin).*$")
END_RE = re.compile(r"^[ \t]*(?:#|/\*|<!--).*?"
                    r"(?:HGHUB_LOCAL_PATCH END|HGhub local patch end).*$")
INDENT_RE = re.compile(r"^[ \t]*")


def _strip_local(text):
    """逐行去掉补丁块（BEGIN 行到 END 行，含两端）。不用跨行贪婪正则 ——
    之前那样写一旦遇到缺 END 的文件会把整份文件吞掉。"""
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        if not skipping and BEGIN_RE.match(line):
            skipping = True
            continue
        if skipping:
            if END_RE.match(line):
                skipping = False
            continue
        out.append(line)
    if skipping:
        raise SystemExit("[patch] 文件里有 BEGIN 但找不到 END，拒绝自动回滚，请手动检查")
    return "".join(out)


def _patch_blocks(text):
    """按行扫描，返回每个补丁块的内容（BEGIN 与 END 之间的行，不含标记）。"""
    blocks, cur = [], None
    for line in text.splitlines():
        if cur is None and BEGIN_RE.match(line):
            cur = []
            continue
        if cur is not None:
            if END_RE.match(line):
                blocks.append("\n".join(cur))
                cur = None
            else:
                cur.append(line)
    return blocks


def _is_applied(text, rel_path, spec):
    """按块判断这个补丁是否已应用（多个补丁共用同一种标记，必须逐块配对）。"""
    key = spec["insert"].strip().splitlines()[0].strip()
    return any(key and key in blk for blk in _patch_blocks(text))


def apply_one(text, spec, rel_path):
    if _is_applied(text, rel_path, spec):
        return text, "already"
    anchor = spec["anchor"]
    if text.count(anchor) == 0:
        raise SystemExit(
            f"[patch] 找不到锚点（{spec['name']}）:\n    {anchor!r}\n"
            f"上游可能改了这段代码，请到 tools/apply_local_patches.py 里更新锚点。")
    if text.count(anchor) > 1 and "def do_POST" not in anchor:
        raise SystemExit(f"[patch] 锚点不唯一（{spec['name']}）: {anchor!r}")

    block = _marker_block(rel_path, spec["insert"])
    if spec["where"] == "after-anchor-line":
        # 插在锚点最后一行的下一行，保持缩进
        idx = text.index(anchor) + len(anchor)
        nl = text.index("\n", idx) + 1
        return text[:nl] + block + text[nl:], "applied"
    if spec["where"] == "before-anchor-line":
        # 插在锚点起始行的前面（锚点可能是缩进块里的语句）。
        # 约定：spec["insert"] 已按锚点的缩进书写，标记行用锚点缩进，
        # 补丁块整体再多缩进一级，保证不落在锚点上一行的 if 体里。
        start = text.rindex("\n", 0, text.index(anchor)) + 1
        indent = re.match(r"[ \t]*", text[start:]).group(0)
        marker = indent
        body = indent + "    "
        lines = [indent + _marker(rel_path, "BEGIN", spec.get("syntax"))]
        for ln in spec["insert"].strip("\n").split("\n"):
            lines.append(((indent + ln) if ln.strip() else ln))
        lines.append(indent + _marker(rel_path, "END", spec.get("syntax")))
        return text[:start] + "\n".join(lines) + "\n" + text[start:], "applied"

    idx = text.index(anchor) + len(anchor)
    nl = text.index("\n", idx) + 1
    return text[:nl] + block + text[nl:], "applied"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查，不写文件")
    ap.add_argument("--revert", action="store_true", help="撤掉所有本地补丁")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    changed = 0
    for rel, specs in PATCHES.items():
        path = os.path.join(ROOT, rel.replace("/", os.sep))
        if not os.path.exists(path):
            print(f"[patch] 跳过不存在的文件 {rel}")
            continue
        with open(path, encoding="utf-8") as f:
            original = f.read()

        if args.revert:
            text = _strip_local(original)
        else:
            text = original
            for spec in specs:
                text, how = apply_one(text, spec, rel)
                print(f"[patch] {rel}: {spec['name']}: {how}")

        if text == original:
            continue
        changed += 1
        if args.check:
            print(f"[patch] {rel} 需要修改（--check 模式不写入）")
        else:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            print(f"[patch] 已写入 {rel}")

    print(f"[patch] 完成：{changed} 个文件{'会被' if args.check else '被'}修改")
    if args.check and args.revert:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
