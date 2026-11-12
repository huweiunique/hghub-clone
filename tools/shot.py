#!/usr/bin/env python3
"""用 Chrome DevTools Protocol 给正在运行的 HGhub 网页截图（无需 Playwright）。

    python tools/shot.py http://127.0.0.1:8881/ shots/01-home.png --wait ".slide" --delay 6

依赖：本机装了 Chrome/Edge；Python 3 标准库即可（用 websocket 手写 CDP 帧）。
"""
import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_chrome():
    env = os.environ.get("CHROME_BIN")
    if env and os.path.exists(env):
        return env
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("找不到 Chrome/Edge，可用 CHROME_BIN 指定")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WS:
    """最小 WebSocket 客户端（只处理 CDP 需要的文本帧）。"""

    def __init__(self, url):
        _, rest = url.split("://", 1)
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\n"
               f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        if b" 101 " not in buf.split(b"\r\n")[0]:
            raise RuntimeError(f"WebSocket handshake failed: {buf[:200]}")
        self.buf = buf.split(b"\r\n\r\n", 1)[1]
        self.msg_id = 0

    def _recv(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("socket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, obj):
        data = json.dumps(obj).encode()
        header = bytearray([0x81])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        while True:
            b1, b2 = self._recv(2)
            opcode = b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._recv(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._recv(8))[0]
            payload = self._recv(n) if n else b""
            if opcode == 0x8:
                raise RuntimeError("websocket closed")
            if opcode in (0x1, 0x2):
                return json.loads(payload)

    def call(self, method, params=None, timeout=60):
        self.msg_id += 1
        mid = self.msg_id
        self.send({"id": mid, "method": method, "params": params or {}})
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self.recv()
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(method)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("out")
    ap.add_argument("--width", type=int, default=430)
    ap.add_argument("--height", type=int, default=932)
    ap.add_argument("--wait", default="", help="等待出现的 CSS 选择器")
    ap.add_argument("--delay", type=float, default=5.0, help="等待后额外 sleep 秒数")
    ap.add_argument("--wait-timeout", type=float, default=60.0)
    ap.add_argument("--eval", default="", help="截图前执行的 JS")
    ap.add_argument("--full", action="store_true", help="整页截图")
    args = ap.parse_args()

    chrome = find_chrome()
    port = free_port()
    profile = tempfile.mkdtemp(prefix="hg-shot-")
    proc = subprocess.Popen([
        chrome, "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--hide-scrollbars",
        "--autoplay-policy=no-user-gesture-required",
        f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
        f"--window-size={args.width},{args.height}", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(100):
            try:
                data = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1))
                ws_url = data["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.1)
        if not ws_url:
            raise SystemExit("Chrome 没有起来")

        ws = WS(ws_url)
        target = ws.call("Target.createTarget", {"url": "about:blank"})
        tid = target["targetId"]
        sess = ws.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]

        def cmd(method, params=None, timeout=60):
            ws.msg_id += 1
            mid = ws.msg_id
            ws.send({"id": mid, "method": method, "sessionId": sess, "params": params or {}})
            deadline = time.time() + timeout
            while time.time() < deadline:
                msg = ws.recv()
                if msg.get("id") == mid:
                    if "error" in msg:
                        raise RuntimeError(f"{method}: {msg['error']}")
                    return msg.get("result", {})
            raise TimeoutError(method)

        cmd("Page.enable")
        cmd("Runtime.enable")
        cmd("Emulation.setDeviceMetricsOverride", {
            "width": args.width, "height": args.height,
            "deviceScaleFactor": 2, "mobile": True})
        cmd("Page.navigate", {"url": args.url})

        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                r = cmd("Runtime.evaluate", {"expression": "document.readyState", "returnByValue": True})
                if r["result"].get("value") == "complete":
                    break
            except Exception:
                pass
            time.sleep(0.3)

        if args.wait:
            deadline = time.time() + args.wait_timeout
            while time.time() < deadline:
                r = cmd("Runtime.evaluate", {"expression":
                        f"document.querySelectorAll({json.dumps(args.wait)}).length > 0",
                        "returnByValue": True})
                if r["result"].get("value"):
                    break
                time.sleep(0.4)
            else:
                print(f"warning: selector {args.wait} not found within "
                      f"{args.wait_timeout}s", file=sys.stderr)

        time.sleep(args.delay)
        if args.eval:
            try:
                r = cmd("Runtime.evaluate", {"expression": args.eval, "awaitPromise": True,
                                             "returnByValue": True})
                if r.get("result"):
                    print("eval:", json.dumps(r["result"].get("value"), ensure_ascii=False))
                if r.get("exceptionDetails"):
                    print("eval exception:", json.dumps(r["exceptionDetails"], ensure_ascii=False))
            except RuntimeError as exc:
                # 页面在 eval 里主动刷新（例如输入密钥后 location.reload()）会中断 CDP 调用
                print(f"eval interrupted (page navigated): {exc}")
            time.sleep(1.0)

        metrics = cmd("Page.getLayoutMetrics")
        params = {"format": "png", "captureBeyondViewport": args.full}
        if args.full:
            params["clip"] = {"x": 0, "y": 0, "width": args.width,
                              "height": max(args.height,
                                            metrics["cssContentSize"]["height"]),
                              "scale": 1}
        shot = cmd("Page.captureScreenshot", params)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "wb") as f:
            f.write(base64.b64decode(shot["data"]))
        print(f"saved {args.out} ({os.path.getsize(args.out)} bytes)")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    main()
