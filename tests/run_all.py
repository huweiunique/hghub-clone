#!/usr/bin/env python3
"""一键跑全部本地测试（Windows / Linux / macOS 通用，纯标准库）。

    python tests/run_all.py            # 默认跑静态与后端离线用例，不启动浏览器
    python tests/run_all.py --ui       # 额外运行 Chromium UI 自动测试
    python tests/run_all.py --online   # 加上真实上游（播放/封面/列表）的用例
    python tests/run_all.py --web http://127.0.0.1:8081 --proxy http://127.0.0.1:8080
                                      # 测已经在跑的服务（如 Docker 容器）

退出码 0 = 全部通过 / 跳过；1 = 有失败。
"""

import argparse
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ui", action="store_true",
                    help="额外运行浏览器 UI 自动测试（需要 Chrome/Edge）")
    ap.add_argument("--online", action="store_true",
                    help="包含需要真实上游网络的用例")
    ap.add_argument("--web", default="", help="已运行的网页服务地址")
    ap.add_argument("--proxy", default="", help="已运行的播放代理地址")
    args = ap.parse_args()

    os.environ["ONLINE"] = "1" if args.online else "0"
    # 每次由显式参数决定，避免外部环境变量让后端 CI 意外启动浏览器。
    os.environ["HGHUB_UI_TESTS"] = "1" if args.ui else "0"
    # 显式清掉外部残留的环境变量，避免 --web/--proxy 与真实环境混用
    os.environ.pop("HGHUB_WEB_URL", None)
    os.environ.pop("HGHUB_PROXY_URL", None)
    if args.web:
        os.environ["HGHUB_WEB_URL"] = args.web
        os.environ["REQUIRE_DECRYPT"] = "1"   # 容器/远程环境必须能解密封面
    if args.proxy:
        os.environ["HGHUB_PROXY_URL"] = args.proxy

    # Windows 控制台默认不是 UTF-8，避免中文日志报错
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("浏览器 UI 自动测试：" + ("已启用" if args.ui else "未启用（使用 --ui 显式运行）"), flush=True)
    suite = unittest.defaultTestLoader.discover(start_dir=HERE, pattern="test_*.py",
                                                top_level_dir=HERE)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    total = result.testsRun
    # setUpClass 跳过不计入 testsRun，需与逐用例跳过分开统计。
    class_skips = sum(1 for test, _ in result.skipped
                      if isinstance(test, unittest.suite._ErrorHolder))
    skipped = len(result.skipped) - class_skips
    print(f"\n== 共 {total} 个用例：通过 {total - len(result.failures) - len(result.errors) - skipped}"
          f" / 跳过 {skipped} / 失败 {len(result.failures)} / 错误 {len(result.errors)}")
    if class_skips:
        print(f"另有 {class_skips} 个测试类因前置条件未满足而整体跳过（不计入上述用例数）")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
