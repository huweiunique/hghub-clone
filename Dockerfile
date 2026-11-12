# HGhub 后端镜像：8080 播放代理 + 8081 网页服务
#
# 两个服务都是纯标准库 Python，外加系统 openssl（封面解密必需）。
# 镜像里故意保留 openssl 和 ca-certificates：
#   - 没有 openssl 时 /proxy/img 会把密文当图片返回（封面全破图，本机踩过）
#   - 没有 CA 证书时无法访问 https://huangguoai.com
#
# Debian 软件源默认用阿里云镜像：国内直连 deb.debian.org 会 502。
# 需要官方源时：docker build --build-arg APT_MIRROR=deb.debian.org .
ARG APT_MIRROR=mirrors.aliyun.com
FROM python:3.12-slim

ARG APT_MIRROR
LABEL org.opencontainers.image.title="hghub" \
      org.opencontainers.image.description="HGhub clone: web (8081) + playback proxy (8080)" \
      org.opencontainers.image.source="https://github.com/huweiunique/hghub-clone"

# trixie 起源文件在 /etc/apt/sources.list.d/debian.sources（deb822 格式）
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" \
        /etc/apt/sources.list; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends openssl ca-certificates curl tini; \
    rm -rf /var/lib/apt/lists/*; \
    openssl version

WORKDIR /app

# 代码体积很小，一次复制即可；.dockerignore 已排除 .git 等无关文件
COPY proxy/ /app/proxy/
COPY web/ /app/web/
COPY local_ext/ /app/local_ext/
COPY docker/ /app/docker/
COPY tests/ /app/tests/
COPY tools/ /app/tools/
COPY Dockerfile docker-compose.yml README.md /app/

# 构建期自检：上游文件必须已打好本地补丁（见 tools/apply_local_patches.py），
# 否则鉴权入口不会被调用。缺补丁时在这里就把构建打失败，而不是上线后才发现。
RUN set -eux; \
    grep -q "HGHUB_LOCAL_PATCH BEGIN" /app/web/server.py; \
    grep -q "/local_ext/web_patch.js" /app/web/index.html; \
    python3 -c "import sys; sys.path.insert(0,'/app'); from local_ext import access_key; print('access_key ok, enabled=', access_key.ENABLED)"; \
    chmod +x /app/docker/entrypoint.sh

ENV HOST=0.0.0.0 \
    PROXY_PORT=8080 \
    WEB_PORT=8081 \
    PROXY_BASE=http://127.0.0.1:8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080 8081

# 健康检查只打 8081（/health 免鉴权，即使开了访问密钥也能探活）
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8081/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker/entrypoint.sh"]
