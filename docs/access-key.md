# 访问密钥（可选鉴权）

## 为什么不是「URL 上加一个长 key 就完了」

最初的想法：`http://ip:8081/?key=<长串>`，带 key 才能用。直接实现会踩三个坑：

1. **首页必须免鉴权**。否则浏览器打开 `/` 就被 401，用户没有任何入口把 key 送进来。
2. **HLS 播放器不带你 URL 里的参数**。hls.js 请求 `/proxy/ts?url=...` 时不会自动附带
   页面的 `?key=`，第一集能起播、后续分片全 401。
3. **key 留在地址栏有泄露面**：浏览器历史、分享链接、Referer（分享面板会把当前 URL 发出去）。

## 实际实现

```
GET /?key=xxx  ── 校验通过 ──▶ 200 首页 + Set-Cookie: hghub_auth=<HMAC>（不 302）
                                     │  页面脚本再 fetch 一次换 Cookie，
                                     │  成功后 history.replaceState 去掉地址栏 key
                                     ▼
                    之后所有 /api/*、/proxy/* 凭 Cookie 放行
```

> **为什么不用 302**：WKWebView（iOS App 壳）跟随 302 时经常丢弃响应里的
> `Set-Cookie`，而 302 又把 `?key=` 清掉了 —— 结果是 App 里每次启动都重复
> 弹输入框。现在首页直接 200 带 Cookie，`?key=` 保留到页面脚本处理完为止。

- Cookie 值是 `HMAC-SHA256(KEY, "hghub-access-v1")`，**不是明文 key**：
  即使 Cookie 被截获，也拿不到可以重新签发的密钥；换 key 后旧 Cookie 立即失效。
- `HttpOnly` + `SameSite=Lax` + 30 天；`X-Forwarded-Proto: https` 或 `HGHUB_COOKIE_SECURE=1` 时加 `Secure`。
- key 用 `hmac.compare_digest` 比较（防时序侧信道）。
- 前端 `local_ext/web_patch.js`：探测到 401 就弹输入框，输入正确后走 `/?key=` 换 Cookie 再刷新。
  带 `?key=` 的链接打开则完全无感。

## 配置

| 环境变量 | 作用 |
| --- | --- |
| `HGHUB_ACCESS_KEY` | 非空即启用；`openssl rand -hex 32` 生成 |
| `HGHUB_ALLOW_IPS` | 可选，逗号分隔；**与 key 同时生效**（两个都对才放行） |
| `HGHUB_TRUST_PROXY=1` | 放在 Nginx/CF 后面时，用 `X-Forwarded-For` 取真实 IP。默认**不信任**该头（否则可伪造绕过白名单） |
| `HGHUB_COOKIE_SECURE=1` | HTTPS 部署时强制 Cookie 带 Secure |

## 免鉴权路径

`/`、`/index.html`、`/hls.min.js`、`/health`、`/local_ext/*`

- `/health` 只回 `{"status":"ok"}`，给 Docker HEALTHCHECK 和负载均衡探活用。
- `/local_ext/*` 是页面自己的脚本，不放行的话开了密钥后前端连密钥框都加载不出来（踩过）。

## 安全边界（说实话）

- 这是**单用户自用**级别的保护：一把共享 key，没有用户体系、没有审计、没有限流。
- 服务端没有 TLS。公网直接用 http 时，key 和 Cookie 在传输中**可被中间人看到**。
  要真安全请在前面挂 HTTPS 反代（Caddy/Nginx/Cloudflare Tunnel）。
- 有了 key 的人等于有了这个代理的使用权（包括访问上游和代理 CDN）。不要公开分享。
- 关闭方式：不设 `HGHUB_ACCESS_KEY` 即可，行为与上游完全一致（测试 `test_disabled_key_keeps_old_behaviour` 守着这点）。

## 相关代码

- 逻辑：`local_ext/access_key.py`（`pre_serve` 是唯一入口）
- 前端：`local_ext/web_patch.js`
- 测试：`tests/test_auth.py`（覆盖白名单、伪造 Cookie、IP 白名单、200+Set-Cookie 换 Cookie）
