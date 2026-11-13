"""macOS 上编译实际 Swift 通道，用本机 TCP 服务验证；Windows/Linux 明确跳过。"""
from pathlib import Path
import queue
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EchoHandler(socketserver.BaseRequestHandler):
    def handle(self):
        while data := self.request.recv(65536):
            self.request.sendall(data)
        # 客户端半关闭写端后，仍应收到对端最后的数据。
        self.request.sendall(b'fixture-tail')


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('swiftc'), '需要 macOS 和 Swift 编译器，未验证原生 TCP 通道')
class PreferredIPTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / '.test-tmp').mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / '.test-tmp')
        cls.addClassCleanup(cls.temp.cleanup)
        folder = Path(cls.temp.name)
        # 取实际生产类，不复制或重写实现；控制器和 WebKit API 仍由 IPA 构建校验。
        source = (ROOT / 'ios/HGhub/HGhub/PreferredIP.swift').read_text(encoding='utf-8')
        source = source.split('@MainActor\nfinal class PreferredIPController')[0].replace('import WebKit', '')
        (folder / 'Transport.swift').write_text(source, encoding='utf-8')
        (folder / 'main.swift').write_text('''
import Foundation
import Network
let arguments = CommandLine.arguments
let proxy = CFConnectProxy(host: arguments[1], port: UInt16(arguments[2])!, ip: arguments[3], fallback: arguments[4] == "yes")
proxy.start { port in
    guard let port = port else { exit(1) }
    print(port); fflush(stdout)
}
dispatchMain()
''', encoding='utf-8')
        cls.binary = str(folder / 'proxy-fixture')
        build = subprocess.run(['swiftc', str(folder / 'Transport.swift'), str(folder / 'main.swift'), '-o', cls.binary],
                               capture_output=True, text=True, timeout=60)
        if build.returncode:
            raise AssertionError(build.stderr)
        cls.server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), EchoHandler)
        cls.server.daemon_threads = True
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    def start_proxy(self, ip='127.0.0.1', fallback=False, host='backend.example.invalid'):
        process = subprocess.Popen([self.binary, host, str(self.server.server_address[1]), ip, 'yes' if fallback else 'no'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(process.stderr.close)
        self.addCleanup(process.stdout.close)
        def stop():
            process.terminate(); process.wait(timeout=5)
        self.addCleanup(stop)
        result = queue.Queue()
        threading.Thread(target=lambda: result.put(process.stdout.readline()), daemon=True).start()
        try:
            port = int(result.get(timeout=5))
        except (queue.Empty, ValueError):
            raise AssertionError('Swift 通道没有返回监听端口')
        connection = socket.create_connection(('127.0.0.1', port), timeout=10)
        self.addCleanup(connection.close)
        return connection

    def connect_header(self, connection, host='backend.example.invalid', port=None):
        target_port = port if port is not None else self.server.server_address[1]
        request = f'CONNECT {host}:{target_port} HTTP/1.1\r\nHost: {host}:{target_port}\r\n\r\n'.encode()
        # 分片请求头也必须被正确解析。
        connection.sendall(request[:12]); connection.sendall(request[12:])
        response = b''
        while b'\r\n\r\n' not in response:
            chunk = connection.recv(4096)
            if not chunk:
                return response
            response += chunk
        return response

    def test_tunnel_preserves_bytes_and_half_close_tail(self):
        connection = self.start_proxy()
        self.assertIn(b'200 Connection Established', self.connect_header(connection))
        payload = bytes(range(256)) * 300
        connection.sendall(payload)
        connection.shutdown(socket.SHUT_WR)
        received = b''
        while chunk := connection.recv(65536):
            received += chunk
        self.assertEqual(len(received), len(payload) + len(b'fixture-tail'),
                         f'转发数据不完整：收到 {len(received)} 字节，期望 {len(payload) + len(b"fixture-tail")} 字节；末尾={received[-24:]!r}')
        self.assertEqual(received, payload + b'fixture-tail')

    def test_other_domain_or_port_is_rejected(self):
        for host, port in [('another.invalid', None), ('backend.example.invalid', 1)]:
            with self.subTest(host=host, port=port):
                self.assertNotIn(b'200', self.connect_header(self.start_proxy(), host, port))

    def test_unreachable_ip_falls_back_only_when_allowed(self):
        # 127.0.0.2 没有监听服务；localhost 是原目标，回退后才能成功。
        connection = self.start_proxy(ip='127.0.0.2', fallback=True, host='localhost')
        self.assertIn(b'200', self.connect_header(connection, 'localhost'))
        strict = self.start_proxy(ip='127.0.0.2', fallback=False, host='localhost')
        self.assertNotIn(b'200', self.connect_header(strict, 'localhost'))


if __name__ == '__main__':
    unittest.main()
