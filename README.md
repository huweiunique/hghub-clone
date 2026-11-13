# HGhub Clone — 黄果短剧第三方客户端复刻版

> ⚠️ **仅供学习与技术交流**，不提供、不存储、不分发任何音视频内容。
> 所有内容均来自第三方站点，请自行判断合规性，并在 24 小时内删除相关资源。
> 本项目与黄果短剧官方无关；原作者已删库停更。

> 📦 **本 fork 的 Docker 部署 / 发布说明见 [docs/docker.md](docs/docker.md)**
> （镜像怎么编译、`docker run`、`docker compose`、访问密钥、Nightly 与正式版规则）。

这是 [HGhub](https://github.com/Minireel/HGhub) 1.2.0（黄果短剧第三方客户端，
Tauri 2 + React，Fluent 设计）的**网页复刻版**：原作者删库后，按留存的
1.2.0 APK（包名 `com.hghub.huangguo`）复刻而成。

**小白也能跟着做**：下面每一步都是复制粘贴就能跑的命令，不用会写代码。
照着做完，你会得到一个能在手机上刷剧的网站 + 一个能安装的 APK。

---

## 一、做完之后你得到什么

```
手机浏览器 / APK
      │  只跟你的服务器说话（http://你的服务器IP:8081/）
      ▼
┌──────────────┐   反代    ┌──────────────┐   POST 空 JSON 取流   ┌──────────────────┐
│  网页 8081    │ ────────► │ 播放代理 8080 │ ────────────────────► │ huangguoai.com   │
│  web/server.py│           │ proxy/server.py│  代理清单/密钥/分片  │ 上游：列表/详情/ │
│  首页/分类/搜索│           │                │                     │ 播放/排行/帖子    │
│  榜单/帖子/播放│           │                │                     │ 封面图床：        │
│  封面解密代理 │           │                │                     │ pic.drleao.cn    │
└──────────────┘           └──────────────┘                     └──────────────────┘
```

| 东西 | 地址 | 说明 |
| --- | --- | --- |
| 复刻版网页 | `http://<服务器IP>:8081/` | 手机浏览器直接打开就能刷剧 |
| 播放代理 | `http://<服务器IP>:8080/` | 帮浏览器拿播放地址、代理清单/密钥/分片 |
| APK | `HGhub-1.2.0.3.apk`（自己构建） | 前端页面打进 APK，打开秒开，地址已内置，不用再输 |

## 二、需要准备什么

| 东西 | 说明 |
| --- | --- |
| 1 台境外服务器 | 能访问 `huangguoai.com` 的 Linux 服务器（Debian 12/13 最好）。本仓库示例用一台香港服务器部署，地址用 `YOUR_SERVER_IP` 占位——换成你自己的服务器 IP 即可。服务器上 **80 和 443 端口可能已有其他服务在用，本项目只用 8080 和 8081，绝不碰 80/443**。配置不用高：1 核、512MB 内存、10GB 磁盘就够 |
| 1 个 GitHub 账号 | 用来克隆本仓库、以后自己改代码、发 APK |
| 1 台电脑 | 用来构建 APK：装 JDK 17 + Android SDK（见第六节）。如果只想用网页版看剧，这一步可以跳过 |
| 1 部安卓手机 | 装 APK 用。iPhone 不能装 APK，只能用浏览器打开网页版 |

## 三、快速开始（5 步，复制粘贴就行）

### 第 1 步：登上服务器，拉取仓库

```bash
# 服务器是 Debian/Ubuntu，用 root 登录后：
apt update && apt install -y git python3 openssl curl
git clone https://github.com/vps1986/hghub-clone.git
cd hghub-clone
```

> 没有 `git`？先装：`apt install -y git`。Windows 电脑上先装
> [Git for Windows](https://git-scm.com/) 再用 Git Bash 跑同样命令。

### 第 2 步：部署播放代理（8080 端口）

```bash
bash scripts/deploy-proxy.sh
```

脚本会：把 `proxy/server.py` 装到 `/root/hghub-proxy/`，
写好 systemd 服务并开机自启，最后自动验证。
看到 `部署完成` 和 `/health` 返回 `{"status": "ok"}` 就是成功了。

手动验证（下面三条都应该是 200）：

```bash
curl http://127.0.0.1:8080/health
curl -s -X POST -H 'Content-Type: application/json' -d '{"id":12,"ep":1}' \
  http://127.0.0.1:8080/api/play | head -c 300
```

### 第 3 步：部署复刻版网页（8081 端口）

```bash
bash scripts/deploy-web.sh
```

脚本会先检查 8080 代理在不在，再把网页装到 `/root/hghub-web/`，
写好 systemd 服务并开机自启，最后自动验证首页和播放接口。

### 第 4 步：打开网页试试

手机浏览器打开：

```
http://<你的服务器IP>:8081/
```

看到首页竖屏刷剧、点一部剧能播出来，就是成功了。
如果点剧播不了，先看第七节的报错表。

### 第 5 步（可选）：构建 APK 装到手机上

见第六节。构建出来的 APK 默认打开的就是你服务器的 8081 网页，
装上直接刷，不用再输地址。

## 四、仓库里每个文件是干什么的

```
.
├── README.md                    # 你正在看的这份说明
├── proxy/
│   └── server.py                # 播放解析代理（8080 端口，Python 标准库）
├── web/
│   ├── index.html               # 复刻版网页本体（单文件：首页/分类/搜索/榜单/
│   │                            #   帖子/详情/登录/播放器，hls.js 播 HLS）
│   └── server.py                # 网页服务（8081 端口：静态页 + 反代 + 封面解密）
├── android/                     # Android WebView 壳工程（包名 com.hghub.huangguoai）
│   ├── build-apk-manual.sh      # 手动构建 APK 的脚本（不用 Gradle 也能编）
│   ├── build.gradle             # Gradle 构建配置
│   ├── settings.gradle
│   └── app/
│       ├── build.gradle
│       └── src/main/
│           ├── AndroidManifest.xml          # 竖屏、联网权限、允许明文 HTTP
│           ├── java/com/hghub/huangguo/MainActivity.java  # 全屏 WebView
│           └── res/
│               ├── drawable/ic_launcher.xml # 黄色 HG 图标
│               ├── values/strings.xml       # 应用名 HGhub
│               ├── values/styles.xml
│               └── xml/network_security_config.xml  # 允许明文访问你的服务器
└── scripts/
    ├── deploy-proxy.sh          # 一键部署 8080 播放代理
    └── deploy-web.sh            # 一键部署 8081 网页
```

**APK 二进制文件不进仓库**（`.gitignore` 已排除 `android/HGhub-1.2.0.apk*`），
每次都是在你自己电脑上构建出来的。

## 五、原理：为什么要这样搭（看懂了才好排错）

### 5.1 播放接口：POST 空 JSON `{}`

老接口已经失效：`GET /api/videos/:id/play` 返回的 `video_url` 是空的。

新版首播接口（2026-11-10 实测）：

```bash
curl -s -X POST -H 'Content-Type: application/json' -d '{}' \
  https://huangguoai.com/api/videos/12/episodes/1/playback
```

- URL 里带视频 id 和集数，**请求体必须是空 JSON `{}`**。
  带上 `id` / `ep` 等参数，上游会返回
  `{"status":0,"msg":"播放参数无效"}`。
- 成功返回 `data.streams.main`（HLS 清单地址）、`data.streams.hevc`、
  `data.cdn.authKey = "x-cdn-auth"`、`manifest_method = "GET"`。
- 清单是 AES-128 加密的，密钥 16 字节；清单、分片、密钥都能直连 200，
  但它们分散在两个 CDN 域名上：

| 资源 | 域名 |
| --- | --- |
| 清单 `.m3u8` | `yd-lphu-long.hzjvlo.cn` |
| AES 密钥 / `.ts` 分片 | `tp4.drleao.cn`（HEVC：`tp8.drleao.cn`） |

浏览器直连被挡就全断。所以复刻版用**服务器解析代理**：
服务端先 POST 取流地址，再把清单、密钥、分片代理成站内地址，
hls.js 只跟本站说话，前端不再直连 CDN。
签名过期自动换新地址重试一次，代理失败自动切直连。
iOS Safari 没有 MSE，走原生直连清单，代理帮不上它。

### 5.2 封面图：图床下发的是加密字节，必须解密

这是最容易踩的坑，也是本仓库重点修好的地方。

**现象**：网页能打开、列表标题都有，但所有封面图片都是空白/破图。

**根因（2026-11-10 实测）**：上游图床 `pic.drleao.cn` 下发的封面
**不是 JPEG**，而是一串 AES 加密字节：

- 文件熵 7.999 bit/字节，全文件找不到任何 JPEG/PNG/WebP 文件头；
- `Content-Type` 是 `binary/octet-stream`；
- 不带 Referer 也能拉到同样的 200 —— 跟防盗链、Referer、CDN 封禁都没关系，
  拉到的是密文，浏览器当然显示不出来。

上游自己的解密协议是公开的
（`https://huangguoai.com/static/web/js/plugins/crypto-image-protocol.js`）：

```
AES-128-CBC，无填充（NoPadding）
decryptKey = "f5d965df75336270"   # 16 个 ASCII 字符 = 16 字节密钥
decryptIV  = "97b60394abc2fbe1"   # 16 个 ASCII 字符 = 16 字节 IV
```

本地验证（拿一张封面解密，得到合法 JPEG）：

```bash
COVER="https://pic.drleao.cn/upload_01/upload/20260924/2026092411162272798.jpg?auth_key=..."
curl -s "$COVER" -o cover.enc
openssl enc -d -aes-128-cbc -nopad \
  -K "$(printf 'f5d965df75336270' | od -An -tx1 | tr -d ' \n')" \
  -iv "$(printf '97b60394abc2fbe1' | od -An -tx1 | tr -d ' \n')" \
  -in cover.enc -out cover.jpg
file cover.jpg   # JPEG image data
```

**本仓库的修复**（两处配合，缺一不可）：

1. `web/server.py` 的 `GET /proxy/img?url=...`：服务端先拉取封面字节，
   再用系统 `openssl` 解密成正常 JPEG 返回（带 200 张内存缓存，
   只放行 `pic.drleao.cn` 等图床域名，防滥用）。
2. `web/index.html` 的 `coverSrc()` / `coverImg()`：所有封面
   （首页信息流、分类卡片、榜单、观看历史）一律走 `/proxy/img?url=...`，
   代理失败时 `onerror` 再换回直连地址试一次。

> 注意：这个密钥/IV 是上游**公开给浏览器**的前端协议参数，
> 写死在仓库里是安全的；它本来就是人人都能在上游网页源码里看到的。

### 5.3 两个服务怎么分工

| 服务 | 端口 | 文件 | 干什么 |
| --- | --- | --- | --- |
| 播放代理 | 8080 | `proxy/server.py` | `POST /api/play` 取流；`GET /proxy/m3u8\|key\|ts?url=` 代理清单/密钥/分片；`GET /proxy?url=` 是统一入口别名 |
| 网页 | 8081 | `web/server.py` + `web/index.html` | 提供网页；同源反代 `/api/play`、`/proxy/*` 到 8080，`/api/up/*`、`/api/edge/*` 到上游；`/proxy/img` 解密封面 |

浏览器（手机）只访问 8081，8081 再去找 8080 和上游。
这样前端不用处理跨域，也不用直连被挡的 CDN。

## 六、构建 APK（装到手机上）

### 准备：JDK 17 + Android SDK

```bash
# 以 Ubuntu/Debian 为例（Windows 用 Android Studio 更方便，见下）
sudo apt install -y openjdk-17-jdk unzip curl
mkdir -p ~/android-sdk/cmdline-tools
cd ~/android-sdk/cmdline-tools
curl -o tools.zip https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
unzip tools.zip && mv cmdline-tools latest
export ANDROID_HOME=~/android-sdk
export PATH=$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH
sdkmanager "platforms;android-34" "build-tools;34.0.0" "platform-tools"
```

Windows / macOS：装 [Android Studio](https://developer.android.com/studio)，
它自带 JDK 和 SDK，装好后把 `ANDROID_HOME` 指到它的 SDK 目录即可。

### 方法 A：Gradle（推荐，有 Android Studio 时最顺）

```bash
cd android
export ANDROID_HOME=<你的 SDK 目录>   # 例：~/android-sdk
./gradlew assembleDebug
# 产物：app/build/outputs/apk/debug/app-debug.apk
```

### 方法 B：手动脚本（Gradle daemon 在沙箱/云主机里起不来时用）

```bash
cd android
export JAVA_HOME=<JDK 17 目录> ANDROID_HOME=<SDK 目录>
bash build-apk-manual.sh
# 产物：HGhub-1.2.0.3.apk（debug 签名）
```

手动脚本用的是 `aapt2 compile/link + javac + d8 + zipalign + apksigner`，
不依赖 Gradle。构建中踩过的坑（都已写进脚本）：
`/tmp` 是小 tmpfs 会满盘、Gradle daemon IPC 在沙箱里连不上、
javac 需要 `-encoding UTF-8`。

### 安装

手机上允许“安装未知来源应用”后，直接安装 APK。
应用只要联网权限，没有其他敏感权限。

### 改 APK 打开的地址

APK 打开的地址在构建时注入，仓库里不写死任何服务器 IP。
构建时把 `APP_URL` 换成你自己的服务器地址：

```bash
APP_URL="http://YOUR_SERVER_IP:8081/" bash android/build-apk-manual.sh
# 不传 APP_URL 则默认值为空，首次打开时在应用内输入一次（保存在本地）
```

Gradle 构建时用 `-PappUrl=http://YOUR_SERVER_IP:8081/`，
或改 `android/app/build.gradle` 里 `APP_URL` 的默认值（默认空）。

## 七、常见报错表

| 报错 / 现象 | 原因 | 修法 |
| --- | --- | --- |
| `net::ERR_CLEARTEXT_NOT_PERMITTED` | Android 9+ 默认禁止明文 HTTP，APK 没开开关 | 本仓库已修：`AndroidManifest.xml` 里 `android:usesCleartextTraffic="true"` + `res/xml/network_security_config.xml` 对服务器域名放行明文。重新构建 APK 再装 |
| `net::ERR_CONNECTION_REFUSED` | 8081 网页服务没起来 | 服务器上 `systemctl status hghub-web`，再看日志 `journalctl -u hghub-web -f`；确认 8080 代理先起来了，再 `systemctl restart hghub-web` |
| `播放参数无效` | 播放请求体里带了 `id`/`ep` 参数 | 播放接口请求体必须是空 JSON `{}`，id/ep 只放在 URL 里（见 5.1）。`proxy/server.py` 已按这个实现 |
| 首页能打开，点剧播不了 | 8080 代理没起来，或上游播放地址签名过期 | 先 `curl http://127.0.0.1:8080/health`；再按第三节第 2 步测 `POST /api/play`；播放器会自动换新地址重试一次 |
| 封面全是空白/破图 | 图床下发的是 AES 加密字节，直接当图片加载显示不出来 | 本仓库已修：封面走 `web/server.py` 的 `/proxy/img` 解密。确认你部署的是本仓库最新版 `web/`，且服务器上有 `openssl` 命令（`openssl version` 能打出版本号） |
| `gh: not logged into any GitHub hosts` | 本机没登录 GitHub，推不上去 | 云浏览器里打开 `github.com` 登录一次，再跑 `gh auth login`，然后 `git push`（见第八节） |
| `upstream HTTP 403`（代理拉清单/密钥时） | 上游播放地址的 `auth_key` 签名过期了 | 正常现象：重新调一次 `POST /api/play` 拿新地址再播。不要拿几个小时前的旧地址去试 |

## 八、换成你自己的服务器（部署地址怎么改）

只改 3 个地方，其他不用动：

1. **网页和代理**：在你自己的服务器上跑第三节的部署脚本，
   8080/8081 端口照用，域名/IP 不用写进代码（两个服务都用相对地址和
   `127.0.0.1` 互相调用）。
2. **APK 打开的地址**：构建时传
   `APP_URL=http://YOUR_SERVER_IP:8081/ bash android/build-apk-manual.sh`
   （或 Gradle `-PappUrl=http://YOUR_SERVER_IP:8081/`），重新构建。
   不要把 IP 写进代码里提交。
3. **占位符**：本仓库所有地址都用 `YOUR_SERVER_IP` 占位
   （例如 `http://YOUR_SERVER_IP:8081/`），不要把你自己的服务器 IP
   也公开写进仓库——构建 APK 时再用环境变量注入（见第六节）。

> 如果你的服务器 8080/8081 端口被运营商/防火墙挡了，改端口也行：
> `PORT=18080 bash scripts/deploy-proxy.sh`，
> `PORT=18081 PROXY_BASE=http://127.0.0.1:18080 bash scripts/deploy-web.sh`，
> APK 里的 `APP_URL` 也改成新端口。注意：80 和 443 别动，
> 它们通常已有其他服务（比如 Xray、MTProto）在用。

## 九、已验证 / 未验证（说实话）

**已验证（2026-11-10，本地 + 线上实测）**：

- 播放代理：`GET /health` 200；`POST /api/play {id:12, ep:1}` 200，
  返回 `streams.main/hevc/preview`；`/proxy/m3u8` 拉清单 6894 字节
  `application/vnd.apple.mpegurl`；`/proxy/key` 拉密钥 16 字节；
  `/proxy` 统一入口同样可用
- 网页服务：`/` 200；`/api/play` 反代 200；`/api/up/videos` 反代 200，
  返回真实上游列表；`/proxy/img` 对真实封面返回 `image/jpeg`，
  解密后是合法 JPEG（`FFD8FFE0` 开头，174816 字节）；非图床域名返回 403
- 封面解密：`openssl` 用公开协议参数解密线上封面，得到合法 JPEG
- APK：`apksigner verify` 通过；包名 `com.hghub.huangguoai`、版本 1.2.0.3、
  minSdk 24、targetSdk 34、竖屏、入口 `MainActivity`；
  manifest 里确认 `usesCleartextTraffic=true`；
  dex 里确认内置地址是你构建时注入的 `APP_URL`
  （示例 `http://YOUR_SERVER_IP:8081/`）

**未验证 / 已知限制**：

- 本机没有安卓模拟器/真机，**APK 没有做过真机安装和打开测试**；
  播放效果以手机实测为准
- 线上 8081 的封面修复（`/proxy/img`）是本仓库新加的，
  服务器上正在跑的旧版 8081 还没有这个接口——部署新版后才生效
  （跑 `bash scripts/deploy-web.sh` 重新部署即可）
- iOS Safari 没有 MSE，走原生直连清单，代理帮不上它
- 上游接口随时可能改版（播放参数、加密协议、域名），
  哪天播不了了，先按第七节的表排查，再去上游网页源码里
  对照 `crypto-image-protocol.js` / `edge-api-crypto.js` 看看参数变了没有

## 十、免责

本项目与黄果短剧官方无关；原作者已删库停更，本复刻仅用于学习交流。
请勿将本项目用于商业用途；使用第三方内容请遵守当地法律法规。

## 十一、1.2.0.2 更新（跟原版更接近）

- **沉浸式 feed**：首页全屏，顶栏/页脚隐藏；滚轮、触摸上下滑切集；双击点赞（带爱心动画）。
- **预加载**：滑到哪集就预加载那集和下一集的播放链接 + 清单，点下一集直接起播；播着当前集时也在后台预加载下一集。
- **封面本地缓存**：Cache API（`hg-covers-v1`）存解密后的封面，第二次打开不走网络。
- **续播**：每 5 秒存一次进度，打开看到一半的剧自动跳回上次位置。
- **线路**：默认直连 CDN 起播（最快），失败自动换 8080 代理再试；也可以在「我的 → 设置」里手动切换。
- **APK 不再是空壳**：`web/index.html` + `hls.min.js` 打进 APK 的 `assets/hghub/`，打开先加载本地页面，列表/播放再联网拉。构建脚本每次构建都会从 `web/` 同步最新前端。
- **顺带修了一个旧 bug**：仓库里的 `web/index.html` 主 JS 曾有语法错误（`coverImg` 调用被包进了字符串里），整段脚本在浏览器里解析失败；1.2.0.2 已修掉，`node --check` 通过。
- **hls.js 本地化**：`web/hls.min.js` 随仓库走，`web/server.py` 新增 `/hls.min.js` 路由，不再依赖 jsdelivr CDN（CDN 只作兜底）。

原版仍做不到的：原生 Tauri 渲染/手势跟手度、离线缓存整集视频、原生播放器硬解、账号体系走上游登录（复刻版登录只存在本机）。

## 十二、1.2.0.3 更新（内容不全修复：全部内容 + 自动更新）

根因：首页以前只拉第一页（`/api/feed/today` 只有 23 条，`/api/videos` 第一页只有 20 条），没有翻页，滑一会就到底。

- **上游分页（2026-11-11 实测）**：`/api/videos?page=N`，每页 20 条，`limit` 参数无效；全部 3361 部 / 169 页。分类参数是 `cate_id`（不是 `category_id`，后者会被忽略返回全量）：24 AI成人短剧 1518 部/76 页，25 AI成人漫剧 113 部/6 页，26 AI换脸 832 部/42 页，27 AI魔改 898 部/45 页。搜索正确接口是 `/api/search?q=`（分页）；帖子 `/api/posts` 749 条/38 页。
- **无限滚动**：首页 feed 滑到底自动加载下一页，直到全部 3361 部加载完，底部显示“已加载全部”；分类、搜索、帖子同样到底自动加载下一页；顶部显示“全部 X 部 · 已加载 Y 部”。
- **自动更新**：打开时比对首页第一页的 ID 和总数，有新剧/新集就弹出“有 N 部新更新，点击查看”；每 10 分钟后台静默刷新第一页，只提示不打断浏览；单剧详情每次打开都重新拉集数，不用缓存的旧集数。
- **后端**：`/api/up/*` 本来就把查询串（`?page=` / `cate_id=` / `q=`）原样透传给上游，不截断，1.2.0.3 只在注释里写明了这一点。

仍做不到的：榜单上游只返回前 20 名，`page` 参数无效，无法翻页（已在页面上注明）；上游列表本身没有按更新时间排序的字段，新剧发现靠“第一页出现的新 ID + 总数变化”比对，极少数情况下可能漏报；一次性拉完全部 169 页会很慢，所以是滑到底才加载下一页，不是打开就全拉下来。

## 十三、1.2.0.4 更新（抖音式播放 + 底部导航 + 分享/评论 + 滑不动修复）

**滑不动的根因（2026-11-11 查到两个）**：
- 以前 `api()` 先直连上游 `huangguoai.com`，手机网络下直连经常挂起几十秒不返回，而 `loading` 标志一直占着，下一页永远加载不出来。现在先走本站同源代理 `/api/up/`（服务器在香港，直连上游稳定），失败再试直连，每次尝试 15 秒超时。
- 以前用 JS 劫持 `wheel`/`touch` 事件强制一屏一屏跳，会和 CSS `scroll-snap` 打架，滑到一半卡住。现在用原生滚动 + `scroll-snap`，JS 只做节流后的状态同步。
- 兜底：无限滚动双重触发（滚动位置判断 + 底部哨兵 `IntersectionObserver`）；加载失败 3 秒后自动重试，再失败在列表底部放可点击的重试条；`loading` 标志一定在 `finally` 里复位；新 slide 追加后重新挂 observer；重复绑定用 `dataset.bound` 防重。

**布局**：取消全屏沉浸式。顶栏只留 logo + 搜索框，底部固定导航栏（首页/分类/榜单/帖子/我的，图标 + 文字，当前页高亮），顶栏和底栏始终保留，播放（详情弹窗打开）时也不隐藏。feed 卡片不占满屏：上下留白、卡片之间有间距、圆角 20px + 阴影。

**抖音式播放**：滑到哪集自动播放那集（静音起播，WebView 已开 `setMediaPlaybackRequiresUserGesture(false)`；点一下画面后开声音），滑走暂停上一集；点画面暂停/继续，中央短暂闪一下 ❚❚/▶ 图标；侧边和画面上的大 ▶ 播放按钮已去掉；右侧操作栏保留点赞（带真实数字）、评论、收藏、分享；底部有进度条（可点进度条快进）；播完自动滑到下一集；切换用 `transform`/`opacity` 过渡，`scroll-behavior: smooth` + 惯性滚动（`-webkit-overflow-scrolling: touch`），前后卡片预渲染（封面前 3 张 eager + 预加载下一集播放链接）。

**封面黑屏修复**：三级兜底（`/proxy/img` 解密图 → 直连原地址 → 占位图），画面永远不会全黑；封面缓存只换上校验过文件头（JPEG `FFD8FF` / PNG）的真图片；视频未播时用 `poster` 显示封面。

**分享**：点分享弹出面板：复制链接、微信、QQ、系统分享、下载 App。分享链接格式 `https://hg.45678.eu.org/?v=<视频id>&ep=<集数>`，别人点开直接打开对应剧集开始播（打开时解析 URL 参数自动定位）。下载 App 地址写在 `web/index.html` 的 `APK_RELEASE_URL` 常量里，发新版时只改这一处。

**评论**：点评论图标弹出评论面板，拉上游真实接口 `GET /api/videos/:id/comments`（2026-11-11 实测返回评论列表），没有就显示本地评论；可以发评论（先调上游 `POST /api/up/videos/:id/comments`，上游不接受就只存本地）。

**点赞/收藏**：显示上游返回的真实 `like_count`/`collect_count`，点赞/收藏后数字 +1，状态本地保存。

仍做不到的：榜单上游只返回前 20 名无法翻页；原生 Tauri 渲染/手势跟手度、离线缓存整集视频、原生播放器硬解、上游账号体系仍做不到；自动播放默认静音（浏览器限制），要点一下画面才有声音。

## 十三、1.2.0.5 更新

- **搜索/底部导航点了没反应修好了**：实测找到一个真 bug——热门标签接口返回 `{word, heat}`，旧代码只读 `name/keyword/tag`，热门词 chip 渲染成空白，点了等于没点；已改成读 `word` 字段并过滤空词。底部导航、搜索按钮、分类/榜单 chip 加了内联 `onclick` + 文档级捕获委托双重兜底，搜不到明确显示“没有找到相关短剧”，搜索失败给“点击重试”。
- **优选 IP**：自动列表来自 cf.090227.xyz（电信、联通、移动）。新 iOS App 在 iOS 17+ 将自动列表与多条自定义 IPv4/IPv6 合并去重，从手机各测两次后端 HTTPS 耗时，选择成功且平均耗时最低的 IP，显示逐项结果与进度，支持停止；全部失败回退普通连接。不支持的系统直接隐藏优选设置。Android 保留原有优选连接；普通浏览器仍使用系统连接。原域名及系统证书校验不变，只影响接入 Cloudflare 的 HTTPS 后端域名，不测试视频 CDN 下载速度。详见 [CF 优选 IP](docs/preferred-ip.md)。
- **hg 域名回退**：App 默认地址改成 `https://hg.45678.eu.org/`，如果域名还没通（隧道未跑起来报 530），自动回退到构建时注入的直连地址。
- **详情页（网页先行）**：点封面/标题先进详情页，不直接播。详情页有封面大图、标题、文案介绍（可展开/收起）、作者/分类/更新状态（已完结/连载中）/总集数/评分、点赞/收藏/评论数、标签（点标签直接搜）；选集按 30 集分段（1-30、31-60……），点哪集播哪集，当前集高亮、看过的集打勾；点“立即播放”或封面进播放页，播完自动下一集。

## 十四、1.2.0.6 更新（控制中心位置修复 + 抖音布局 + 同源 API）

- **控制中心位置修好了**：顶栏以前是 `sticky`，在竖屏 feed（内部滚动容器）和 WebView 里会被滚走，改成 `fixed` 永远贴在顶部；首页 feed 上顶栏是黑渐变盖在视频上（抖音式），其他页是实底色。底部导航 `fixed bottom` + `z-index 90` 加固，高于播放弹窗（z-60）和评论/分享面板（z-80），播放时、详情页里都始终贴在底部可见，不会被盖住、不会跑到顶部、不会随滚动消失。顶栏/底栏高度用 `--topbar-h` / `--bottomnav-h` 统一，feed、弹窗、面板的留白都按它算；评论输入框的底部留白也按底栏高度算，不再被底栏盖住。
- **同页点底部导航没反应修好了**：以前 `showView` 同页直接 return，详情/播放弹窗开着时点底部导航什么都不发生，看起来像控制中心坏了；现在同页先关弹窗再回顶部。
- **抖音式全屏 feed**：卡片占满顶栏与底栏之间的整块区域，无留白、无圆角、卡片之间无缝；首页的提示行删掉。右侧竖排操作栏：点赞（带真实数字）、评论、收藏、分享；点视频暂停/继续（中央只短暂闪一下 ❚❚/▶，不留播放按键）；底部进度条（可点快进）；上下滑动切视频；双击点赞；播完自动下一集。详情页抖音风格：顶部“‹ 返回”（弹窗打开时顶栏隐藏、背后滚动锁定）、封面（点封面直接播，中间的大 ▶ 播放键已去掉）、文案、选集。
- **同源 API 修好了**：`web/server.py` 之前只有 `/api/up/*` 路由，直接调 `/api/videos`、`/api/search` 等会 404，前端 `api()` 的兜底又是跨域直连上游，手机网络下经常挂起/CORS 挡住。现在 server.py 加了通用 `/api/*` 同源反代（GET 和 POST，`/api/play`、`/api/prefip` 优先匹配不受影响），前端 `api()` 先走同源直接 `/api/*`、再走同源 `/api/up/*`，不再跨域直连上游。

## 十五、1.2.0.7 更新（feed 简介+看全集、底部导航真修、详情页对齐预览）

- **feed 卡片终于看得见标题和简介了**：根因是 `video.bgvid` 是 `z-index:1`，没有 z-index 的 `.shade/.info/.acts` 会被播起来的视频盖住——标题、简介、右侧点赞栏全藏在视频下面，只有 `z-4` 的静音键看得见，和用户截图 1 一模一样。现在 `.shade` z-2、`.info`/`.acts` z-3，全部抬到视频上面。feed 卡片直接显示标题 + 一行简介（点简介展开完整文案）+ 黄色“看全集”按钮；点标题区/“看全集”进详情页，点视频空白处暂停/继续，双击点赞，不再冲突。
- **底部导航点了没反应真修好了**：根因是 `#view-home{display:flex}`（ID 选择器）优先级高于 `section[hidden]{display:none}`，首页 section 设了 `hidden` 也藏不住——点“分类”只换了导航高亮，首页还盖在上面，看起来像没反应。现在加了全局 `[hidden]{display:none !important}` 兜底（弹窗/面板的 hidden 也一样）；切页时先停掉 feed 正在播的视频。
- **详情页对齐预览图**：评分做成黄色徽章（9.5 分）、“看全集”改成黄色大按钮（续看显示“续看第 N 集”）、封面右下角加右侧操作栏（点赞/评论/收藏/分享，带真实数字），和预览图 2 的元素一一对应。封面 `onerror` 改在 `src` 之前挂上（以前先设 src、失败太快会漏掉，直接黑屏），失败走三级兜底（解密图 → 直连 → 占位图），封面容器本身也有渐变底，加载中/失败都不是纯黑。

## 十六、1.2.0.8 更新（整体下移、去掉点赞图标、图标缩小、删帖子、logo 回首页）

- **整体下移**：新增 `--page-shift:14px`，顶栏 `top:14px` 不再贴着屏幕顶边，`main` 上边距和 feed 高度同步扣掉这 14px，整个页面内容往下移。
- **点赞图标移除**：feed 右侧栏、详情右侧栏、详情页和播放页的“♥ 点赞”按钮全部去掉；feed 简介行、卡片、榜单、帖子、详情统计里的 `♥ 点赞数` 文字计数也一并去掉。双击点赞手势保留（双击仍点赞并弹出爱心动画），点赞数据仍存在本地。
- **其他图标同比例缩小**：右侧栏按钮 52→44px、详情右侧栏 48→41px、底部导航图标 21→18px、logo 24→21px、静音/分享/关闭图标同步缩小约 15%，保持协调。
- **底部导航删掉“帖子”**：只剩 首页/分类/榜单/我的 4 项，均匀分布。帖子页面代码保留（上游接口仍在），只是导航入口删掉。
- **顶部 logo 可点击回首页**：点 HGhub logo 停掉当前视频、关掉详情/播放弹窗和评论/分享面板，回到首页 feed 顶部。
