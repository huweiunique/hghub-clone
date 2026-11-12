#!/usr/bin/env python3
"""一键跑全部本地测试（Windows / Linux / macOS 通用，纯标准库）。

    python tests/run_all.py            # 默认只跑不需要上网的用例
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
    ap.add_argument("--online", action="store_true",
                    help="包含需要真实上游网络的用例")
    ap.add_argument("--web", default="", help="已运行的网页服务地址")
    ap.add_argument("--proxy", default="", help="已运行的播放代理地址")
    args = ap.parse_args()

    os.environ["ONLINE"] = "1" if args.online else "0"
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

    suite = unittest.defaultTestLoader.discover(start_dir=HERE, pattern="test_*.py",
                                                top_level_dir=HERE)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    total = result.testsRun
    skipped = len(result.skipped)
    print(f"\n== 共 {total} 个用例：通过 {total - len(result.failures) - len(result.errors) - skipped}"
          f" / 跳过 {skipped} / 失败 {len(result.failures)} / 错误 {len(result.errors)}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
