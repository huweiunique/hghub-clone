# AGENTS.md

HGhub 第三方短剧客户端的复刻版（上游：[vps1986/hghub-clone](https://github.com/vps1986/hghub-clone)，fork 后由本仓库维护）。
结构：`proxy/`(8080 播放解析代理) + `web/`(8081 网页，同源反代) + `android/`(WebView 壳) + `ios/`(WKWebView 壳，待建)
+ `local_ext/`(本地扩展：访问密钥) + `tools/`(补丁/截图) + `tests/`(功能测试) + `Dockerfile`/`docker-compose.yml`。

## 最重要的一条：不要直接改上游文件

上游还在更新。**改 `web/server.py`、`web/index.html`、`android/app/src/main/assets/hghub/index.html` 的正文会被 merge 冲突淹没。**

- 新逻辑写进 `local_ext/`，再由 `python tools/apply_local_patches.py` 以「锚点 + 标记块」方式插入（当前共 4 个锚点、45 行）。
- 改了 `local_ext/` 后重跑补丁脚本；`--check` 应输出全部 `already`。
- 上游大改导致锚点找不到时，脚本会报错并指出哪个锚点，去更新锚点而不是放弃补丁。
- 新增文件（Dockerfile、tests、docs……）不受影响，随便加。

详见 [docs/local-changes.md](docs/local-changes.md)。

## 常用命令

```bash
# 本地跑（无 Docker）
python proxy/server.py            # 8080
PORT=8081 PROXY_BASE=http://127.0.0.1:8080 python web/server.py

# 测试（离线）
python tests/run_all.py
# 测试（连真实上游，验证播放/封面/列表）
python tests/run_all.py --online
# 测试已经跑着的服务（容器/远程）
python tests/run_all.py --online --web http://127.0.0.1:8081 --proxy http://127.0.0.1:8080

# Docker
docker compose up -d --build
docker build --build-arg APT_MIRROR=deb.debian.org -t hghub:1.2.0.8 .   # 官方源（境外）
```

## 环境事实（不要假设）

| 事实 | 说明 |
| --- | --- |
| 两个服务都是纯 Python 标准库 | 不要引入 pip 依赖；测试里 `test_servers_are_stdlib_only` 会拦 |
| 封面解密依赖系统 `openssl` 命令 | Windows 默认没有 → 封面全是密文。容器镜像已装 |
| 上游接口慢 | 单次 3–8 秒是常态；UI 卡在"加载中"多半只是还没回来，不是 bug |
| 上游偶发 403/断连 | 清单签名过期或 CDN 轮换，测试会 skip 并注明，不要当成代码回归 |
| `id=12/ep=1` 是固定样本 | README 一直用它，测试默认也用它（可 `HGHUB_SAMPLE_ID` 覆盖） |
| 仓库里不写死服务器 IP | APK/IPA 地址靠构建时注入（`APP_URL`/`appUrl`） |

## 访问密钥（可选，默认关闭）

`HGHUB_ACCESS_KEY` 非空才启用；`HGHUB_ALLOW_IPS` 可加 IP 白名单。
首页/`hls.min.js`/`local_ext/*`/`health` 免鉴权，其余接口凭 `?key=` 或登录后的 HttpOnly Cookie。
设计理由和踩过的坑见 [docs/access-key.md](docs/access-key.md)。

## 发布

- **后端**：Docker 镜像（`hghub:<version>`），见 [docs/deploy.md](docs/deploy.md)。
- **Release 工作流**（`.github/workflows/release.yml`）：一个 run 出 APK（ubuntu）+ 未签名 IPA（macOS），都进同一个 Release。
- 打 tag（`v1.2.0.8`）即触发，也可以手动 `workflow_dispatch`。
- 详细流程与已知限制：[docs/release.md](docs/release.md)。

## 提交前自检

```bash
python tools/apply_local_patches.py --check   # 补丁状态一致
python tests/run_all.py                       # 离线用例全绿
```

## 文档索引

- [docs/local-changes.md](docs/local-changes.md) — 本地扩展、补丁机制、冲突处理
- [docs/access-key.md](docs/access-key.md) — 鉴权设计、Cookie 流、安全边界
- [docs/deploy.md](docs/deploy.md) — Docker 构建/运行/排错
- [docs/release.md](docs/release.md) — APK / IPA 构建与发版
- [docs/pitfalls.md](docs/pitfalls.md) — 踩过的坑清单（改代码前先看）
