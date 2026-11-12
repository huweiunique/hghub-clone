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
  web_patch.js      # 前端：未授权时弹输入框，输入正确后换 Cookie
tools/
  apply_local_patches.py   # 幂等补丁脚本（apply / --check / --revert）
```

## 补丁脚本做了什么

| 文件 | 补丁 | 位置 |
| --- | --- | --- |
| `web/server.py` | import + `LOCAL_EXT_DIR` 常量 | `from http.server ...` 之后 |
| `web/server.py` | `do_GET` 调 `pre_serve` | 解析完 path/qs 之后 |
| `web/server.py` | `do_POST` 调 `pre_serve` | 解析完 path 之后 |
| `web/server.py` | `_send` 写出额外头（Set-Cookie/Location） | 写完 CORS 头之后 |
| `web/server.py` | `/local_ext/<file>.js` 静态路由 | `if path == "/hls.min.js"` 之前 |
| `web/index.html` | 一行 `<script src="/local_ext/web_patch.js">` | `</head>` 之前 |
| `android/.../assets/hghub/index.html` | 同上 | `</head>` 之前 |

每个补丁都用注释标记包围，注释形式按文件类型自动选（`#` / `<!-- -->` / `/* */`）。

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
