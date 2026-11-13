# Docker 部署与发布（本地维护版说明）

> 这是 **fork 后本地维护版** 的补充说明。上游 README 讲的是「直接跑 python 脚本 + systemd」，
> 这里讲 **Docker 怎么编译、怎么运行，以及版本怎么发布**。

## 一、Docker 编译（构建镜像）

在仓库根目录执行。

### 方式 A：Docker Compose（推荐，一条命令）

```bash
docker compose up -d --build
```

Compose 会读取 `Dockerfile` 构建镜像 `hghub:1.2.0.8` 并启动容器。
`--build` 表示**每次启动前重新编译镜像**（改了代码后必须带这个参数）。

### 方式 B：手动 docker build

```bash
# 基础用法
docker build -t hghub:1.2.0.8 .

# 国内网络：Debian 软件源默认走阿里云；要改用官方源时
docker build --build-arg APT_MIRROR=deb.debian.org -t hghub:1.2.0.8 .

# 国内拉基础镜像慢时，可以换镜像仓库前缀
docker build -f Dockerfile --build-arg APT_MIRROR=mirrors.aliyun.com \
  -t hghub:1.2.0.8 .
```

构建约 2～5 分钟（主要时间在拉 `python:3.12-slim` 和装 openssl）。
构建成功后会看到镜像：

```bash
docker images hghub
# REPOSITORY   TAG       SIZE
# hghub        1.2.0.8   135MB
```

**镜像里包含什么**：`python:3.12-slim` + `openssl` + `ca-certificates` + `tini`，
以及 `proxy/`（8080 播放代理）、`web/`（8081 网页）、`local_ext/`（访问密钥）。
两个服务跑在同一个容器里，由 `docker/entrypoint.sh` 拉起。

> 为什么必须装 openssl：封面图是 AES 加密的，服务端用它解密。
> 没有 openssl 时封面会全部变成破图（这是真实踩过的坑）。

## 二、用编译好的镜像运行（docker run）

不需要源码，只要有镜像就能跑。

```bash
# 最简运行
docker run -d --name hghub \
  -p 8081:8081 \
  -p 8080:8080 \
  hghub:1.2.0.8

# 带访问密钥运行（推荐；密钥是任意字符串，见下方说明）
docker run -d --name hghub \
  -p 8081:8081 \
  -e HGHUB_ACCESS_KEY="my-home-server-2026" \
  --restart unless-stopped \
  hghub:1.2.0.8
```

然后浏览器打开 `http://<服务器IP>:8081/`。开了密钥时用
`http://<服务器IP>:8081/?key=<密钥>` 打开，或者首次打开在页面上输入一次。

`-p 8081:8081` 是网页（手机访问这个），`-p 8080:8080` 是播放代理（对外可以不映射，
只给 8081 内部用；映射出来方便排查）。

常用操作：

```bash
docker logs -f hghub          # 看日志（会显示是否开启了访问密钥）
docker restart hghub          # 重启
docker rm -f hghub            # 删除容器
docker exec hghub openssl version   # 确认解密依赖在
```

### 从镜像仓库或离线包运行

```bash
# 从其他机器导出/导入（没有仓库时）
docker save hghub:1.2.0.8 -o hghub-1.2.0.8.tar
docker load -i hghub-1.2.0.8.tar

# 如果推到了 Docker Hub
docker tag hghub:1.2.0.8 <你的用户名>/hghub:1.2.0.8
docker push <你的用户名>/hghub:1.2.0.8
docker run -d -p 8081:8081 <你的用户名>/hghub:1.2.0.8
```

## 三、用 Docker Compose 运行

```bash
# 1. 配置（可选）：复制环境变量模板
cp .env.example .env
#    编辑 .env，至少要设置 HGHUB_ACCESS_KEY

# 2. 启动（首次或改代码后用 --build）
docker compose up -d --build

# 3. 查看状态与日志
docker compose ps
docker compose logs -f

# 4. 停止 / 删除
docker compose down
```

`docker-compose.yml` 会读同一个目录下的 `.env`（`.env` 已在 `.gitignore` 里，不会进仓库）。
也可以不建 `.env`，直接用环境变量：

```bash
HGHUB_ACCESS_KEY="my-home-server-2026" docker compose up -d
```

可用环境变量：

