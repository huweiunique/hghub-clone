#!/usr/bin/env bash
# 容器入口：同一个容器里起两个服务（8080 代理 + 8081 网页）。
# 任何一个退出或收到信号，整个容器退出（tini 负责转发 SIGTERM）。
set -euo pipefail

PROXY_PORT="${PROXY_PORT:-8080}"
WEB_PORT="${WEB_PORT:-8081}"
PROXY_BASE="${PROXY_BASE:-http://127.0.0.1:${PROXY_PORT}}"

if ! command -v openssl >/dev/null; then
  echo "[hghub] 警告：没有 openssl，/proxy/img 封面无法解密（会返回密文）" >&2
fi

# 访问密钥（可选）：HGHUB_ACCESS_KEY 非空即开启；密钥会下发到前端一起打包，
# 这样 APK / IPA 打开就能直接用，不用手输。
if [ -n "${HGHUB_ACCESS_KEY:-}" ]; then
  key_file=/app/local_ext/access_key.json
  # 只用于本机首次打开：把当前 key 写进运行时可读的 json（不含密钥本身，
  # 只含"是否开启"标记，避免把密钥暴露给任何未授权请求）
  printf '{"enabled":true}' > "$key_file"
  echo "[hghub] 访问密钥已开启${HGHUB_ALLOW_IPS:+（IP 白名单: $HGHUB_ALLOW_IPS）}"
  echo "[hghub] 浏览器地址：http://<你的地址>/?key=<HGHUB_ACCESS_KEY>"
  echo "[hghub] 打 APK/IPA 时把同一把 key 注入前端即可免输入（见 docs/local-changes.md）"
else
  echo "[hghub] 未设置 HGHUB_ACCESS_KEY：服务公开可访问（建议仅内网/临时使用）"
fi

echo "[hghub] 启动播放代理 :${PROXY_PORT}"
PORT="$PROXY_PORT" python3 /app/proxy/server.py &
PROXY_PID=$!

# 等代理就绪，再起网页（网页启动时会反代到它）
for _ in $(seq 1 50); do
  if python3 -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:${PROXY_PORT}/health', timeout=1)" 2>/dev/null; then
    break
  fi
  sleep 0.2
done

echo "[hghub] 启动网页服务 :${WEB_PORT}（反代 -> ${PROXY_BASE}）"
PORT="$WEB_PORT" PROXY_BASE="$PROXY_BASE" python3 /app/web/server.py &
WEB_PID=$!

trap 'kill -TERM "$PROXY_PID" "$WEB_PID" 2>/dev/null || true' TERM INT

# 任一进程退出就整体退出，交给 compose 的 restart 策略
wait -n "$PROXY_PID" "$WEB_PID"
echo "[hghub] 有服务退出，容器结束" >&2
kill -TERM "$PROXY_PID" "$WEB_PID" 2>/dev/null || true
exit 1
