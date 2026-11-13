"""macOS 编译实际原生控制器，以可控网络回执验证合并、测速、选择及取消。"""
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
import Foundation
import Network
import WebKit

func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw NSError(domain: "fixture", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
}

Task { @MainActor in
    let scenario = CommandLine.arguments[1]
    let host = "fixture-\(UUID().uuidString.lowercased()).invalid"
    let key = "cf_preferred_\(host):443"
    defer { UserDefaults.standard.removeObject(forKey: key) }
    let url = URL(string: "https://\(host)/?key=fixture-do-not-send")!
    var calls: [String: Int] = [:]
    var active = 0
    var peak = 0
    var events: [String] = []
    let auto = ["192.0.2.1", "192.0.2.2", "2001:db8::1", "192.0.2.3"]
    let controller = PreferredIPController(url: url, loadAutomatic: { _ in
        if scenario == "source-failure" { throw NSError(domain: "fixture", code: 1) }
        return auto
    }, measureIP: { ip in
        active += 1; peak = max(peak, active)
        defer { active -= 1 }
        calls[ip, default: 0] += 1
        if scenario == "cancel" { try await Task.sleep(nanoseconds: 2_000_000_000) }
        else { try await Task.sleep(nanoseconds: 5_000_000) }
        if scenario == "all-failed" || ip == "192.0.2.1" { throw NSError(domain: "fixture", code: 2) }
        events.append(ip)
        return ip == "192.0.2.4" ? 20 : 100
    })
    defer { controller.stop() }
    do {
        if scenario == "bridge-origin" {
            let secure = URL(string: "https://fixture.invalid/")!
            let plain = URL(string: "http://fixture.invalid/")!
            let custom = URL(string: "https://fixture.invalid:8443/")!
            try require(WebBridgeOrigin.allows(scheme: "https", host: "fixture.invalid", port: 0, isMainFrame: true, backend: secure), "HTTPS 默认端口0必须可用")
            try require(WebBridgeOrigin.allows(scheme: "https", host: "fixture.invalid", port: 443, isMainFrame: true, backend: secure), "HTTPS显式443必须可用")
            try require(WebBridgeOrigin.allows(scheme: "http", host: "fixture.invalid", port: 0, isMainFrame: true, backend: plain), "HTTP默认端口0必须可用")
            try require(WebBridgeOrigin.allows(scheme: "https", host: "fixture.invalid", port: 8443, isMainFrame: true, backend: custom), "自定义端口必须精确匹配")
            try require(!WebBridgeOrigin.allows(scheme: "https", host: "fixture.invalid", port: 0, isMainFrame: true, backend: custom), "默认端口不能放行到8443")
            try require(!WebBridgeOrigin.allows(scheme: "https", host: "other.invalid", port: 0, isMainFrame: true, backend: secure), "不同域名不能放行")
            try require(!WebBridgeOrigin.allows(scheme: "http", host: "fixture.invalid", port: 0, isMainFrame: true, backend: secure), "不同协议不能放行")
            try require(!WebBridgeOrigin.allows(scheme: "https", host: "fixture.invalid", port: 0, isMainFrame: false, backend: secure), "子框架不能放行")
        } else if scenario == "cancel" {
            let running = Task { try await controller.handle(["action":"save", "mode":"auto", "isp":"ct", "customIPs":"192.0.2.4"]) }
            while !(controller.snapshot()["running"] as? Bool ?? false) { await Task.yield() }
            _ = try await controller.handle(["action":"cancel"])
            let result = try await running.value
            try require(result["selectedIP"] as? String == "", "取消不能选择部分结果")
            try require(result["running"] as? Bool == false, "取消后必须解除忙状态")
        } else if scenario == "invalid" {
            do {
                _ = try await controller.handle(["action":"save", "mode":"auto", "isp":"ct", "customIPs":"192.0.2.4\nhttps://invalid/"])
                throw NSError(domain: "fixture-unexpected", code: 1)
            } catch {
                try require((error as NSError).domain != "fixture-unexpected", "非法地址必须拒绝")
                try require(calls.isEmpty, "非法配置不能开始测量")
            }
        } else {
            let result = try await controller.handle(["action":"save", "mode":"auto", "isp":"ct",
                "customIPs":"192.0.2.2\n192.0.2.4\n2001:0db8:0:0:0:0:0:1"])
            let rows = result["results"] as? [[String: Any]] ?? []
            if scenario == "all-failed" {
                try require(result["selectedIP"] as? String == "", "全部失败必须清空选择")
                try require(result["status"] as? String == "default", "全部失败必须普通连接")
            } else {
                try require(result["selectedIP"] as? String == "192.0.2.4", "应选择成功且平均耗时最低的自定义 IP")
                try require(calls["192.0.2.4"] == 2, "候选需测试两次")
                try require(rows.contains { $0["ip"] as? String == "192.0.2.4" && $0["ms"] as? Double == 20 }, "应记录平均耗时")
            }
            if scenario == "selection" {
                try require(rows.count == 5, "自动列表和自定义应合并并按地址字节去重")
                try require(calls["192.0.2.2"] == 2 && calls["2001:db8::1"] == 2, "重复地址不能重复测试")
                try require(rows.contains { $0["ip"] as? String == "192.0.2.2" && $0["source"] as? String == "自动＋自定义" }, "应保留双来源")
                try require(peak <= 3 && peak > 1, "测量应并发且不能超过三项")
                let restored = PreferredIPController(url: url)
                try require(restored.snapshot()["selectedIP"] as? String == "192.0.2.4", "重启应恢复已验证的选择")
                restored.stop()
            }
            if scenario == "source-failure" {
                try require(rows.count == 3, "自动源不可用时仍应测全部有效自定义候选")
            }
        }
        print("ok \(scenario)"); exit(0)
    } catch { fputs("\(error)\n", stderr); exit(1) }
}
dispatchMain()
'''


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('swiftc'), '需要 macOS/Swift/WebKit，未运行原生择优测试')
class PreferredIPRankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / '.test-tmp').mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / '.test-tmp')
        cls.addClassCleanup(cls.temp.cleanup)
        folder = Path(cls.temp.name)
        (folder / 'main.swift').write_text(HARNESS, encoding='utf-8')
        cls.binary = str(folder / 'selection-fixture')
        sources = ROOT / 'ios/HGhub/HGhub'
        build = subprocess.run(['swiftc', '-target', platform.machine() + '-apple-macos14.0',
                                str(sources / 'PreferredIP.swift'), str(sources / 'PreferredIPRanking.swift'),
                                str(sources / 'WebBridgeOrigin.swift'),
                                str(folder / 'main.swift'), '-o', cls.binary], capture_output=True, text=True, timeout=60)
        if build.returncode:
            raise AssertionError(build.stderr)

    def run_scenario(self, name):
        result = subprocess.run([self.binary, name], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_combined_candidates_are_deduplicated_measured_and_fastest_selected(self):
        self.run_scenario('selection')

    def test_all_failures_use_normal_connection(self):
        self.run_scenario('all-failed')

    def test_custom_candidates_work_when_source_is_down(self):
        self.run_scenario('source-failure')

    def test_cancel_does_not_choose_partial_results(self):
        self.run_scenario('cancel')

    def test_invalid_custom_input_is_rejected_before_measurement(self):
        self.run_scenario('invalid')

    def test_default_ports_are_normalized_without_relaxing_origin_checks(self):
        self.run_scenario('bridge-origin')


if __name__ == '__main__':
    unittest.main()
