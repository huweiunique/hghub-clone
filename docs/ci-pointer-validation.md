# Linux CI 指针模拟修复验证

## 问题与修复

提交 `06392003de4bc25093bf965bf2c770b407520499` 的 [Backend tests 第 2 次尝试](https://github.com/huweiunique/xyz/actions/runs/43558928226/attempts/2) 在离线测试阶段失败：`test_desktop_navigation_stays_visible_while_video_controls_hide` 返回 `desktop=False`、导航隐藏。后续 Docker 构建步骤没有执行。

原用例用 `Emulation.setEmulatedMedia` 设置 `hover/pointer`，但 [Chromium 的媒体覆盖实现](https://github.com/chromium/chromium/blob/main/third_party/blink/renderer/core/css/media_feature_overrides.cc) 没有处理这两个特性。本机有鼠标时用例通过，Linux 无头环境则会暴露错误的测试前置条件。

测试浏览器启动时现明确设置 fine pointer 和 hover，数值来自 [Chromium 输入能力枚举](https://github.com/chromium/chromium/blob/main/third_party/blink/public/mojom/webpreferences/web_preferences.mojom)。触屏模拟改用实际生效的 `Emulation.setTouchEmulationEnabled`，同一用例检查桌面、触屏、恢复桌面三次状态及真实 CSS 显隐结果；没有跳过原断言。

仅修改测试与文档，业务页面、样式、代理、原生壳和构建流程均无改动。

## 本地验证（2026-11-14）

- 环境：Windows、Python 3.12.8、独立 headless Chromium 测试进程，离线页面夹具。
- 修复前，在启动浏览器时附加 `--blink-settings=availablePointerTypes=0,primaryPointerType=0,availableHoverTypes=0,primaryHoverType=0`，运行原失败用例，复现相同 `desktop=False / nav=hidden / actions=hidden` 断言失败。
- 修复后，`python -m unittest discover -s tests -p test_viewing_ui.py`：11 项通过，包含桌面、触屏与恢复桌面的媒体查询及导航显隐检查。
- `python tools/apply_local_patches.py --check`：全部 `already`，无文件需要修改。
- `python tests/run_all.py`：最终复核 156 项，137 通过、19 跳过、0 失败、0 错误。跳过项为未启用的在线测试。
- 首次完整验证有 2 个 Windows 浏览器清理错误（退出超时后 `taskkill` 返回非零、profile 文件锁），业务断言没有失败；待该测试浏览器退出后重跑完整测试，以上最终复核通过。首次运行不记为通过。

测试夹具负责关闭本次创建的浏览器和临时服务。此次属于测试环境修复，未启动额外业务服务验收页面，未做原生真机验证；本机 Docker 未启动。Linux 测试与 Docker 构建须以新提交的 Backend tests 运行结果为准，APK/IPA 不属于该工作流的产物。
