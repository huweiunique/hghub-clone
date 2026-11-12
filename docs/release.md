# 发版：APK / IPA / Docker

## 打一个 tag 就全自动

```bash
git tag -a v1.2.0.8 -m "HGhub 1.2.0.8"
git push origin v1.2.0.8
```

触发三条流水线，产物都进 **GitHub Release**：

| 流水线 | runner | 产物 | 说明 |
| --- | --- | --- | --- |
| `android-apk.yml` | ubuntu | `HGhub-1.2.0.8.apk` | debug 签名，可直接安装 |
| `ios-ipa.yml` | **macos-15** | `HGhub-1.2.0.8-unsigned.ipa` | 未签名，需重签 |
| `backend-tests.yml` | ubuntu | — | 离线用例 + Docker 构建 + 容器健康检查 |

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

## macOS runner 说明

- **`macos-14` 已于 2026-11-02 从 GitHub Actions 退役**，用它会瞬间被 cancel（本仓库踩过）。
- 当前用 `macos-15`（arm64）。可用标签见
  [actions/runner-images](https://github.com/actions/runner-images#available-images)。
- 公开仓库的 macOS 分钟数免费；私有的按分钟计费，且 macOS 倍率高。

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
