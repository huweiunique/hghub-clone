#!/usr/bin/env python3
"""HGhub 访问密钥（可选伸延模块）。

上游 web/server.py 与 proxy/server.py 都保持原样；鉴权逻辑全部放在这里，
由本地补丁脚本（tools/apply_local_patches.py）打 3~4 个极小的钩子接入。
这样上游更新时 git 几乎不会冲突，重跑一次补丁脚本即可。

接入契约（**故意做得极窄**，只看协议相关变量，不看内部函数名）：

  上游 Handler  ├─ do_GET(self)  ->  parsed / qs 对应 self.path
                └─ do_POST(self) ->  parsed 对应 self.path

  pre_serve(handler, method) 返回 (status, body, content_type, headers)
      status 非 0 表示"直接回这个响应并结束"（鉴权失败/登录 302）；
      返回 0 表示放行，headers 里可能带 Set-Cookie。

  未启用密钥（HGHUB_ACCESS_KEY 为空）时 pre_serve 恒返回放行，
  且额外头为空 —— 对上游行为零影响。

环境变量：
  HGHUB_ACCESS_KEY    访问密钥（openssl rand -hex 32 生成），为空即关闭
  HGHUB_ALLOW_IPS     可选，逗号分隔的来源 IP 白名单（与密钥同时生效）
  HGHUB_TRUST_PROXY=1 可选，信任 X-Forwarded-For（放在反代后面时开）
  HGHUB_COOKIE_SECURE=1 可选，强制 Cookie 带 Secure（HTTPS 部署时开）
"""

import hashlib
import hmac
import json
import logging
import os
import urllib.parse

log = logging.getLogger("hghub-auth")

ACCESS_KEY = os.environ.get("HGHUB_ACCESS_KEY", "").strip()
ACCESS_COOKIE = "hghub_auth"
ACCESS_MAX_AGE = 30 * 24 * 3600
# Cookie 里放的是 HMAC 派生值而不是明文 key：泄了 Cookie 也拿不到可重新签发的 key，
# 换 key 后所有旧 Cookie 立即失效。
ACCESS_TOKEN = (
    hmac.new(ACCESS_KEY.encode(), b"hghub-access-v1", hashlib.sha256).hexdigest()
    if ACCESS_KEY else ""
)
ALLOW_IPS = {ip.strip() for ip in os.environ.get("HGHUB_ALLOW_IPS", "").split(",")
             if ip.strip()}

# 免鉴权路径：首页/静态资源要给用户一个"输入 key"的入口，/health 给容器探活。
# /health 只回 {"status":"ok"}，不泄露内容。
PUBLIC_PATHS = {"/", "/index.html", "/hls.min.js", "/health"}
# 本地扩展的静态文件（前端密钥输入框等）同样必须免鉴权，否则开密钥后页面自己都加载不了
PUBLIC_PREFIXES = ("/local_ext/",)

ENABLED = bool(ACCESS_KEY)


def _client_ip(handler):
    if os.environ.get("HGHUB_TRUST_PROXY", "") == "1":
        xff = handler.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
    return handler.client_address[0]


def _cookie_token(handler):
    for part in (handler.headers.get("Cookie", "") or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == ACCESS_COOKIE:
            return value
    return ""


def _ok(seconds):
    return hmac.compare_digest(seconds, ACCESS_TOKEN)


def authorized(handler, path, qs):
    """判断该请求是否已授权。未开启密钥时恒为 True（对上游零影响）。"""
    if not ENABLED:
        return True
    if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
        return True
    if ALLOW_IPS and _client_ip(handler) not in ALLOW_IPS:
        return False
    given = (qs.get("key") or [""])[0]
    if given and hmac.compare_digest(given, ACCESS_KEY):
        return True
    token = _cookie_token(handler)
    return bool(token) and hmac.compare_digest(token, ACCESS_TOKEN)


def auth_cookie_header(handler):
    parts = [f"{ACCESS_COOKIE}={ACCESS_TOKEN}", "Path=/",
             f"Max-Age={ACCESS_MAX_AGE}", "HttpOnly", "SameSite=Lax"]
    if os.environ.get("HGHUB_COOKIE_SECURE", "") == "1" or \
            handler.headers.get("X-Forwarded-Proto", "") == "https":
        parts.append("Secure")
    return ("Set-Cookie", "; ".join(parts))


def pre_serve(handler, method, path=None, extra_paths=()):
    """请求进入上游路由前调用。

    返回 (status, body, content_type, headers)：
      status == 0  -> 放行（headers 里可能有 Set-Cookie）
      status != 0  -> 直接返回这个响应
    """
    raw = path if path is not None else handler.path
    parsed = urllib.parse.urlparse(raw)
    p = parsed.path
    qs = urllib.parse.parse_qs(parsed.query)

    if not ENABLED:
        return (0, b"", "", [])

    # 首屏带 ?key=（正确）：下发 Cookie + 302 去掉 URL 里的 key，
    # 避免密钥留在浏览器历史/Referer 里。必须在"公共路径放行"之前处理。
    if method == "GET" and p in ("/", "/index.html"):
        given = (qs.get("key") or [""])[0]
        if given:
            if not hmac.compare_digest(given, ACCESS_KEY):
                log.warning("access key rejected from %s", _client_ip(handler))
                return (0, b"", "", [])  # 首页照常打开，前端会弹输入框
            return (302, b"", "text/plain; charset=utf-8",
                    [auth_cookie_header(handler), ("Location", "/")])

    # 公共路径免鉴权：首页/静态资源/local_ext（页面自己的脚本）
    public = PUBLIC_PATHS | set(extra_paths)
    if p in public or p.startswith(PUBLIC_PREFIXES):
        return (0, b"", "", [])

    if authorized(handler, p, qs):
        return (0, b"", "", [])
    log.warning("unauthorized %s %s from %s", method, p, _client_ip(handler))
    body = json.dumps({"status": 0, "msg": "unauthorized: 缺少或错误的访问 key"},
                      ensure_ascii=False).encode()
    return (401, body, "application/json", [])


def status_info():
    return {"enabled": ENABLED, "ip_allowlist": sorted(ALLOW_IPS)}
