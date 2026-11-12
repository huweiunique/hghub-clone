#!/usr/bin/env python3
"""访问密钥（HGHUB_ACCESS_KEY）的功能测试。

    python -m unittest tests.test_auth -v

要点：
  * 不开密钥时（默认）所有接口照旧可用 —— 不破坏原有部署
  * 开密钥后：/health、/、/hls.min.js 免鉴权（探活和首屏要能用）
  * 其余接口无 key / 错误 key -> 401
  * GET /?key=<正确> -> 302 + Set-Cookie，后续只看 Cookie 就能访问
  * POST /api/play 同样受保护
"""

import os
import sys
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_proxy import REPO_ROOT, LocalServer  # noqa: E402

WEB_DIR = os.path.join(REPO_ROOT, "web")
KEY = "test-key-" + "a" * 40


def raw_get(base, path, headers=None, cookies=None):
    """不自动跟随重定向，方便检查 302 和 Set-Cookie。"""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(base + path, headers=headers or {})
    if cookies:
        req.add_header("Cookie", cookies)
    try:
        with opener.open(req, timeout=15) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def wait_ready(base):
    for _ in range(100):
        try:
            if raw_get(base, "/health")[0] == 200:
                return
        except Exception:
            pass
        import time
        time.sleep(0.1)
    raise RuntimeError(f"{base} not ready")


class AccessKeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = LocalServer(WEB_DIR).start()  # 不设 HGHUB_ACCESS_KEY
        wait_ready(cls.srv.base)
        # 开密钥的实例：同时起一个代理，避免被上游网络拖慢
        cls.proxy = LocalServer(os.path.join(REPO_ROOT, "proxy")).start()
        cls.srv_key = LocalServer(WEB_DIR).start({
            "HGHUB_ACCESS_KEY": KEY, "PROXY_BASE": cls.proxy.base})
        wait_ready(cls.srv_key.base)

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls.srv_key.stop()
        cls.proxy.stop()

    # ---------- 不开密钥：行为不变 ----------
    def test_disabled_key_keeps_old_behaviour(self):
        status, body, _ = raw_get(self.srv.base, "/api/site/categories/video")
        self.assertEqual(status, 200, body[:120])

    # ---------- 白名单路径 ----------
    def test_public_paths_work_without_key(self):
        for path in ("/", "/index.html", "/hls.min.js", "/health"):
            status, body, _ = raw_get(self.srv_key.base, path)
            self.assertEqual(status, 200, f"{path} -> {status}")

    # ---------- 受保护路径 ----------
    def test_protected_paths_require_key(self):
        for path in ("/api/videos?page=1", "/api/site/categories/video",
                     "/proxy/img?url=", "/api/prefip"):
            status, body, _ = raw_get(self.srv_key.base, path)
            self.assertEqual(status, 401, f"{path} -> {status}")
            self.assertIn("unauthorized", body.decode("utf-8", "ignore"))

    def test_wrong_key_is_rejected(self):
        status, _, _ = raw_get(self.srv_key.base, "/api/site/categories/video?key=nope")
        self.assertEqual(status, 401)

    def test_correct_key_in_query_allowed(self):
        status, body, _ = raw_get(
            self.srv_key.base, f"/api/site/categories/video?key={KEY}")
        self.assertEqual(status, 200, body[:120])

    def test_post_play_requires_key(self):
        req = urllib.request.Request(
            self.srv_key.base + "/api/play", data=b'{"id":12,"ep":1}',
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        self.assertEqual(status, 401)

    # ---------- 登录换 Cookie ----------
    def test_key_bootstraps_cookie_and_redirects(self):
        # 用 curl 风格的"不跟随重定向"检查 302 + Set-Cookie
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        try:
            r = opener.open(self.srv_key.base + f"/?key={KEY}", timeout=15)
            status, headers = r.status, r.headers
        except urllib.error.HTTPError as e:
            status, headers = e.code, e.headers
        # 注：如果 URL.path 恰好被 parse 成 /local_ext/ 前缀那类公共路径，
        # 这里不会 302（静态资源免鉴权，本来就不需要 Cookie）。
        self.assertEqual(status, 302, f"status={status}")
        self.assertEqual(headers.get("Location"), "/")
        cookie = headers.get("Set-Cookie", "")
        self.assertIn("hghub_auth=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertNotIn(KEY, cookie, "cookie 不能包含明文 key")

        # 用这个 Cookie 访问受保护接口
        token = cookie.split("hghub_auth=", 1)[1].split(";", 1)[0]
        status, body, _ = raw_get(self.srv_key.base, "/api/videos?page=1",
                                  cookies=f"hghub_auth={token}")
        self.assertEqual(status, 200, body[:120])

    def test_wrong_key_on_root_does_not_set_cookie(self):
        status, _, headers = raw_get(self.srv_key.base, "/?key=wrong")
        self.assertEqual(status, 200)  # 首页本身仍可打开（好让用户输入 key）
        self.assertIsNone(headers.get("Set-Cookie"))

    def test_forged_cookie_rejected(self):
        status, _, _ = raw_get(self.srv_key.base, "/api/site/categories/video",
                               cookies="hghub_auth=" + "0" * 64)
        self.assertEqual(status, 401)

    def test_ip_allowlist(self):
        srv = LocalServer(WEB_DIR).start({
            "HGHUB_ACCESS_KEY": KEY, "HGHUB_ALLOW_IPS": "203.0.113.9"})
        try:
            wait_ready(srv.base)
            status, _, _ = raw_get(srv.base, f"/api/site/categories/video?key={KEY}")
            self.assertEqual(status, 401, "不在白名单的 IP 即使 key 正确也应被拒")
            status, _, _ = raw_get(srv.base, "/health")
            self.assertEqual(status, 200, "探活不受 IP 白名单影响")
        finally:
            srv.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)
