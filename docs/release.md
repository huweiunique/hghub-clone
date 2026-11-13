# 发版：APK / IPA / Docker

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

## 注入后端地址与密钥

两个 app 都需要知道后端在哪：

- **APK**：`-PappUrl` / `APP_URL`，构建脚本写进 `BuildConfig.APP_URL`
- **IPA**：`APP_URL` + `ACCESS_KEY`，构建脚本写进 `AppConfig.plist`

```bash
gh workflow run android-apk.yml -f app_url="http://<IP>:8081/"
gh workflow run ios-ipa.yml -f app_url="http://<IP>:8081/" -f access_key="<KEY>"
```

留空时：APK 首次打开要求输入地址；IPA 有设置面板（右上角齿轮）输入地址和密钥。

> 密钥会打进 app 包里。若在意，可以只填地址，让用户首次打开时手输密钥
> （网页会弹「需要访问密钥」输入框，输入一次存 30 天 Cookie）。

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
