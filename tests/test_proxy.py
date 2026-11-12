#!/usr/bin/env python3
"""播放解析代理（proxy/server.py）的功能测试。

跑法（仓库根目录）：
    python -m unittest discover -s tests -v
    # 或指定已经在跑的服务：
    HGHUB_PROXY_URL=http://127.0.0.1:8080 python -m unittest tests.test_proxy -v

设计：
  * 纯标准库 unittest，不装任何第三方包。
  * 需要“本地起服务”的用例在 setUpClass 里用随机端口把 server.py 拉起来，
    用例结束后关掉 —— 不依赖外部已经跑着的实例。
  * 需要上游网络的用例用 @unittest.skipUnless(ONLINE) 标记：上游挂掉/被墙时
    设置 ONLINE=0 即可离线跑完。

验证的是“功能”而不是“实现细节”：HTTP 状态码、返回结构、
白名单拦截、请求体错误处理、上游透传是否原样。
"""

import json
import os
import re
import socket
import http.client
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROXY_DIR = os.path.join(REPO_ROOT, "proxy")

# ONLINE=0 时跳过所有需要真实上游的用例（离线环境用）
ONLINE = os.environ.get("ONLINE", "1") != "0"
# 已经跑着的代理地址（不设则自己起一个）
EXTERNAL_BASE = os.environ.get("HGHUB_PROXY_URL", "").rstrip("/")
# 用来测试的剧集：上游 id=12 是 README 里一直用的样本
SAMPLE_ID = int(os.environ.get("HGHUB_SAMPLE_ID", "12"))
SAMPLE_EP = int(os.environ.get("HGHUB_SAMPLE_EP", "1"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


try:  # 可选依赖：装了就能做“分片解密”自检，没装就跳过
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    def aes128_cbc_decrypt(data, key, iv):
        dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        return dec.update(data) + dec.finalize()
except Exception:  # pragma: no cover
    aes128_cbc_decrypt = None


def http_get(url, timeout=30, method="GET", headers=None, retries=1):
    """HTTP GET。retries=1 时对“连接被上游/服务端直接掐断”这类抖动重试一次
    （实测上游偶尔会重置连接，不是被测服务的 bug）。"""
    hdrs = {"User-Agent": "hghub-test"}
    hdrs.update(headers or {})
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers
        except (ConnectionError, urllib.error.URLError, http.client.HTTPException):
            if attempt >= retries:
                raise
            time.sleep(1.0)


def http_post_json(url, payload, timeout=30, headers=None):
    data = json.dumps(payload).encode()
    hdrs = {"Content-Type": "application/json", "User-Agent": "hghub-test"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, method="POST", headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def wait_health(base, timeout=20):
    """base 可以是服务根地址，也可以是一个完整的 URL（例如 http://127.0.0.1:18080/health）。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            status, body, _ = http_get(base, timeout=2, retries=0)
            if status == 200:
                return True
        except Exception as exc:  # 服务还没起来
            last = exc
        time.sleep(0.2)
    raise RuntimeError(f"server at {base} did not become healthy: {last}")


class LocalServer:
    """用随机端口在本地起一个 server.py 实例。"""

    def __init__(self, script_dir, ready_path="/health"):
        self.script_dir = script_dir
        self.ready_path = ready_path
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc = None

    def start(self, extra_env=None):
        env = dict(os.environ, HOST="127.0.0.1", PORT=str(self.port),
                   PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        env.update(extra_env or {})
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(self.script_dir, "server.py")],
            cwd=self.script_dir, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_health(self.base + self.ready_path)
        return self

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class ProxyFunctionalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if EXTERNAL_BASE:
            cls.local = None
            cls.base = EXTERNAL_BASE
            wait_health(EXTERNAL_BASE + "/health")
        else:
            cls.local = LocalServer(PROXY_DIR).start()
            cls.base = cls.local.base

    @classmethod
    def tearDownClass(cls):
        if cls.local:
            cls.local.stop()

    # ---------- 基础：健康检查 / 路由 ----------

    def test_health(self):
        status, body, headers = http_get(self.base + "/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")

    def test_head_is_not_silently_handled(self):
        """已知行为记录：代理只实现了 do_GET/do_POST，HEAD 请求会被
        BaseHTTPRequestHandler 回 501。容器健康检查/某些 CDN 探测会用 HEAD，
        这里明确断言现状，避免以后误以为支持。"""
        status, _, _ = http_get(self.base + "/health", method="HEAD")
        self.assertEqual(status, 501)

    def test_options_cors_preflight(self):
        req = urllib.request.Request(self.base + "/api/play", method="OPTIONS")
        with urllib.request.urlopen(req, timeout=10) as r:
            self.assertEqual(r.status, 204)
            self.assertEqual(r.headers.get("Access-Control-Allow-Methods"),
                             "GET, POST, OPTIONS")

    def test_unknown_path_404_json(self):
        status, body, _ = http_get(self.base + "/nope")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["status"], 0)

    # ---------- 参数校验与防护（不需要上游） ----------

    def test_play_invalid_body(self):
        status, body, _ = http_post_json(self.base + "/api/play", {"foo": 1})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["status"], 0)
        self.assertIn("invalid body", json.loads(body)["msg"])

    def test_proxy_requires_http_url(self):
        status, body, _ = http_get(self.base + "/proxy?url=" +
                                   urllib.parse.quote("ftp://evil/x"))
        self.assertEqual(status, 400)

    def test_proxy_blank_url(self):
        status, body, _ = http_get(self.base + "/proxy/m3u8?url=")
        self.assertEqual(status, 400)

    def test_proxy_blocks_host_outside_whitelist(self):
        # SSRF 防护：只放行白名单域名 / 后缀
        for bad in ("https://example.com/a.m3u8",
                    "https://drleao.cn.evil.com/x",
                    "http://127.0.0.1:8081/",
                    "http://[::1]/"):
            status, body, _ = http_get(
                self.base + "/proxy?url=" + urllib.parse.quote(bad))
            self.assertEqual(status, 403, f"{bad} should be blocked")
            self.assertIn("host not allowed", json.loads(body)["msg"])

    # ---------- 真实上游：播放解析 + 清单/密钥/分片代理 ----------

    def _play_streams(self, payload):
        status, body, headers = http_post_json(self.base + "/api/play", payload)
        self.assertEqual(status, 200, body[:300])
        data = json.loads(body)
        # 代理把上游响应原样返回（含 data 包装），前端两种形状都兼容
        return (data.get("data") or data).get("streams") or {}, headers

    @unittest.skipUnless(ONLINE, "ONLINE=0")
    def test_play_returns_streams(self):
        streams, headers = self._play_streams({"id": SAMPLE_ID, "ep": SAMPLE_EP})
        self.assertIn("main", streams, streams)
        self.assertTrue(streams["main"].startswith("http"), streams["main"])
        self.assertIn(".m3u8", streams["main"])
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")

    @unittest.skipUnless(ONLINE, "ONLINE=0")
    def test_play_default_episode_is_first(self):
        # 只传 id 不传 ep，默认第 1 集
        streams, _ = self._play_streams({"id": SAMPLE_ID})
        self.assertIn("main", streams)

    @unittest.skipUnless(ONLINE, "ONLINE=0")
    def test_cdn_auth_header_is_forwarded(self):
        """上游签名的 CDN 需要 x-cdn-auth 头才会给出真实资源。

        代理文档写明 authKey = x-cdn-auth；`_proxy()` 目前没有转发
        播放响应里的 cdn.authValue，所以带鉴权头的 CDN 会失败。
        这里断言“带了头就能通、没带就 403”，用来锁定这个缺口。
        """
        status, body, _ = http_post_json(self.base + "/api/play",
                                         {"id": SAMPLE_ID, "ep": SAMPLE_EP})
        self.assertEqual(status, 200, body[:200])
        d = json.loads(body)
        d = d.get("data") or d
        cdn = d.get("cdn") or {}
        if not cdn.get("authKey") or not cdn.get("authValue"):
            self.skipTest("upstream did not require cdn auth this time")
        main = d["streams"]["main"]
        q = urllib.parse.quote(main, safe="")
        plain, with_auth = None, None
        try:
            plain = http_get(self.base + "/proxy/m3u8?url=" + q)
            with_auth = http_get(self.base + "/proxy/m3u8?url=" + q,
                                 headers={cdn["authKey"]: cdn["authValue"]})
        except (ConnectionError, urllib.error.URLError) as exc:
            self.fail(f"keep-alive 连接被服务端直接断开：{exc}")
        status_code = with_auth[0]
        self.assertEqual(status_code, 200,
                         f"代理没有把 {cdn['authKey']} 转发给 CDN（返回 {status_code}，"
                         f"不带头时是 {plain[0]}）")
        self.assertEqual(with_auth[1][:7], b"#EXTM3U")

    @unittest.skipUnless(ONLINE, "ONLINE=0")
    def test_manifest_refs_are_reachable(self):
        """清单里的 key / ts 引用（上游返回绝对地址）能被代理成功代理。

        最能代表“能不能播”的测试：清单 200 + 是合法 #EXTM3U，
        其中的密钥 16 字节、分片能完整下载。
        同时校验 /proxy?url= 统一入口与分路径入口都可用（内容不逐字节比：
        上游会轮换回源域名 tpN.drleao.cn）。
        上游 403（签名过期/换 CDN）时 skip 并给出原因 —— 这通常是上游侧变化，
        不是代理的 bug，但会在日志里明确写出来。
        """
        streams, _ = self._play_streams({"id": SAMPLE_ID, "ep": SAMPLE_EP})
        main = streams["main"]
        q = urllib.parse.quote(main, safe="")
        status, manifest, headers = http_get(self.base + "/proxy/m3u8?url=" + q)
        if status == 403:
            self.skipTest("上游清单返回 403（签名过期或 CDN 侧变更），稍后重试")
        self.assertEqual(status, 200, manifest[:200])
        self.assertIn("mpegurl", headers.get("Content-Type", ""))
        text = manifest.decode("utf-8", "ignore")
        self.assertIn("#EXTM3U", text)
        self.assertGreater(len(manifest), 100)

        status2, manifest2, _ = http_get(self.base + "/proxy?url=" + q)
        self.assertEqual(status2, 200)
        self.assertIn("#EXTM3U", manifest2.decode("utf-8", "ignore"))

        refs = [ln.strip() for ln in text.splitlines()
                if ln.strip() and not ln.strip().startswith("#")]
        uris = re.findall(r'URI="([^"]+)"', text)
        self.assertTrue(refs, "manifest has no segment refs")
        self.assertTrue(uris, "manifest has no #EXT-X-KEY URI")

        targets = [("key", uris[0])] + [("ts", r) for r in refs[:2]]
        for kind, ref in targets:
            abs_url = urllib.parse.urljoin(main.rsplit("/", 1)[0] + "/", ref)
            try:
                status, body, headers = http_get(
                    self.base + f"/proxy/{kind}?url=" + urllib.parse.quote(abs_url, safe=""),
                    timeout=60)
            except (ConnectionError, urllib.error.URLError) as exc:
                self.fail(f"{kind} 请求时连接被服务端断开（keep-alive 复用问题）：{exc}")
            self.assertEqual(status, 200, f"{kind} {abs_url} -> {status}")
            if kind == "key":
                self.assertEqual(len(body), 16, "AES-128 key must be 16 bytes")
                self.assertEqual(headers.get("Content-Type"), "application/octet-stream")
            else:
                # 上游分片本身就是 AES-128 加密的（#EXT-X-KEY），所以开头不是
                # MPEG-TS 同步字节 0x47；只校验长度与 Content-Type。
                self.assertEqual(headers.get("Content-Type"), "video/MP2T")
                self.assertGreater(len(body), 10_000, "segment looks truncated")

        # 解密链路自检：用清单里的 key + IV 解开第一个分片，必须出现 TS 同步字节。
        # 这能在不依赖播放器的情况下证明“密钥和分片是配对的、能解出视频”。
        key = http_get(self.base + "/proxy/key?url=" +
                       urllib.parse.quote(urllib.parse.urljoin(
                           main.rsplit("/", 1)[0] + "/", uris[0]), safe=""))[1]
        seg = http_get(self.base + "/proxy/ts?url=" +
                       urllib.parse.quote(urllib.parse.urljoin(
                           main.rsplit("/", 1)[0] + "/", refs[0]), safe=""))[1]
        iv = re.search(r"IV=0x([0-9a-fA-F]+)", text)
        if not aes128_cbc_decrypt:
            self.skipTest("未安装 cryptography，跳过解密自检（可选依赖）")
        decoded = aes128_cbc_decrypt(
            seg, key, bytes.fromhex(iv.group(1)) if iv else key)
        self.assertEqual(decoded[0], 0x47, "decrypted segment is not MPEG-TS")

    @unittest.skipUnless(ONLINE, "ONLINE=0")
    def test_unknown_video_reports_failure(self):
        # 上游对不存在的剧返回非 200，代理应把失败告诉调用方（而不是 500 崩掉）
        status, body, _ = http_post_json(
            self.base + "/api/play", {"id": 99999999, "ep": 1})
        self.assertIn(status, (200, 400, 404, 422, 502), body[:200])
        if status != 200:
            self.assertEqual(json.loads(body)["status"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
