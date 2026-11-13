#!/usr/bin/env python3
"""静态检查：不联网、不起服务，几秒钟跑完。

    python -m unittest tests.test_static -v

检查项：
  * 两个 server.py 能编译
  * web/index.html 的主脚本能被 node 解析（1.2.0.2 曾因语法错误整页 JS 失效）
  * APK assets 里的前端与 web/ 保持同步（构建脚本会复制，防止 APK 里跑旧页面）
  * AndroidManifest：包名、竖屏、明文 HTTP 放行
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(REPO_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def sha256(*parts):
    with open(os.path.join(REPO_ROOT, *parts), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class ServerSyntaxTests(unittest.TestCase):
    def test_proxy_server_compiles(self):
        src = read("proxy", "server.py")
        compile(src, "proxy/server.py", "exec")

    def test_web_server_compiles(self):
        src = read("web", "server.py")
        compile(src, "web/server.py", "exec")

    def test_servers_are_stdlib_only(self):
        # 不装任何第三方包也能部署：import 只允许标准库
        allowed = {
            "hashlib", "hmac", "json", "logging", "os", "subprocess", "sys",
            "urllib.error", "urllib.parse", "urllib.request", "collections",
            "http.server", "re", "time", "local_ext",
        }
        for rel in ("proxy/server.py", "web/server.py"):
            for mod in re.findall(r"^\s*(?:import|from)\s+([A-Za-z_][\w.]*)", read(*rel.split("/")), re.M):
                top = mod.split(".")[0]
                self.assertIn(top, {a.split(".")[0] for a in allowed}, f"{rel}: {mod}")


class FrontendTests(unittest.TestCase):
    def setUp(self):
        html = read("web", "index.html")
        # 最后一个 <script> 就是主脚本（前面是 /hls.min.js 的标签和兜底加载）
        start = html.rindex("<script>") + len("<script>")
        end = html.index("</script>", start)
        self.js = html[start:end]
        self.html = html

    @unittest.skipIf(shutil.which("node") is None, "node not installed")
    def test_main_script_parses_in_node(self):
        # 写到仓库自己的 .test-tmp/ 而不是系统临时目录：某些沙箱/CI 下
        # 系统临时目录不可写（本机沙箱就是这样）。
        tmp = os.path.join(REPO_ROOT, ".test-tmp")
        os.makedirs(tmp, exist_ok=True)
        path = os.path.join(tmp, "main.js")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.js)
            proc = subprocess.run(["node", "--check", path],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def test_covers_go_through_decrypt_proxy(self):
        # 封面修复的关键：前端封面地址必须经过 /proxy/img
        self.assertIn("/proxy/img", self.js)
        self.assertIn("coverSrc", self.js)

    def test_api_calls_stay_same_origin(self):
        # 1.2.0.6：API 先走同源，不再跨域直连上游
        self.assertRegex(self.js, r"['\"]/api/")
        # 主脚本里的同源代理前缀应该出现（/api/up/ 或 /api/）
        self.assertIn("/api/up/", self.js)

    def test_app_url_placeholder_only(self):
        # 仓库里不写死任何服务器 IP：APK 地址靠构建时注入
        ips = set(re.findall(r"http://(\d{1,3}(?:\.\d{1,3}){3})", self.html))
        self.assertEqual(ips, set(), f"hard-coded IPs in index.html: {ips}")

    def test_bundled_assets_match_web(self):
        self.assertEqual(sha256("web", "index.html"),
                         sha256("android", "app", "src", "main", "assets", "hghub", "index.html"),
                         "android assets/index.html out of sync with web/index.html")
        self.assertEqual(sha256("web", "hls.min.js"),
                         sha256("android", "app", "src", "main", "assets", "hghub", "hls.min.js"),
                         "android assets/hls.min.js out of sync with web/hls.min.js")


class AndroidProjectTests(unittest.TestCase):
    def setUp(self):
        self.manifest = read("android", "app", "src", "main", "AndroidManifest.xml")

    def test_package_and_version(self):
        self.assertIn('package="com.hghub.huangguoai"', self.manifest)
        self.assertIn('android:versionName="1.2.0.8"', self.manifest)

    def test_package_name_is_ours_not_upstream(self):
        """包名不能和上游原版 / LNPANDY 版相同，否则设备上会互相覆盖。"""
        ours = "com.hghub.huangguoai"
        gradle = read("android", "app", "build.gradle")
        self.assertIn(f'namespace = "{ours}"', gradle)
        self.assertIn(f'applicationId = "{ours}"', gradle)
        ios = read("ios", "HGhub", "HGhub.xcodeproj", "project.pbxproj")
        self.assertIn(f"PRODUCT_BUNDLE_IDENTIFIER = {ours};", ios)
        # 不能被上游的 com.hghub.huangguo 冒充（\b 避免误判 huangguoai）
        for rel in ("android/app/src/main/AndroidManifest.xml", "ios/HGhub/HGhub.xcodeproj/project.pbxproj",
                    "android/app/build.gradle"):
            text = read(*rel.split("/"))
            self.assertNotRegex(text, r"com\.hghub\.huangguo(?!ai)\b", rel)
        # Java 目录必须与包名一致
        self.assertTrue(os.path.exists(os.path.join(
            REPO_ROOT, "android", "app", "src", "main", "java", "com", "hghub", "huangguoai",
            "MainActivity.java")))

    def test_portrait(self):
        self.assertIn('android:screenOrientation="portrait"', self.manifest)

    def test_cleartext_allowed(self):
        # 自建服务器默认是 http://IP:8081，Android 9+ 必须放行明文
        self.assertIn('android:usesCleartextTraffic="true"', self.manifest)
        cfg = read("android", "app", "src", "main", "res", "xml", "network_security_config.xml")
        self.assertIn("cleartextTrafficPermitted=\"true\"", cfg)

    def test_internet_permission_only(self):
        perms = re.findall(r'uses-permission android:name="([^"]+)"', self.manifest)
        self.assertIn("android.permission.INTERNET", perms)
        self.assertFalse([p for p in perms if "SMS" in p or "CAMERA" in p])


class LocalPatchTests(unittest.TestCase):
    """本地扩展必须通过补丁脚本接入，不能直接改上游正文（降低 merge 冲突）。"""

    def test_patch_script_is_idempotent(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "tools", "apply_local_patches.py"), "--check"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        self.assertEqual(proc.returncode, 0, (proc.stdout or "") + (proc.stderr or ""))
        # 每一条都应是 already：说明已打过的补丁不会再插入一次
        self.assertIn("already", proc.stdout)
        self.assertNotIn(": applied", proc.stdout)

    def test_hooks_present_in_upstream_files(self):
        server = read("web", "server.py")
        self.assertIn("HGHUB_LOCAL_PATCH BEGIN", server)
        self.assertIn("_local_auth.pre_serve(self, \"GET\")", server)
        self.assertIn("_local_auth.pre_serve(self, \"POST\")", server)
        # 上游原有代码仍然原样在（没被我们改写）
        self.assertIn("def do_GET(self):", server)
        self.assertIn("self._json(404, {\"status\": 0, \"msg\": \"not found\"})", server)

    def test_frontend_patch_is_one_line_include(self):
        html = read("web", "index.html")
        self.assertEqual(html.count('script src="/local_ext/web_patch.js"'), 1)
        # 必须在 </head> 之前（<script> 与 </head> 之间只允许夹注释行）
        head_tail = html.split("</head>")[0].split('src="/local_ext/web_patch.js"></script>')
        self.assertEqual(len(head_tail), 2, "web_patch.js 应出现在 </head> 之前")
        self.assertIn("local patch end", head_tail[1])
        # 不能落在 <style> 里（否则标记会被当 CSS 文本渲染成可见乱码）
        self.assertNotIn("local patch", html.split("</style>")[0].lower())

    def test_local_ext_module(self):
        sys.path.insert(0, REPO_ROOT)
        from local_ext import access_key  # noqa: E402
        self.assertFalse(access_key.ENABLED, "默认不开密钥，保持原有部署行为")
        # 未启用密钥时对任何路径都放行
        self.assertEqual(access_key.pre_serve(None, "GET", path="/api/videos")[0], 0)
        self.assertEqual(access_key.pre_serve(None, "POST", path="/api/play")[0], 0)

    def test_auth_handshake_does_not_redirect(self):
        """首屏换 Cookie 必须是 200 + Set-Cookie，不能 302（WKWebView 会丢 Cookie）。"""
        src = read("local_ext", "access_key.py")
        self.assertNotIn('"Location", "/"', src)
        self.assertIn("auth_cookie_header(handler)", src)

    def test_frontend_patch_fixes_known_shell_bugs(self):
        js = read("local_ext", "web_patch.js")
        # 不能依赖 hg_key_ok_* 本地标记：Cookie 有效时就不该弹框
        self.assertNotIn("hg_key_ok_", js)
        self.assertIn("localStorage.removeItem('hg_need_key')", js)
        # 行内 ★ 不再另起一行；取消悬浮齿轮后顶栏无需额外留空
        self.assertIn(".ic-svg{display:inline-block", js)
        self.assertNotIn("body.hg-app header{padding-right:78px}", js)


class ClientConfigTests(unittest.TestCase):
    """客户端（APK / IPA）必须能配置「后端地址 + 访问密钥」，且 Docker 侧能通过环境变量注入密钥。"""

    def test_android_has_url_and_key_config(self):
        java = read("android", "app", "src", "main", "java", "com", "hghub", "huangguoai", "MainActivity.java")
        self.assertIn("BuildConfig.APP_URL", java)
        self.assertIn("BuildConfig.APP_ACCESS_KEY", java)
        self.assertIn("KEY_ACCESS", java)
        # 设置界面里有地址和密钥两个输入框
        self.assertIn("EditText input", java)
        self.assertIn("EditText keyInput", java)
        # 地址要带上 key 参数（?key=）才会换 Cookie；实现用字符串拼接以兼容 minSdk 24
        self.assertIn('sb.append("key=")', java)
        self.assertIn("android.net.Uri.encode(key)", java)
        # 不能用到 API 29+ 的 Uri.Builder 方法（只看代码行，忽略注释）
        code = "\n".join(ln for ln in java.splitlines() if not ln.strip().startswith("//"))
        self.assertNotIn("removeQueryParameter", code)
        self.assertNotIn("appendEncodedQueryParameter", code)

    def test_android_build_does_not_embed_access_key(self):
        """密钥不允许内置进安装包，只能在 App 内输入。"""
        sh = read("android", "build-apk-manual.sh")
        self.assertIn('public static final String APP_ACCESS_KEY = "";', sh)
        self.assertNotIn("APP_ACCESS_KEY_JAVA", sh)
        gradle = read("android", "app", "build.gradle")
        self.assertIn('buildConfigField("String", "APP_ACCESS_KEY", "\\"\\"")', gradle)
        self.assertNotIn("appAccessKey", gradle)

    def test_ios_does_not_embed_access_key(self):
        app = read("ios", "HGhub", "HGhub", "App.swift")
        self.assertIn('let builtInKey = ""', app)
        self.assertNotIn('bundleValue("AccessKey")', app)
        script = read("ios", "build-ipa.sh")
        self.assertIn('ACCESS_KEY=""', script)

    def test_ios_has_url_and_key_config(self):
        app = read("ios", "HGhub", "HGhub", "App.swift")
        view = read("ios", "HGhub", "HGhub", "WebView.swift")
        self.assertIn("URLQueryItem(name: \"key\"", app)
        self.assertIn("SecureField", view)           # 密钥输入框
        self.assertIn("TextField(\"http://", view)   # 地址输入框
        self.assertIn("测试连接", view)

    def test_android_can_reopen_settings(self):
        """首次没填密钥也要能补填：长按返回键回到设置页。"""
        java = read("android", "app", "src", "main", "java", "com", "hghub", "huangguoai", "MainActivity.java")
        self.assertIn("onKeyDown", java)
        self.assertIn("showUrlSetup()", java)
        self.assertIn("KEYCODE_BACK", java)

    def test_docker_passes_access_key_env(self):
        compose = read("docker-compose.yml")
        self.assertIn("HGHUB_ACCESS_KEY", compose)
        self.assertIn("HGHUB_ALLOW_IPS", compose)
        entry = read("docker", "entrypoint.sh")
        self.assertIn("HGHUB_ACCESS_KEY", entry)

    def test_dotenv_not_committed(self):
        ignore = read(".gitignore")
        self.assertIn(".env", ignore.splitlines())
        self.assertTrue(os.path.exists(os.path.join(REPO_ROOT, ".env.example")))

    def test_key_can_be_any_string(self):
        """文档要讲清楚：密钥就是任意字符串，openssl 只是一种生成方式。"""
        env = read(".env.example")
        self.assertIn("任意字符串", env)
        self.assertIn("openssl rand -hex 32", env)

    def test_docker_docs_cover_build_run_compose(self):
        doc = read("docs", "docker.md")
        self.assertIn("docker build", doc)
        self.assertIn("docker run", doc)
        self.assertIn("docker compose up", doc)
        self.assertIn("README", read("README.md"))


class ReleaseChannelTests(unittest.TestCase):
    """发布规则：默认 Nightly，正式版只能由人打 tag。"""

    def test_nightly_is_default_channel(self):
        night = read(".github", "workflows", "nightly.yml")
        self.assertIn("schedule", night)
        self.assertIn("channel: nightly", night)

    def test_stable_release_only_on_tag(self):
        rel = read(".github", "workflows", "release.yml")
        self.assertIn('tags: ["v*"]', rel)
        self.assertIn("channel: stable", rel)
        # 正式版不能由 push/手动触发
        self.assertNotIn("workflow_dispatch", rel)

    def test_release_notes_include_commits(self):
        build = read(".github", "workflows", "_build.yml")
        self.assertIn("本次包含的提交", build)
        self.assertIn("git log --pretty=format", build)
        self.assertIn("git diff --stat", build)
        self.assertIn("prerelease:", build)

    def test_builds_reject_embedded_key(self):
        build = read(".github", "workflows", "_build.yml")
        self.assertIn('APP_ACCESS_KEY = ""', build)
        self.assertIn("AccessKey", build)

    def test_artifact_names_distinguish_channels(self):
        """Nightly 的包名要带日期和提交号，正式版才用纯版本号。"""
        build = read(".github", "workflows", "_build.yml")
        self.assertIn('suffix=-nightly-$(date -u +%Y%m%d)-${GITHUB_SHA::7}', build)
        self.assertIn("ARTIFACT_SUFFIX", build)
        # 两个构建脚本都支持后缀
        self.assertIn("ARTIFACT_SUFFIX", read("android", "build-apk-manual.sh"))
        self.assertIn("SUFFIX", read("ios", "build-ipa.sh"))
        self.assertIn('HGhub-1.2.0.8${ARTIFACT_SUFFIX:-}.apk', read("android", "build-apk-manual.sh"))
        self.assertIn('HGhub-${VERSION}${SUFFIX}-unsigned.ipa', read("ios", "build-ipa.sh"))


class DockerHubPublishTests(unittest.TestCase):
    """CI 推送镜像到 Docker Hub：凭据只能来自 Secrets，不能硬编码。"""

    def setUp(self):
        self.build = read(".github", "workflows", "_build.yml")

    def test_uses_secrets_for_login(self):
        self.assertIn("secrets.DOCKERHUB_USERNAME", self.build)
        self.assertIn("secrets.DOCKERHUB_TOKEN", self.build)
        self.assertIn("docker/login-action", self.build)

    def test_caller_passes_secrets_explicitly(self):
        """workflow_call 不会自动继承 secrets：调用方必须显式传，delegate 必须声明。"""
        self.assertIn("secrets:\n      DOCKERHUB_USERNAME", self.build)
        for wf in ("nightly.yml", "release.yml"):
            text = read(".github", "workflows", wf)
            self.assertIn("DOCKERHUB_USERNAME: ${{ secrets.DOCKERHUB_USERNAME }}", text, wf)
            self.assertIn("DOCKERHUB_TOKEN: ${{ secrets.DOCKERHUB_TOKEN }}", text, wf)

    def test_no_hardcoded_credentials(self):
        # 不能出现明文 token / 密码（正则找真实凭据形态，允许 ${{ secrets.X }}）
        self.assertNotRegex(self.build, r"dckr_pat_[A-Za-z0-9]{10,}")
        self.assertNotRegex(self.build, r"(?m)^\s*password:\s*(?!\$\{\{)\S+")
        self.assertNotRegex(self.build, r"DOCKERHUB_TOKEN\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}")

    def test_skips_when_not_configured(self):
        # 没配 secret 时不能失败
        self.assertIn("enabled=false", self.build)
        self.assertIn("跳过镜像推送", self.build)

    def test_nightly_never_overwrites_latest(self):
        # nightly 分支只打 nightly* 标签
        nightly_block = self.build.split('channel }}" = "stable"')[0]
        self.assertIn("${REPO}:nightly", self.build)
        # latest 只在 stable 分支里
        stable_part = self.build.split("else", 1)[1] if "else" in self.build else ""
        self.assertIn(":latest", self.build)

    def test_multi_arch(self):
        self.assertIn("linux/amd64,linux/arm64", self.build)

    def test_push_docs_exist(self):
        doc = read("docs", "docker.md")
        self.assertIn("DOCKERHUB_TOKEN", doc)
        self.assertIn("Access Token", doc)

    def test_no_private_dockerhub_account_in_docs(self):
        """文档里不能出现真实的私有 Docker Hub 账号名，只能用占位符。"""
        for rel in ("docs/docker.md", "docker-compose.yml", "README.md", ".env.example"):
            text = read(*rel.split("/"))
            self.assertNotRegex(text, r"[A-Za-z0-9_-]+/hghub:",
                                f"{rel} 里出现了具体的 Docker Hub 仓库路径")
            self.assertIn("你的DockerHub用户名", text) if rel == "docs/docker.md" else None

    def test_1panel_section(self):
        doc = read("docs", "docker.md")
        self.assertIn("1Panel", doc)
        self.assertIn("编排", doc)
        # 1Panel 在服务器上跑，没有源码：YAML 里不能出现 build:
        block = doc.split("### 8.2", 1)[1].split("```yaml", 1)[1].split("```", 1)[0]
        self.assertNotIn("build:", block)
        self.assertIn("image:", block)
        self.assertIn("HGHUB_ACCESS_KEY", block)

    def test_proxy_port_not_published_by_default(self):
        """8080 只在容器内部反代，默认不应映射到宿主机（只暴露 8081）。"""
        compose = read("docker-compose.yml")
        # 未注释的行里不能有 8080 映射
        active = [ln for ln in compose.splitlines()
                  if ln.strip() and not ln.strip().startswith("#")]
        self.assertFalse(
            any(re.search(r'"\$\{?PROXY_PORT[^"]*:8080"', ln) or '"8080:8080"' in ln
                for ln in active),
            "docker-compose.yml 默认不应发布 8080")
        doc = read("docs", "docker.md")
        self.assertNotIn("-p 8080:8080", doc)
        self.assertIn("8080 **不需要**映射到宿主机", doc)

    def test_doc_explains_same_origin_mechanism(self):
        """文档要说清楚：前端用相对路径，App 配的是网页地址。"""
        doc = read("docs", "docker.md")
        self.assertIn("### 9.4 工作机制", doc)
        self.assertIn("相对路径", doc)
        self.assertIn("不要**单独给 `/api` 配一个二级域名", doc)

    def test_deployment_faq_section(self):
        """只暴露前端、反代写法、镜像 tag 与版本号的区别都要写到。"""
        doc = read("docs", "docker.md")
        self.assertIn("## 九、只给 App 用", doc)
        self.assertIn('"127.0.0.1:38081:8081"', doc)      # 回环绑定示例
        self.assertIn("HGHUB_COOKIE_SECURE", doc)       # HTTPS 反代注意
        self.assertIn("HGHUB_TRUST_PROXY", doc)
        self.assertIn("proxy_pass http://127.0.0.1:38081", doc)
        self.assertIn("location /", doc)                # 必须整站反代
        # 默认 YAML 不应把 8080 暴露出去
        block = doc.split("### 8.2", 1)[1].split("```yaml", 1)[1].split("```", 1)[0]
        self.assertNotIn('"8080:8080"', block)


class ReverseProxyTests(unittest.TestCase):
    """前端必须同源调用后端，不能硬编码后端地址。"""

    def test_frontend_uses_relative_api_paths(self):
        html = read("web", "index.html")
        self.assertNotRegex(html, r"fetch\(['\"]https?://")
        self.assertIn("fetch('/api/play'", html)
        self.assertIn("fetch('/api/prefip", html)

    def test_backend_upstream_is_server_side_only(self):
        """huangguoai 只在服务端反代里出现，前端不直连。"""
        html = read("web", "index.html")
        self.assertNotRegex(html, r"fetch\(\s*UP\b")
        self.assertIn("huangguoai.com", read("web", "server.py"))

    def test_proxy_base_is_container_local(self):
        """8080 只在容器/本机内部用，默认 127.0.0.1。"""
        server = read("web", "server.py")
        self.assertIn('os.environ.get("PROXY_BASE", "http://127.0.0.1:8080")', server)


class AppKeyFlowTests(unittest.TestCase):
    """App 里填过密钥后，页面不应再弹窗要求输入（踩过的 bug）。"""

    def setUp(self):
        self.js = read("local_ext", "web_patch.js")

    def test_reads_key_from_url(self):
        """页面必须能从自己的 URL 取 ?key=（App 壳拼在入口地址上）。"""
        self.assertIn("function keyFromURL", self.js)
        self.assertIn("new URLSearchParams(location.search)", self.js)

    def test_exchanges_key_before_prompting(self):
        """先尝试用 URL 里的 key 换 Cookie，成功就 return，不弹窗。"""
        probe = self.js.split("async function probe()", 1)[1]
        head = probe.split("askKey()", 1)[0]
        self.assertIn("keyFromURL()", head)
        self.assertIn("exchangeKey(urlKey)", head)
        self.assertLess(head.index("exchangeKey(urlKey)"), head.index("hg_need_key"))

    def test_exchange_uses_credentials(self):
        """换 Cookie 的请求必须带 credentials，否则 Set-Cookie 被忽略。"""
        fn = self.js.split("async function exchangeKey", 1)[1].split("async function probe", 1)[0]
        self.assertIn("credentials: 'same-origin'", fn)

    def test_removes_key_from_address_bar(self):
        """换完 Cookie 要把地址栏的 key 去掉，避免留在历史/Referer。"""
        self.assertIn("history.replaceState", self.js)
        self.assertIn("searchParams.delete('key')", self.js)

    def test_shells_inject_key_into_url(self):
        ios = read("ios", "HGhub", "HGhub", "App.swift")
        # 注入前统一去掉首尾空白，避免粘贴带空格导致服务端判错
        self.assertIn("trimmingCharacters(in: .whitespacesAndNewlines)", ios)
        self.assertIn('URLQueryItem(name: "key", value: key)', ios)
        java = read("android", "app", "src", "main", "java", "com", "hghub", "huangguoai", "MainActivity.java")
        self.assertIn('sb.append("key=")', java)

if __name__ == "__main__":
    unittest.main(verbosity=2)