| 变量 | 作用 | 示例 |
| --- | --- | --- |
| `HGHUB_ACCESS_KEY` | 访问密钥；留空 = 不鉴权（公开可访问） | `my-home-server-2026` |
| `HGHUB_ALLOW_IPS` | 只允许这些来源 IP（逗号分隔，和密钥同时生效） | `1.2.3.4,5.6.7.8` |
| `HGHUB_TRUST_PROXY` | 放在 Nginx/Cloudflare 后面时设为 `1`，用 `X-Forwarded-For` 取真实 IP | `1` |
| `HGHUB_COOKIE_SECURE` | HTTPS 部署时设为 `1`，让 Cookie 带 Secure | `1` |
| `WEB_PORT` / `PROXY_PORT` | 宿主机端口，默认 8081 / 8080 | `18081` |

> 端口被别人占了（比如本机已有服务用 8080），改在 `.env` 里：
> `WEB_PORT=18081`、`PROXY_PORT=18080`，然后 `docker compose up -d`。

## 四、关于访问密钥

**它就只是一段任意字符串**，没有格式要求：

- 长度不限，建议 16 位以上；
- 字母、数字、符号都可以，但不能有空格和换行。

下面这些都行，效果一样：

```bash
openssl rand -hex 32          # 3f2a9c8e...（64 位十六进制）—— 只是一种生成方式
openssl rand -base64 24       # xK9/2mP+...（注意可能有 = + /）
python -c "import secrets;print(secrets.token_urlsafe(32))"
pwsh -c "[guid]::NewGuid().ToString('N')"
my-home-server-2026           # 手打也完全可以
```

**客户端里不内置密钥**：APK / IPA 首次打开时自己输入，输入后保存在本机
（Android 存在 SharedPreferences，iOS 存在 UserDefaults，30 天 Cookie 免重复输入）。
这样即使安装包被转发出去，别人也不能直接用你的服务器。

> ⚠️ 安全边界：服务本身没有 HTTPS。公网直接 http 访问时，密钥在传输中可能被看到。
> 要真安全，请在前面挂一层 HTTPS 反向代理（Caddy / Nginx / Cloudflare Tunnel），
> 并打开 `HGHUB_COOKIE_SECURE=1`。

## 五、验证是否正常

```bash
curl -s http://127.0.0.1:8081/health
# {"status": "ok"}

curl -s http://127.0.0.1:8080/health
# {"status": "ok"}

# 播放链路（应返回 streams.main）
curl -s -X POST -H 'Content-Type: application/json' -d '{"id":12,"ep":1}' \
  http://127.0.0.1:8080/api/play | head -c 200
```

更完整的自动化测试（需要 Python，连真实上游）：

```bash
python tests/run_all.py --online --web http://127.0.0.1:8081 --proxy http://127.0.0.1:8080
```

## 六、版本与发布

| 通道 | 触发方式 | 版本号 | 产物 |
| --- | --- | --- | --- |
| **Nightly** | 每天 UTC 18:00 定时，或手动跑 `Nightly` 工作流 | `nightly`（每次覆盖） | APK + IPA，Release 标记为 Pre-release |
| **正式版** | **只有维护者手动打 tag** | `v1.2.0.8` 这种 | APK + IPA，正式 Release |

**没有打 tag 的构建一律是 Nightly**，不会占用正式版本号。
正式发版由维护者决定：

```bash
git tag -a v1.2.0.9 -m "1.2.0.9"
git push origin v1.2.0.9
```

每次发布（无论 Nightly 还是正式版）的 Release 说明里都会自动带上：

- 本次对应的提交号、来源分支、构建时间；
- **本次包含的提交清单**（正式版是「自上一个 tag 以来」的全部提交，Nightly 是最近 25 条）；
- **改动的文件统计**（`git diff --stat`）。

构建流程定义在 `.github/workflows/_build.yml`，`nightly.yml` 与 `release.yml` 都复用它。

可选：在仓库 Settings → Variables 里设置 `HGHUB_APP_URL`，构建时就会把它内置成后端地址
（密钥仍然不内置）。

## 七、发布镜像到 Docker Hub（CI 自动）

上面的 docker.md 讲的是本机构建。如果想让 GitHub Actions **自动构建并推送**镜像，
按下面两步配置，之后每次 Nightly / 正式发版都会顺带推镜像。

### 1. 在 Docker Hub 建 Access Token（不要用账号密码）

1. 登录 <https://hub.docker.com/> → 右上头像 → **Account settings**
2. 左侧 **Personal access tokens** → **Generate new token**
3. 权限选 **Read & Write**（只推送镜像不需要 Admin）
4. 复制生成的 token（`dckr_pat_...`，**只显示一次**）

