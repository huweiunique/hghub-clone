"""第三方优选列表：按运营商缓存，显式刷新绕过缓存；不在服务器上冒充手机测速。"""
import ipaddress
import threading
import time
import urllib.request

_CACHE = {}
_LOCK = threading.Lock()
TTL = 600


def fetch_list(isp):
    req = urllib.request.Request("https://cf.090227.xyz/" + isp,
                                 headers={"User-Agent": "HGhub"})
    with urllib.request.urlopen(req, timeout=10) as response:
        text = response.read(256 * 1024).decode("utf-8", "replace")
    ips = []
    for item in text.replace(",", "\n").splitlines():
        raw = item.split("#", 1)[0].strip()
        try:
            ip = str(ipaddress.ip_address(raw))
        except ValueError:
            continue
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise ValueError("列表中没有有效 IP")
    return ips


def get_list(isp, force=False):
    isp = isp if isp in ("ct", "cu", "cmcc") else "ct"
    with _LOCK:
        saved = _CACHE.get(isp)
    if not force and saved and time.monotonic() - saved[0] < TTL:
        return saved[1], True
    ips = fetch_list(isp)
    with _LOCK:
        _CACHE[isp] = (time.monotonic(), ips)
    return ips, False


def serve(handler, qs):
    isp = (qs.get("isp") or ["auto"])[0]
    force = (qs.get("force") or [""])[0] == "1"
    handler._local_headers = (getattr(handler, "_local_headers", []) or []) + [
        ("Cache-Control", "no-store")]
    try:
        # auto 沿用原先的电信首选规则，避免把服务器的网络当作用户的运营商。
        ips, cached = get_list(isp, force)
        handler._json(200, {"status": 1, "data": {
            "isp": isp, "ips": ips, "cached": cached, "source": "cf.090227.xyz"}})
    except (OSError, ValueError):
        handler._json(502, {"status": 0, "msg": "优选列表获取失败，请稍后重试"})
