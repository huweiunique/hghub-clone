# 本地扩展与补丁机制

## 为什么

`vps1986/hghub-clone` 是活跃的上游。我们 fork 后的本地需求（访问密钥、静态路由等）
如果直接改 `web/server.py` 正文，每次 `git merge upstream/main` 都要手工解冲突。

所以约定：**本地逻辑放 `local_ext/`，上游文件只留极小的钩子。**

当前上游文件上的改动：**4 个锚点、约 45 行**（原来是 203 行分散改动）。

## 结构

```
local_ext/
  access_key.py     # 鉴权全部逻辑：key 校验、Cookie 签发、IP 白名单
  web_patch.js      # 前端鉴权与布局修正：行内图标、App 顶栏、看全集自适应
tools/
  apply_local_patches.py   # 幂等补丁脚本（apply / --check / --revert）
```

## 补丁脚本做了什么

| 文件 | 补丁 | 位置 |
| --- | --- | --- |
| `web/server.py` | import + `LOCAL_EXT_DIR` 常量 | `from http.server ...` 之后 |
| `web/server.py` | `do_GET` 调 `pre_serve` | 解析完 path/qs 之后 |
| `web/server.py` | `do_POST` 调 `pre_serve` | 解析完 path 之后 |
| `web/server.py` | `_send` 写出额外头（Set-Cookie） | 写完 CORS 头之后 |
| `web/server.py` | `/local_ext/<file>.js` 静态路由 | `if path == "/hls.min.js"` 之前 |
| `web/index.html` | 一行 `<script src="/local_ext/web_patch.js">` | `</head>` 之前 |
| `android/.../assets/hghub/index.html` | 同上 | `</head>` 之前 |

每个补丁都用注释标记包围，注释形式按文件类型自动选（`#` / `<!-- -->` / `/* */`）。

“看全集”播放状态下，视频区域占满返回按钮、操作栏和底部导航之外的可用空间，
取消上游的 `900px` 宽度与 `62vh` 高度限制。画面以 `object-fit:contain` 保持原比例，
比例不同会留黑边；操作按钮随宽度自动换行，底部导航的实际高度（含安全区）由
`ResizeObserver` 跟踪。返回详情后恢复上游滚动布局。相关样式使用 `:has()`，
适用于本项目 iOS 16+ 的 WebView 和支持该选择器的现代浏览器。

`python tests/test_player_layout.py` 用本机 Chrome/Edge 在六种视口尺寸下核验视频、
操作栏和导航的位置，并覆盖横竖视频、屏幕旋转、底栏高度变化与返回详情。
测试使用本地生成的视频流，无需上游；没有 Chrome/Edge 时明确跳过。

页面共同使用底部导航的实际高度，避免首页、详情和弹层在安全区较高时被遮挡。
小屏搜索栏允许收缩，榜单及卡片的长文本可换行，按钮内 SVG 统一限制尺寸。
密钥输入框在横屏或可用高度较小时可滚动。布局回归还覆盖首页、分类、榜单、
动态、个人页、搜索、详情、评论、分享以及密钥弹窗；固定的海报预览宽度和
普通列表内容最大宽度继续保留，作为阅读布局约束。

## 日常操作

```bash
python tools/apply_local_patches.py --check   # 期望：全部 already，0 个文件会改
python tools/apply_local_patches.py           # 应用（幂等）
python tools/apply_local_patches.py --revert  # 回到纯上游代码（排查上游 bug 用）
```

## 上游合并后怎么办

```bash
git fetch upstream && git merge upstream/main
python tools/apply_local_patches.py --check
```

- 输出全 `already` → 什么都没变，继续。
- 报「找不到锚点」→ 上游改了那段代码。打开脚本，把 `patch(...)` 的锚点换成上游新代码里
  同等位置的一行（通常是 `def do_GET` 后第一行、`</head>` 这类稳定结构），重跑即可。

**选锚点的原则**：挑协议层/结构层的东西（函数定义、`</head>`、`send_header(...)`），
不要挑业务字符串（例如某个接口 URL、某条提示文案），那些最容易被上游改。

## Docker 里的保护

镜像构建时会检查：`web/server.py` 有补丁标记、`index.html` 引用了 `web_patch.js`、
`local_ext.access_key` 能 import。缺任何一项直接构建失败 —— 避免出现「代码更新了但补丁没打」
却照样上线的镜像。
