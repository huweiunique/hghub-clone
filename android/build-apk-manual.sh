#!/usr/bin/env bash
# Manual APK build without Gradle (works where the Gradle daemon IPC fails).
#
# Requires: JDK 17 and Android SDK with platforms;android-34 and
# build-tools;34.0.0. Set JAVA_HOME and ANDROID_HOME, or edit the defaults.
# Produces: HGhub-1.2.0.8.apk (debug-signed) in the current directory.
# 1.2.0.8：构建时把 web/index.html + web/hls.min.js 同步进
# app/src/main/assets/hghub/，打进 APK（本地页面秒开，API 仍走服务器）。
set -euo pipefail

JAVA_HOME="${JAVA_HOME:-$HOME/workspace/.build-tmp/jdk17}"
ANDROID_HOME="${ANDROID_HOME:-$HOME/workspace/.build-tmp/android-sdk}"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/build-tools/34.0.0:$ANDROID_HOME/platform-tools:$PATH"

ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="$ROOT/app/src/main"
W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT
mkdir -p "$W"/{compiled-res,gen,classes,dex}

# APP_URL：复刻版网页的部署地址，构建时注入，仓库里不写死服务器 IP。
#   APP_URL="http://YOUR_SERVER_IP:8081/" bash android/build-apk-manual.sh
# 不传则默认值为空，首次打开时在应用内输入一次（保存在本地）。
APP_URL="${APP_URL:-}"
# FALLBACK_URL：hg 域名打不开（隧道未跑起来报 530）时回退的直连地址，构建时注入。
#   FALLBACK_URL="http://YOUR_SERVER_IP:8081/" bash android/build-apk-manual.sh
FALLBACK_URL="${FALLBACK_URL:-}"
# 访问密钥【故意不参与构建】：避免把密钥打进分发包。用户首次打开时自己输入并保存。
# 转义成 Java 字符串字面量（防引号/反斜杠破坏代码）
APP_URL_JAVA=$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1])[1:-1])' "$APP_URL")
FALLBACK_URL_JAVA=$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1])[1:-1])' "$FALLBACK_URL")

mkdir -p "$W/gen/com/hghub/huangguo"
cat > "$W/gen/com/hghub/huangguo/BuildConfig.java" <<EOF
package com.hghub.huangguoai;
public final class BuildConfig {
    public static final boolean DEBUG = true;
    public static final String APPLICATION_ID = "com.hghub.huangguoai";
    public static final String BUILD_TYPE = "debug";
    public static final int VERSION_CODE = 1208;
    public static final String VERSION_NAME = "1.2.0.8";
    // 构建时由环境变量 APP_URL 注入；为空则首次打开时在应用内输入一次。
    public static final String APP_URL = "$APP_URL_JAVA";
    // hg 域名打不开时回退的直连地址，同样构建时注入，仓库里不写服务器 IP。
    public static final String FALLBACK_URL = "$FALLBACK_URL_JAVA";
    // 访问密钥不内置：为空常量，运行时由用户在应用内输入并保存在本地。
    public static final String APP_ACCESS_KEY = "";
}
EOF

# 前端打进 APK：每次构建都从 web/ 同步最新页面 + hls.js（仓库里也留一份）。
mkdir -p "$SRC/assets/hghub"
cp "$ROOT/../web/index.html" "$SRC/assets/hghub/index.html"
cp "$ROOT/../web/hls.min.js" "$SRC/assets/hghub/hls.min.js"
aapt2 compile --dir "$SRC/res" -o "$W/compiled-res.zip"
aapt2 link -o "$W/app-unsigned.apk" \
  -I "$ANDROID_HOME/platforms/android-34/android.jar" \
  --manifest "$SRC/AndroidManifest.xml" --java "$W/gen" \
  -A "$SRC/assets" \
  --min-sdk-version 24 --target-sdk-version 34 "$W/compiled-res.zip"
javac -encoding UTF-8 -cp "$ANDROID_HOME/platforms/android-34/android.jar" \
  -d "$W/classes" $(find "$W/gen" "$SRC/java" -name '*.java')
(cd "$W/classes" && jar --create --file "$W/classes.jar" .)
d8 --output "$W/dex" --lib "$ANDROID_HOME/platforms/android-34/android.jar" "$W/classes.jar"

cp "$W/app-unsigned.apk" "$W/app-with-dex.apk"
python3 - "$W" <<'PY'
import sys, zipfile
w = sys.argv[1]
z = zipfile.ZipFile(f"{w}/app-with-dex.apk", "a", zipfile.ZIP_DEFLATED)
z.write(f"{w}/dex/classes.dex", "classes.dex")
z.close()
PY

KEYSTORE="${DEBUG_KEYSTORE:-$W/debug.keystore}"
if [ ! -f "$KEYSTORE" ]; then
  keytool -genkeypair -keystore "$KEYSTORE" -storepass android -keypass android \
    -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Android Debug,O=Android,C=US" -noprompt
fi
zipalign -f -p 4 "$W/app-with-dex.apk" "$W/app-aligned.apk"

# 产物名：HGhub-<版本>[-<渠道后缀>].apk
#   正式版：HGhub-1.2.0.8.apk
#   Nightly：HGhub-1.2.0.8-nightly-20261113-4ab18bf.apk（由 CI 传 ARTIFACT_SUFFIX）
APK_NAME="HGhub-1.2.0.8${ARTIFACT_SUFFIX:-}.apk"
apksigner sign --ks "$KEYSTORE" --ks-pass pass:android --key-pass pass:android \
  --out "$ROOT/$APK_NAME" "$W/app-aligned.apk"
apksigner verify "$ROOT/$APK_NAME"
aapt2 dump badging "$ROOT/$APK_NAME" | grep -E "package:|sdkVersion|targetSdkVersion|launchable-activity"
ls -la "$ROOT/$APK_NAME"
unzip -l "$ROOT/$APK_NAME" | grep -E "assets/|classes.dex"
