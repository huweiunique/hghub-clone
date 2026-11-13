# 本地扩展与补丁机制

## 为什么

`vps1986/hghub-clone` 是活跃的上游。我们 fork 后的本地需求（访问密钥、静态路由等）
如果直接改 `web/server.py` 正文，每次 `git merge upstream/main` 都要手工解冲突。

所以约定：**本地逻辑放 `local_ext/`，上游文件只留极小的钩子。**

上游文件只保留脚本引用、服务端钩子和受控续播接缝，业务逻辑维护在 `local_ext/`。

## 结构

```
local_ext/
  access_key.py     # 鉴权全部逻辑：key 校验、Cookie 签发、IP 白名单
  web_patch.js      # 前端鉴权与布局修正：行内图标、App 顶栏、看全集自适应
  app_settings.js   # iOS 随包注入：“我的 → 设置”的地址与密钥配置入口
  player_patch.js   # 复用原播放器：沉浸布局、手动横竖切换、续播与历史增强
  prefip_patch.js   # 优选设置与刷新反馈；iOS 原生连接桥
  preferred_ip.py   # 优选列表按运营商缓存与显式刷新
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

播放增强由补丁脚本在两个页面的 `</body>` 前引用 `player_patch.js`。
优选设置同样在 `</body>` 前引用 `prefip_patch.js`，服务端通过受鉴权保护的
`/api/prefip` 标记钩子进入本地扩展。iOS 连接能力和使用边界见 [CF 优选 IP](preferred-ip.md)。
上游原有系统全屏按钮、视频控件、选集、倍速、播放线路及自动下一集继续保留。
唯一的续播接缝是在上游旧续播判断前插入标记块：启用本地增强时跳过旧的固定延迟
seek，避免切集后被旧定时器拖回错误时间；没有增强脚本时仍执行原逻辑。

每个补丁都用注释标记包围，注释形式按文件类型自动选（`#` / `<!-- -->` / `/* */`）。

搜索栏贴住网页视口顶部，取消原有 `14px` 偏移，滚动时不再从搜索栏上方露出内容。
“看全集”播放状态下，视频区域占满网页视口，底部导航隐藏，已有返回与操作栏叠放在
画面上，播放时闲置三秒后隐藏，轻点或暂停可再次显示。画面以 `object-fit:contain`
保持原比例，比例不同会留黑边；保留视频原生控件和系统全屏入口。
“切换横屏”按钮将现有播放区域和操作一起旋转，再点切回；不监听设备方向自动切换。
返回详情时恢复竖屏、底栏和上游滚动布局。iOS 播放状态通过同源主框架消息控制状态栏
和安全区；这部分需新 IPA 配合，系统全屏及安全区效果仍需 iPhone 验收。相关样式使用 `:has()`，
适用于本项目 iOS 16+ 的 WebView 和支持该选择器的现代浏览器。

`python tests/test_player_layout.py` 用本机 Chrome/Edge 在六种视口尺寸下核验视频、
操作栏和导航的位置，并覆盖横竖视频、屏幕旋转、底栏高度变化与返回详情。
测试使用本地生成的视频流，无需上游；没有 Chrome/Edge 时明确跳过。

续播继续使用 `hg_progress`，保留旧进度，补存开头十秒、暂停、页面隐藏与退出时的位置。
新源就绪后才恢复并保存进度，详情切换和旧媒体暂停事件不能覆盖保存位置；一集结束先记
下一集开头，再复用原有自动下一集处理器，最后一集标记“已看完”。强制终止 App 仍不能
保证最后瞬间一定收到退出事件，进度保存在当前服务来源的本机网站数据中，不跨设备同步。
观看历史的位置和入口不变，增加集号、秒级进度和“查看详情”；点击未看完条目直接续播，
已看完条目打开详情，不自动重播。`test_player_behavior.py` 执行真实业务脚本及扩展，
以可控媒体加载与本地接口回执验证这些事件链路；不冒充真实上游或 iOS 系统播放器验收。

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