> 用 Access Token 而不是密码：可以单独吊销，泄露影响面小，也不受二次验证影响。

### 2. 把仓库建出来（第一次需要）

Docker Hub 上先建一个名为 `hghub` 的仓库（或推第一次时自动创建，取决于账号设置）。
镜像名格式：`<用户名>/hghub`。

### 3. 在 GitHub 仓库加两个 Secret

```bash
# 在仓库根目录执行（已 gh auth login）
gh secret set DOCKERHUB_USERNAME   # 粘贴你的 Docker Hub 用户名
gh secret set DOCKERHUB_TOKEN      # 粘贴上一步的 dckr_pat_...
```

或者网页操作：仓库 → **Settings** → **Secrets and variables** → **Actions** →
**New repository secret**，分别建 `DOCKERHUB_USERNAME` 和 `DOCKERHUB_TOKEN`。

**安全要点**：

- token 只存在 GitHub Secrets 里，**不会**出现在代码、日志或 Release 里；
- 工作流里只在 `docker/login-action` 这一步使用，日志会打码；
- **不要**把 token 写进 `.env`、`docker-compose.yml` 或任何提交的文件；
- 定期轮换：Docker Hub 上删旧 token、生成新的、更新 Secret 即可，代码不用改；
- 仓库不要给别人 `Secrets: write` 权限，只给 `maintain` 及以下也不行。

### 4. 推送时机与标签

| 触发 | 推送的标签 | 说明 |
| --- | --- | --- |
| Nightly（每天定时/手动） | `nightly`、`nightly-<sha>` | **不会覆盖 `latest`** |
| 正式 tag（`v1.2.0.9`） | `v1.2.0.9`、`1.2.0.8`、`latest` | 只有正式发版才更新 `latest` |

- 多架构：同时构建 `linux/amd64` 和 `linux/arm64`（ARM 服务器 / Apple Silicon 可直接跑）；
- 构建缓存走 GitHub Actions 缓存（`type=gha`），第二次起快很多；
- **没配置这两个 Secret 时自动跳过**，不影响 APK/IPA 流水线。

### 5. 使用推送上去的镜像

```bash
# 拉取（Nightly）
docker pull <用户名>/hghub:nightly

# 运行
docker run -d --name hghub \
  -p 8081:8081 \
  -e HGHUB_ACCESS_KEY="my-home-server-2026" \
  --restart unless-stopped \
  <用户名>/hghub:nightly

# compose 里改用远程镜像（不用 build）
# services:
#   hghub:
#     image: <用户名>/hghub:nightly
#     ports: ["8081:8081"]
```

### 6. 手动推一次（本机）

CI 之外也可以自己推：

```bash
docker login -u <用户名>          # 密码处粘贴 Access Token
docker build -t <用户名>/hghub:1.2.0.8 .
docker push <用户名>/hghub:1.2.0.8
```

## 八、在 1Panel 里用「编排」部署

1Panel 自带的 **容器 → 编排（Compose）** 功能，本质就是帮你在服务器上管理一个
`docker-compose.yml`：你粘贴 YAML，它负责创建目录、执行 `docker compose up -d`、
展示状态和日志，还支持更新和查看文件。

### 8.1 面板里怎么建

1. 左侧菜单 → **容器** → **编排** → 右上角 **创建编排**
2. **名称**：填 `hghub`（会让你容器/项目以这个名字出现）
3. **分组**：随便选或新建，比如 `自用`
4. **来源**：选 **编辑** / **手动输入**（不是「从仓库拉取」）
5. 把下面 8.2 的 YAML 整段粘进去
6. 点 **确认** → 1Panel 会自动创建目录（通常是
   `/opt/1panel/docker/compose/hghub/`）并执行 `docker compose up -d`

> 不同版本 1Panel 的按钮文案略有差异（有的叫「编排模板」「Compose 编排」），
> 但都在 **容器** 菜单下，认准「粘贴 YAML 创建」这个入口即可。
> 如果最终看到「运行中」，说明是用 `docker compose` 起的。

### 8.2 直接粘贴的 YAML（用 Docker Hub 上的镜像）

