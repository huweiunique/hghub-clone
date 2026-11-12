#!/usr/bin/env bash
# 在 macOS 上构建未签名 .ipa（GitHub Actions 的 macos runner 里跑）。
#
#   APP_URL="http://1.2.3.4:8081/" ACCESS_KEY="xxxx" bash ios/build-ipa.sh
#   # 产物：dist/HGhub-<version>-unsigned.ipa
#
# 未签名 IPA 不能直接装到真机，需要自己重签（Sideloadly / AltStore / 开发者证书）：
#   unzip HGhub.ipa -d payload && codesign -f -s "Apple Development: you@x" ...
# 文档见 docs/release.md。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJ_DIR="$ROOT/ios/HGhub"
SCHEME="HGhub"
APP_URL="${APP_URL:-}"
ACCESS_KEY="${ACCESS_KEY:-}"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :MARKETING_VERSION' "$PROJ_DIR/HGhub.xcodeproj/project.pbxproj" 2>/dev/null | head -1 || true)"
[ -z "$VERSION" ] && VERSION="1.2.0.8"

echo "[ios] APP_URL=${APP_URL:-<空，首次打开在 App 内填写>}"
echo "[ios] ACCESS_KEY=$([ -n "$ACCESS_KEY" ] && echo '<已设置>' || echo '<空>')"

# 生成 AppConfig.plist 打进 bundle（不写进源码，避免密钥进仓库）
mkdir -p "$PROJ_DIR/HGhub"
cat > "$PROJ_DIR/HGhub/AppConfig.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>AppURL</key>
	<string>${APP_URL}</string>
	<key>AccessKey</key>
	<string>${ACCESS_KEY}</string>
</dict>
</plist>
PLIST

# 把 AppConfig.plist 加入工程资源（用 PlistBuddy/xcodebuild 动态加更麻烦，
# 这里直接把文件放进 Sources 目录并让 pbxproj 用 folder reference 之外的显式引用；
# 为简单起见，构建后用 cp 放进 .app 里 —— 见下面 Copy Bundle Resources 的替代做法）
cd "$PROJ_DIR"
echo "[ios] xcodebuild archive（未签名）"
xcodebuild \
  -project HGhub.xcodeproj \
  -scheme "$SCHEME" \
  -configuration Release \
  -sdk iphoneos \
  -destination "generic/platform=iOS" \
  -archivePath build/HGhub.xcarchive \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  CODE_SIGN_IDENTITY="" \
  DEVELOPMENT_TEAM="" \
  ONLY_ACTIVE_ARCH=NO \
  | tee build.log | tail -40

APP_PATH="build/HGhub.xcarchive/Products/Applications/HGhub.app"
[ -d "$APP_PATH" ] || { echo "[ios] 归档里没找到 HGhub.app" >&2; exit 1; }

# AppConfig.plist 必须在 Bundle 里，AppSettings 才能读到
cp "$PROJ_DIR/HGhub/AppConfig.plist" "$APP_PATH/AppConfig.plist"

OUT="$ROOT/dist"
mkdir -p "$OUT"
rm -rf build/Payload && mkdir -p build/Payload
cp -R "$APP_PATH" build/Payload/
(cd build && /usr/bin/zip -qry "$OUT/HGhub-${VERSION}-unsigned.ipa" Payload)

echo "[ios] 产物：$OUT/HGhub-${VERSION}-unsigned.ipa"
ls -lh "$OUT/HGhub-${VERSION}-unsigned.ipa"
unzip -l "$OUT/HGhub-${VERSION}-unsigned.ipa" | head -10
