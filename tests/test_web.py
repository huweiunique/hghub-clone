#!/usr/bin/env python3
"""复刻版网页服务（web/server.py）的功能测试。

跑法（仓库根目录）：
    python -m unittest discover -s tests -v
    # 指定已经在跑的服务（例如 Docker 里的 8081）：
    HGHUB_WEB_URL=http://127.0.0.1:8081 HGHUB_PROXY_URL=http://127.0.0.1:8080 \
        python -m unittest tests.test_web -v
    # 离线：
    ONLINE=0 python -m unittest tests.test_web -v

覆盖：
  * 静态页 / hls.min.js / 健康检查
  * 同源反代：/api/*、/api/up/*（查询串透传）、/api/play -> 8080
  * 封面解密 /proxy/img：真实封面 -> 合法 JPEG，且域名白名单生效
  * 非图床域名 403、缺 url 400
"""

import json
import os
import subprocess
import sys
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_proxy import (  # noqa: E402  复用工具函数
    ONLINE, REPO_ROOT, LocalServer, free_port, http_get, http_post_json,
    wait_health)

WEB_DIR = os.path.join(REPO_ROOT, "web")
WEB_BASE = os.environ.get("HGHUB_WEB_URL", "").rstrip("/")
PROXY_URL = os.environ.get("HGHUB_PROXY_URL", "").rstrip("/")
SAMPLE_ID = int(os.environ.get("HGHUB_SAMPLE_ID", "12"))


def has_openssl():
    try:
        subprocess.run(["openssl", "version"], capture_output=True, timeout=10,
                       check=True)
        return True
    except Exception:
        return False


class WebFunctionalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.own = []
        if WEB_BASE:
            cls.base = WEB_BASE
            wait_health(WEB_BASE + "/health")
        else:
            # 先起 8080 代理（如果没给外部地址），再起 8081 指向它
            if PROXY_URL:
                proxy_base = PROXY_URL
            else:
                cls.proxy = LocalServer(os.path.join(REPO_ROOT, "proxy")).start()
                cls.own.append(cls.proxy)
                proxy_base = cls.proxy.base
            cls.web = LocalServer(WEB_DIR).start({"PROXY_BASE": proxy_base})
            cls.own.append(cls.web)
            wait_health(cls.web.base + "/health")
            cls.base = cls.web.base

    @classmethod
    def tearDownClass(cls):
        for srv in getattr(cls, "own", []):
            srv.stop()

    # ---------- 静态资源 ----------

    def test_index_html(self):
        status, body, headers = http_get(self.base + "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertIn(b"<title>HGhub", body)
        # 前端必须自带 hls.js 的引用（1.2.0.2 起本地化）
        self.assertIn(b"/hls.min.js", body)

    def test_hls_js_is_served_locally(self):
        status, body, headers = http_get(self.base + "/hls.min.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers.get("Content-Type", ""))
        self.assertGreater(len(body), 100_000, "hls.min.js looks truncated")
        self.assertIn(b"Hls", body)

    def test_health(self):
        status, body, _ = http_get(self.base + "/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")

    # ---------- 反代 ----------

    def test_play_is_proxied_to_8080(self):
        status, body, _ = http_post_json(self.base + "/api/play",
                                         {"id": SAMPLE_ID, "ep": 1})
        # 8080 不通时这里会是 5xx；要求至少不是 404（说明路由存在）
        self.assertNotEqual(status, 404, body[:200])
        if ONLINE:
            self.assertEqual(status, 200, body[:300])
            data = json.loads(body)
            self.assertIn("main", (data.get("data") or data).get("streams") or {})

    def test_prefip_route_exists(self):
        # /api/prefip 必须优先于通用 /api/* 反代匹配（否则会去上游 404）
        status, body, _ = http_get(self.base + "/api/prefip?isp=ct", timeout=30)
        self.assertEqual(status, 200, body[:200])
        data = json.loads(body)
        self.assertEqual(data["status"], 1)
        self.assertIn("ips", data["data"])
        self.assertIn("data", data)

    def test_bad_image_host_is_403(self):
        status, body, _ = http_get(
            self.base + "/proxy/img?url=" +
            urllib.parse.quote("https://example.com/a.jpg"))
        self.assertEqual(status, 403)
        self.assertIn("not allowed", json.loads(body)["msg"])

    def test_image_missing_url_is_400(self):
        status, _, _ = http_get(self.base + "/proxy/img")
        self.assertEqual(status, 400)

    def test_proxy_route_forwards_to_proxy(self):
        # /proxy/m3u8 缺 url -> 400（来自 8081 自己的校验，不依赖 8080）
        status, _, _ = http_get(self.base + "/proxy/m3u8?url=")
        self.assertEqual(status, 400)

    def test_unknown_path_404(self):
        status, body, _ = http_get(self.base + "/definitely-not-here")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["status"], 0)

    # ---------- 真实上游：列表透传 + 封面解密 ----------

    @unittest.skipUnless(ONLINE, "ONLINE=0")
    def test_upstream_list_passthrough(self):
        status, body, _ = http_get(self.base + "/api/videos?page=1", timeout=40)
        self.assertEqual(status, 200, body[:200])
        data = json.loads(body)
        items = (data.get("data") or {}).get("items") or []
        self.assertGreater(len(items), 0, "upstream returned empty list")
        self.assertIn("title", items[0])
        self.assertIn("cover", items[0])

    @unittest.skipUnless(ONLINE, "ONLINE=0")
    def test_upstream_query_string_is_forwarded(self):
        # 1.2.0.3 的分页/分类依赖查询串原样透传
        status, body, _ = http_get(self.base + "/api/videos?page=2&cate_id=24",
                                   timeout=40)
        self.assertEqual(status, 200, body[:200])
        data = json.loads(body)
        items = (data.get("data") or {}).get("items") or []
        self.assertGreater(len(items), 0)
        # 分类过滤必须真的生效：返回的剧都应属于 24
        cats = {it.get("cate_id") for it in items if it.get("cate_id") is not None}
        if cats:
            self.assertEqual(cats, {24}, cats)

    @unittest.skipUnless(ONLINE, "ONLINE=0")
    def test_up_path_prefix_is_equivalent(self):
        a = http_get(self.base + "/api/videos?page=1", timeout=40)[1]
        b = http_get(self.base + "/api/up/videos?page=1", timeout=40)[1]
        ja, jb = json.loads(a), json.loads(b)
        self.assertEqual(len(ja["data"]["items"]), len(jb["data"]["items"]))
        self.assertEqual(ja["data"]["items"][0]["id"], jb["data"]["items"][0]["id"])

    @unittest.skipUnless(ONLINE, "ONLINE=0")
    def test_cover_is_decrypted_to_real_jpeg(self):
        """封面修复的核心：/proxy/img 返回合法 JPEG（FFD8FF），不是密文。

        注意：解密靠系统 openssl 命令行。Windows 默认没装 openssl 时，
        /proxy/img 会原样返回密文（原代码的兜底行为），封面就是破图。
        在容器里跑这个测试才能验证真实解密效果。
        """
        _, body, _ = http_get(self.base + "/api/videos?page=1", timeout=40)
        items = json.loads(body)["data"]["items"]
        covers = [it["cover"] for it in items if it.get("cover")]
        self.assertTrue(covers)
        status, img, headers = http_get(
            self.base + "/proxy/img?url=" + urllib.parse.quote(covers[0], safe=""),
            timeout=40)
        self.assertEqual(status, 200)
        # 注意：这里不能检查"本机"有没有 openssl —— 被测服务可能在容器里。
        # 行为约定：解密成功返回合法 JPEG；解不了就原样返回密文，但要标成
        # octet-stream（而不是谎称 image/jpeg），前端据此走占位图。
        if img[:3] == b"\xff\xd8\xff":
            self.assertEqual(headers.get("Content-Type"), "image/jpeg")
            self.assertGreater(len(img), 10_000)
        else:
            if os.environ.get("REQUIRE_DECRYPT") == "1":
                self.fail("被测服务没有解密封面（容器镜像必须装 openssl）")
            self.skipTest("被测服务没有可用的 openssl，返回的是密文（需要容器环境验证）")

    @unittest.skipUnless(ONLINE, "ONLINE=0")
    def test_cover_cache_hit_is_consistent(self):
        _, body, _ = http_get(self.base + "/api/videos?page=1", timeout=40)
        cover = json.loads(body)["data"]["items"][0]["cover"]
        url = self.base + "/proxy/img?url=" + urllib.parse.quote(cover, safe="")
        a = http_get(url, timeout=40)[1]
        b = http_get(url, timeout=40)[1]   # 第二次走内存缓存
        self.assertEqual(a, b)
        self.assertGreater(len(a), 1000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