```yaml
services:
  hghub:
    image: <你的DockerHub用户名>/hghub:nightly
    container_name: hghub
    restart: unless-stopped
    ports:
      - "8081:8081"
      - "8080:8080"
    environment:
      TZ: Asia/Shanghai
      # 访问密钥：任意字符串，留空则不鉴权
      HGHUB_ACCESS_KEY: "my-home-server-2026"
      HGHUB_ALLOW_IPS: ""
      HGHUB_TRUST_PROXY: ""
      HGHUB_COOKIE_SECURE: ""
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8081/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

> 注意：**1Panel 的编排 YAML 里不要写 `build:` 和 `version:`**。
> 1Panel 是在服务器上运行，没有你的源码，`build` 会因为找不到 `Dockerfile` 失败；
> `version:` 在新版 Docker Compose 里已废弃，写了会有警告。
> 镜像必须用 `image:` 指向 Docker Hub（或你自己的私有仓库）。

### 8.3 如果一定要「自己构建」（可选）

先把镜像构建好并推到 Docker Hub（见第七章），再用 8.2 的 `image:` 引用。
**不要**在 1Panel 里直接 `build` 本地源码 —— 它没有源码。

### 8.4 端口冲突怎么办

1Panel 所在服务器上 8080 很常被别的容器占用（1Panel 自己、OpenResty、其他面板应用）。
改映射的**左边**（宿主机端口）即可，右边不变：

```yaml
    ports:
      - "18081:8081"     # 浏览器访问 18081
      - "18080:8080"     # 播放代理，可不对外暴露
```

只想给网页用、不暴露代理端口时，可以只留：

```yaml
    ports:
      - "18081:8081"
```

（8081 内部会自动反代到容器里的 8080，不需要对外映射 8080。）

### 8.5 环境变量怎么改

**不要在面板里改 YAML 后忘了重启**。两种方式：

- **直接改 YAML**（推荐，改动可见）：
  编排列表 → 找到 `hghub` → **编辑** → 改 `environment:` → 保存 → **重建/重启**
- **用 1Panel 的 `.env`**（如果该版本支持）：
  在编排目录 `/opt/1panel/docker/compose/hghub/.env` 写：

  ```dotenv
  HGHUB_ACCESS_KEY=my-home-server-2026
  WEB_PORT=18081
  ```

  然后 YAML 里用 `${HGHUB_ACCESS_KEY}` 引用：

  ```yaml
  environment:
    HGHUB_ACCESS_KEY: ${HGHUB_ACCESS_KEY}
  ports:
    - "${WEB_PORT:-8081}:8081"
  ```

  `.env` 不会进 git，适合放密钥。

### 8.6 部署后怎么验证

- 1Panel 编排列表里状态显示 **运行中**；
- 点「日志」能看到：

  ```
  [hghub] 访问密钥已开启
  [hghub] 启动播放代理 :8080
  [hghub] 启动网页服务 :8081（反代 -> http://127.0.0.1:8080）
  ```

- 浏览器打开 `http://<服务器IP>:18081/?key=<你的密钥>`，能看到首页 feed 并播放。

服务器上也可以直接验证：

```bash
docker ps | grep hghub
curl -s http://127.0.0.1:18081/health        # {"status": "ok"}
curl -s -X POST -H 'Content-Type: application/json' -d '{"id":12,"ep":1}' \
  http://127.0.0.1:18080/api/play | head -c 120
```

### 8.7 更新到最新 Nightly

编排列表里点 **更新**（有些版本叫「重新拉取并重建」）：1Panel 会 `docker pull` 最新镜像并重建容器。
命令行等价操作：

```bash
docker compose -f /opt/1panel/docker/compose/hghub/docker-compose.yml pull
docker compose -f /opt/1panel/docker/compose/hghub/docker-compose.yml up -d
```

> `nightly` 标签每天覆盖，所以「更新」就能拿到当天构建。想固定版本就改成
> `<你的DockerHub用户名>/hghub:nightly-<sha>`，或者等正式版的 `latest`。

### 8.8 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 编排创建失败，提示找不到 Dockerfile | YAML 里写了 `build:` | 删掉 `build`，改用 `image:` |
| 提示 `port is already allocated` | 8080/8081 被占用 | 改映射左边端口（见 8.4） |
| 状态一直「重启中」 | 端口冲突或网络拉不到上游 | 看日志；确认服务器能访问 huangguoai.com |
| 页面能开但封面全破图 | 镜像缺 openssl（自己改过镜像） | 改用本仓库 `Dockerfile` 构建的镜像 |
| 一直弹「需要访问密钥」 | 输入的 key 与服务端不一致 | 核对 `docker exec hghub env \| grep HGHUB` |
| 改了 YAML 没生效 | 没重建容器 | 点「重启」或「重新部署」，不要只改文件 |

