# 发版：APK / IPA / Docker

## Nightly 附件保留规则

Nightly Release 仅保留最近一次成功发布的 APK 与未签名 IPA。发布流程先核对本次两个
安装包已完整上传，再清理该 Nightly 的其它上传附件；构建或上传失败时保留此前可用安装包。
正式版不执行此清理。成功上传后同时将 Nightly 标签向前同步到本次提交，避免源码链接仍指旧版。
GitHub 自动生成的 Source code (zip / tar.gz) 属于标签源码下载链接，
不属于上传附件，不能通过 Release 附件删除接口单独移除。

## 打一个 tag 就全自动

```bash
git tag -a v1.2.0.8 -m "HGhub 1.2.0.8"
git push origin v1.2.0.8
```

触发 **Release 工作流**（`.github/workflows/release.yml`），一个 run 里两个 job，
产物都进同一个 **GitHub Release**：

| job | runner | 产物 | 说明 |
| --- | --- | --- | --- |
| `apk` | ubuntu-latest | `HGhub-1.2.0.8.apk` | debug 签名，可直接安装 |
| `ipa` | macos-latest | `HGhub-1.2.0.8-unsigned.ipa` | 未签名，需重签 |

另一条 `backend-tests.yml` 在 push 到 main / PR 时跑，不参与发版。

不想打 tag 时也可以手动跑：Actions → 选工作流 → Run workflow，可填 `app_url` / `access_key`。
手动跑的产物在 **Artifacts** 里，不进 Release。

## 客户端里的「后端地址 + 访问密钥」

**两个客户端都有这两项配置**，优先级：App 内设置 > 构建时内置 > 首次打开手填。

| 客户端 | 设置入口 | 构建时注入 |
| --- | --- | --- |
| APK | 首次打开的设置页（地址 + 密钥），可清除后重填 | `APP_URL` / `APP_ACCESS_KEY`（Gradle：`-PappUrl` / `-PappAccessKey`） |
| IPA | 我的 → 设置：修改服务地址、可选密钥、测试连接 | 仅 `APP_URL` 写入 `AppConfig.plist`；密钥不参与构建 |

密钥最终以 `?key=` 附加到入口 URL，后端据此下发 Cookie，之后请求自动带上。

```bash
# 手动构建并注入（产物在 Actions → Artifacts）
gh workflow run release.yml \
  -f app_url="http://<IP>:8081/" \
  -f access_key="<与服务端 HGHUB_ACCESS_KEY 相同的值>"

# 本地构建
APP_URL="http://<IP>:8081/" APP_ACCESS_KEY="<KEY>" bash android/build-apk-manual.sh
APP_URL="http://<IP>:8081/" ACCESS_KEY="<KEY>" bash ios/build-ipa.sh
```

> 密钥会写进 app 包（dex / AppConfig.plist）。不想内置就留空，让用户首次打开手填；
> 网页本身也会弹「需要访问密钥」输入框（存 30 天 Cookie）。

## iOS 未签名 IPA 怎么用

未签名 IPA **不能直接装到 iPhone**（iOS 只认签名 + 描述文件）。三种方式：

1. **自签**（免费，7 天有效）：Sideloadly / AltStore / TrollStore
2. **开发者证书**：`codesign -f -s "Apple Development: xxx" Payload/HGhub.app`，
   再 `ios-deploy` 或 Xcode Devices 安装
3. **App Store / TestFlight**：需要 Apple Developer 账号（$99/年）+ 签名证书
   + provisioning profile，给 workflow 加 `-exportMethod app-store-connect` 与 secrets

工作流目前只产出**未签名包**（无需任何 Apple 账号），签名环节留给你按需接入。

## macOS runner 与打包方式（实测）

- `macos-14` 已于 2026-11-02 退役，用它会瞬间被 cancel。
- `macos-latest` / `macos-15` 有时能秒级分配，有时排队 15 分钟后取消
  （`duration_ms: 0`、无日志）。这是 GitHub 侧容量问题，重跑 `Release` 即可。
- **打包方式**：iOS 26.5 SDK 不允许 ad-hoc 签名，且 `CODE_SIGNING_ALLOWED=NO`
  时 `xcodebuild archive` 不出 archive。所以脚本用 `xcodebuild build` 产出无签名
  `.app`，再自己组装 `Payload/` 打成 IPA（Sideloadly/AltStore 负责重签）。
- 脚本会断言 `Assets.car` 存在，图标缺失时直接失败，不会推出白图标的包。

可用标签见 [actions/runner-images](https://github.com/actions/runner-images#available-images)。

## 版本号在哪改

| 位置 | 字段 |
| --- | --- |
| `android/app/src/main/AndroidManifest.xml` | `versionCode` / `versionName` |
| `android/app/build.gradle` | `versionCode` / `versionName` |
| `android/build-apk-manual.sh` | `VERSION_CODE` / `VERSION_NAME` / 产物文件名 |
| `ios/HGhub/HGhub.xcodeproj/project.pbxproj` | `MARKETING_VERSION` / `CURRENT_PROJECT_VERSION` |
| `Dockerfile` / `docker-compose.yml` | 镜像 tag |
| `tests/test_static.py` | 断言了包名与版本，改版本要同步 |

## Docker 发布

见 [deploy.md](deploy.md)。目前只能本地构建（本机未登录 Docker Hub）。
