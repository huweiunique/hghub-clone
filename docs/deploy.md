# Docker 部署

## 一句话

```bash
docker compose up -d --build
# 访问 http://<服务器IP>:8081/
```

## 镜像里有什么

- `python:3.12-slim` + `openssl` + `ca-certificates` + `tini`
- 一个容器里跑两个服务：8080 播放代理 + 8081 网页（`docker/entrypoint.sh` 拉起，tini 接管信号）
- 任一服务退出，容器整体退出，交给 `restart: unless-stopped` 重启

为什么必须要 `openssl`：封面解密是 `subprocess` 调 `openssl enc`。**没有它，`/proxy/img`
会把密文当图片返回，页面封面全破图**（本机 Windows 上就是这么复现的）。
基础镜像里加了这个依赖，并带 `ca-certificates` 才能访问 `https://huangguoai.com`。

## 构建

```bash
# 默认走阿里云 apt 源（国内直连 deb.debian.org 会 502）
docker build -t hghub:1.2.0.8 .

# 境外构建用官方源
docker build --build-arg APT_MIRROR=deb.debian.org -t hghub:1.2.0.8 .
```

构建期会自检本地补丁是否已打（见 `docs/local-changes.md`），缺补丁直接失败。

## 运行

```bash
docker run -d --name hghub -p 8081:8081 -p 8080:8080 hghub:1.2.0.8

# 开访问密钥（推荐公网部署）
KEY=$(openssl rand -hex 32)
docker run -d --name hghub -p 8081:8081 \
  -e HGHUB_ACCESS_KEY="$KEY" hghub:1.2.0.8
echo "http://<IP>:8081/?key=$KEY"
```

`docker-compose.yml` 里改 `environment:` 即可；端口冲突用 `WEB_PORT`/`PROXY_PORT` 覆盖。

## 验证

```bash
# 容器内自检
docker exec hghub openssl version
docker exec hghub curl -fsS localhost:8081/health

# 从宿主跑全套功能测试（含播放/封面解密）
docker run --rm -v "$PWD":/src -w /src --network host python:3.12-slim \
  python tests/run_all.py --online --web http://127.0.0.1:8081 --proxy http://127.0.0.1:8080
# Windows 直接用宿主 python：
python tests/run_all.py --online --web http://127.0.0.1:18081 --proxy http://127.0.0.1:18080
```

`--web` 会给测试设 `REQUIRE_DECRYPT=1`，封面没解密就直接失败，不会静默跳过。

## 排错

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 构建卡在 `apt-get update` 502 | 国内访问 deb.debian.org 被挡 | 用默认的阿里云镜像源，或换别的 `APT_MIRROR` |
| 封面全破图 | 镜像缺 openssl（自己改过镜像？） | `docker exec hghub openssl version` 必须能打出版本 |
| 页面一直"加载中" | 上游接口慢（3–8 秒是常态），或容器出网受限 | `docker logs hghub` 看是否有 `upstream HTTP` 错误 |
| `播放参数无效` | 请求体带了 `id`/`ep` | 路由已按空 `{}` 实现，别改 |
| 8080 302/401 | 开了访问密钥 | 用 `/?key=` 打开，或带上 Cookie |

## 发布到 Docker Hub？

目前**只支持本地构建**：本机 `~/.docker/config.json` 里只有阿里云 registry 凭据，
没有 Docker Hub 账号。要发布需先 `docker login -u <user>`，然后：

```bash
docker tag hghub:1.2.0.8 <user>/hghub:1.2.0.8
docker push <user>/hghub:1.2.0.8
```

也可以在 GitHub Actions 里用 `docker/login-action` + secrets 自动发布（未配置）。

## 访问密钥怎么传（环境变量）

密钥**只从环境变量进入容器**，不写进镜像、不进 git：

```bash
# 方式一：临时
HGHUB_ACCESS_KEY=$(openssl rand -hex 32) docker compose up -d

# 方式二：写进 .env（推荐，.env 已在 .gitignore 里）
cp .env.example .env
# 编辑 .env 填写 HGHUB_ACCESS_KEY=...
docker compose up -d
```

可用的环境变量：

| 变量 | 作用 |
| --- | --- |
| `HGHUB_ACCESS_KEY` | 访问密钥；留空 = 关闭鉴权 |
| `HGHUB_ALLOW_IPS` | 来源 IP 白名单（逗号分隔，与密钥同时生效） |
| `HGHUB_TRUST_PROXY` | `1` = 信任 `X-Forwarded-For`（放在反代后面时） |
| `HGHUB_COOKIE_SECURE` | `1` = Cookie 带 Secure（HTTPS） |
| `WEB_PORT` / `PROXY_PORT` | 宿主机映射端口 |

启动后 `docker logs hghub` 会打印是否开启了鉴权，以及访问链接格式（不会打印密钥本身）。
