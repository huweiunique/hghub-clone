# 踩坑清单

改代码前先扫一眼，别再踩一遍。

## 后端 / 服务

| 坑 | 现象 | 真相 |
| --- | --- | --- |
| **本机没有 openssl** | 封面全是破图，但 `/proxy/img` 返回 200 `image/jpeg` | 解密失败后原样返回密文，还被写进 200 张内存缓存。Windows 默认没 openssl —— 用 Git 自带的 `C:\Program Files\Git\usr\bin\openssl.exe` 加进 PATH，或直接用容器 |
| **缓存污染** | 修好 openssl 后，之前看过的封面还是坏的 | 密文已进 LRU 缓存。重启服务（或加一个清缓存入口） |
| 代理没转发 `x-cdn-auth` | 上游开始校验 CDN 鉴权头时播放直接断 | `/proxy/*` 只透传 URL，`data.cdn.authValue` 丢了。当前 CDN 不校验，属于潜伏问题，测试 `test_cdn_auth_header_is_forwarded` 守着 |
| HEAD 请求 501 | 某些探活/CDN 探测失败 | 服务只实现了 `do_GET`/`do_POST`，不是我们引入的 |
| 清单 key/ts 域名会变 | 逐字节比对清单会偶发失败 | 上游在 `tp3/tp4/tp6/tp7.drleao.cn` 之间轮换，只能比结构不能比内容 |
| **服务端侧 key 全挂在 URL 上没用** | 首集能播、后面分片全 401 | hls.js 不会把页面的 `?key=` 带到分片请求，必须换 Cookie（见 `docs/access-key.md`） |

## 前端

| 坑 | 现象 | 真相 |
| --- | --- | --- |
| **补丁注释插进 `<style>`** | 页面顶部出现 `/* ==== HGHUB_LOCAL_PATCH BEGIN` 裸文本 | `<script>` 锚点必须放在 `</head>` 前，不能插在 `<style>` 里 |
| 封面 `onerror` 三级兜底 | 偶发整屏占位图 | 解密失败 → 直连原图 → 占位图。排查时先看 `/proxy/img` 返回的真实字节头 |
| 页面"加载中"很久 | 以为挂了 | 上游单次 3–8 秒；榜单/分类要十几秒 |
| 分类页切换后空白 | 以为 view id 写错 | 实际是 `showView('cat')`，不是 `'category'`；切页名是 `home/cat/rank/posts/me/search` |

## 测试 / 工具

| 坑 | 现象 | 真相 |
| --- | --- | --- |
| `tempfile.TemporaryDirectory` | Windows 沙箱下 PermissionError | 写到仓库内 `.test-tmp/` |
| 系统临时目录 / 管道 | Git Bash `bash -n` 直接 fatal | MSYS 创建命名管道被拒；用 Python/文档自检替代 |
| 上游偶发断连 | 单个用例 ERROR | `http_get` 已内置一次重试；仍失败多为上游抖动 |
| Linux 无头浏览器的输入能力与开发机不同 | 桌面导航测试返回 `desktop=False`，曾阻塞后续 Docker 构建 | 关闭触屏模拟会恢复宿主输入能力，启动参数不能保证恢复后仍有鼠标。默认后端测试不启动浏览器；UI 自动测试用 `python tests/run_all.py --ui` 显式启用，原断言保留。UI 改动仍须实际运行页面验证，见 [测试说明](testing.md) |
| 补丁脚本 `--revert` 用跨行贪婪正则 | **整个文件被删** | 已改成逐行扫描；`BEGIN` 无 `END` 会直接拒绝执行 |

## iOS 构建（GitHub Actions macOS）

| 坑 | 现象 | 真相 |
| --- | --- | --- |
| `macos-14` 已退役（2026-11-02） | 任务 2 秒被 cancel、无日志 | 用 `macos-latest` / `macos-15` |
| macOS runner 排队后被取消 | 排队 ~15 分钟后 `duration_ms: 0`、`runner_name: null` | GitHub 侧容量问题，重跑即可，与工作流无关 |
| `CODE_SIGNING_ALLOWED=NO` + `archive` | `BUILD SUCCEEDED` 但**没有 `.xcarchive`** | 无签名时不走 archive 流程；改 `xcodebuild build` 后自己组装 `Payload/` |
| iOS 26.5 SDK 拒绝 ad-hoc 签名 | `Ad Hoc code signing is not allowed with SDK 'iOS 26.5'` | 别用 `CODE_SIGN_IDENTITY="-"`，直接无签名 |
| `xcodebuild ... \| tee \| tail` | 构建失败却继续往下跑 | 管道退出码来自 `tail`，改重定向 + 显式判错 |
| AppIcon 只有 `Contents.json` | IPA 里没有 `Assets.car`，装上是白图标 | actool 无图片就不生成资源包；补 1024 png，脚本断言 `Assets.car` |
| `NavigationStack` | `only available in iOS 16.0 or newer` | 部署目标提到 16 |

## 进程管理

- `pkill python` 会误杀无关 Python（向量数据库等）。按端口杀：
  `Get-NetTCPConnection -LocalPort 8081 | % { Stop-Process -Id $_.OwningProcess -Force }`
- 容器里两个进程由 `entrypoint.sh` 管，不要在容器里单独重启某一个。
