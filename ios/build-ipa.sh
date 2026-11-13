#!/usr/bin/env bash
# 在 macOS 上构建未签名 .ipa（GitHub Actions 的 macos runner 里跑）。
#
#   APP_URL="http://1.2.3.4:8081/" bash ios/build-ipa.sh
#   访问密钥【不参与构建】：用户在 App 首次打开时输入并保存，避免分发包带密钥。
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
ACCESS_KEY=""
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :MARKETING_VERSION' "$PROJ_DIR/HGhub.xcodeproj/project.pbxproj" 2>/dev/null | head -1 || true)"
[ -z "$VERSION" ] && VERSION="1.2.0.8"
# 渠道后缀由 CI 注入：正式版为空，Nightly 形如 -nightly-20261113-4ab18bf
SUFFIX="${ARTIFACT_SUFFIX:-}"

echo "[ios] APP_URL=${APP_URL:-<空，首次打开在 App 内填写>}"
echo "[ios] 访问密钥：不内置，首次打开时在 App 内输入"

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
rm -rf "$PROJ_DIR/build" "$PROJ_DIR/build.log"
mkdir -p "$PROJ_DIR/build"

echo "[ios] xcodebuild build（不签名，直接产出 .app）"
# 关键点（都踩过）：
#   1. CODE_SIGNING_ALLOWED=NO 时 xcodebuild archive 只 build、不生成 .xcarchive；
#   2. iOS 26.5 SDK 起不允许 ad-hoc（CODE_SIGN_IDENTITY="-"）签名：
#      "Ad Hoc code signing is not allowed with SDK 'iOS 26.5'"。
# 所以这里直接 build 到 DerivedData，再自己组装 Payload/，不经过 archive。
xcodebuild \
  -project "$PROJ_DIR/HGhub.xcodeproj" \
  -scheme "$SCHEME" \
  -configuration Release \
  -sdk iphoneos \
  -destination "generic/platform=iOS" \
  -derivedDataPath "$PROJ_DIR/build/DerivedData" \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  CODE_SIGN_IDENTITY="" \
  DEVELOPMENT_TEAM="" \
  ONLY_ACTIVE_ARCH=NO \
  > "$PROJ_DIR/build.log" 2>&1 || {
    echo "[ios] xcodebuild 失败，最后 60 行：" >&2
    tail -60 "$PROJ_DIR/build.log" >&2
    exit 1
  }
grep -E "BUILD SUCCEEDED|BUILD FAILED" "$PROJ_DIR/build.log" || true
tail -10 "$PROJ_DIR/build.log"

# 从 DerivedData 里找 Release-iphoneos/HGhub.app
APP_PATH="$PROJ_DIR/build/DerivedData/Build/Products/Release-iphoneos/HGhub.app"
if [ ! -d "$APP_PATH" ]; then
  echo "[ios] 默认路径没有 app，搜索 DerivedData："
  find "$PROJ_DIR/build/DerivedData" -name "HGhub.app" -type d -maxdepth 6 || true
  APP_PATH="$(find "$PROJ_DIR/build/DerivedData" -name "HGhub.app" -type d | grep -v '\.app\.' | head -1)"
fi
[ -n "$APP_PATH" ] && [ -d "$APP_PATH" ] || {
  echo "[ios] 构建产物里没找到 HGhub.app" >&2
  exit 1
}
echo "[ios] app 路径：$APP_PATH"
ls -la "$APP_PATH" || true
file "$APP_PATH/HGhub" || true

# AppConfig.plist 必须在 Bundle 里，AppSettings 才能读到
cp "$PROJ_DIR/HGhub/AppConfig.plist" "$APP_PATH/AppConfig.plist"
plutil -p "$APP_PATH/AppConfig.plist"

# 完整性断言：资源目录编译产物必须存在（AppIcon 缺图片时 actool 不会生成 Assets.car，
# 装到手机上就是白图标；本仓库踩过）。缺了就 fail，别产出半个包。
if [ ! -f "$APP_PATH/Assets.car" ]; then
  echo "[ios] 缺少 Assets.car（Assets.xcassets 未编译）：" >&2
  ls -la "$APP_PATH" >&2
  echo "[ios] 检查 AppIcon.appiconset/Contents.json 是否引用真实 png" >&2
  exit 1
fi
echo "[ios] 资源包：" "$(du -sh "$APP_PATH/Assets.car" | cut -f1)" "Assets.car"

# ---------------------------------------------------------------------------
# 组装未签名 IPA：
#   1. 副本放到 Payload/
#   2. 去掉原来的 _CodeSignature、以及 archive 里的 .xcent 等签名残留
#   3. 用 ad-hoc 重签所有 Mach-O（失败则降级为完全无签名，交给重签工具处理）
# 两种形态 Sideloadly / AltStore / TrollStore 都能接受。
# ---------------------------------------------------------------------------
Work="$PROJ_DIR/build/ipa"
rm -rf "$Work" && mkdir -p "$Work/Payload"
cp -R "$APP_PATH" "$Work/Payload/"
APP="$Work/Payload/HGhub.app"
rm -rf "$APP"/*.xcent "$APP"/embedded.mobileprovision "$APP"/_CodeSignature 2>/dev/null || true

# 找到所有 Mach-O（可执行文件 / dylib / framework 里的二进制）；逐个签，避免路径含空格出错
SIGN_LOCKED=0
while IFS= read -r bin; do
  [ -n "$bin" ] || continue
  codesign --force --sign - --timestamp=none "$bin" 2>>"$PROJ_DIR/build.log" || SIGN_LOCKED=1
done < <(find "$APP" -type f \( -perm -111 -o -name "*.dylib" \) \
           ! -name "*.plist" ! -name "InfoPlist.strings" 2>/dev/null)
[ "$SIGN_LOCKED" = "0" ] || echo "[ios] 部分二进制 ad-hoc 签名失败，改为完全无签名包" >&2

# 重签后资源封存会变，去掉残留的 CodeResources，避免安装器报签名不一致
rm -rf "$APP/_CodeSignature"
codesign --verify --deep --strict "$APP" 2>>"$PROJ_DIR/build.log" && echo "[ios] 签名校验通过" || echo "[ios] 无签名包（将由重签工具处理）"

OUT="$ROOT/dist"
mkdir -p "$OUT"
IPA_NAME="HGhub-${VERSION}${SUFFIX}-unsigned.ipa"
rm -f "$OUT/$IPA_NAME"
(cd "$Work" && /usr/bin/zip -qry "$OUT/$IPA_NAME" Payload)

echo "[ios] 产物：$OUT/$IPA_NAME"
ls -lh "$OUT/$IPA_NAME"
unzip -l "$OUT/$IPA_NAME" | head -15
