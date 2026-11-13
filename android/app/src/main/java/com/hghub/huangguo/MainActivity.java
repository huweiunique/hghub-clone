package com.hghub.huangguo;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import javax.net.ssl.SNIHostName;
import javax.net.ssl.SSLParameters;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;

/**
 * HGhub 复刻版 Android 壳：全屏竖屏 WebView。
 * 1.2.0.2：前端页面打进 APK 的 assets 里（assets/hghub/index.html +
 * hls.min.js），打开先加载本地页面（秒开、弱网也能看到界面），
 * 列表/播放再联网拉；相对路径以 APP_URL 为 base，API 仍走服务器。
 * 播放走直连 CDN（默认）或 8080 代理（备用）。
 * 1.2.0.8 优选 IP：APP_URL 默认就是构建时注入的域名（BuildConfig.APP_URL）；
 * 首屏先拉 cf.090227.xyz 的优选 IP（有缓存直接用缓存秒开、后台刷新，
 * 没缓存最多等约 3 秒），再加载本地页面，这样首屏 /api/* 就能走优选 IP；
 * 拦截时用优选 IP 连 443、SNI 写该域名（Cloudflare 证书校验正常），
 * 并转发 Cookie、禁 gzip（Accept-Encoding: identity），失败回退默认节点。
 * 优选域名取自 BuildConfig.APP_URL / FALLBACK_URL 的 host，不在代码里写死，
 * 换服务器只需构建时换环境变量。
 */
public class MainActivity extends Activity {

    private static final String PREFS = "hghub";
    private static final String KEY_URL = "app_url";
    // 本地扩展：后端访问密钥（对应 HGHUB_ACCESS_KEY）
    private static final String KEY_ACCESS = "access_key";

    private WebView webView;
    // 1.2.0.5 优选 IP：cf.090227.xyz 上别人测好的 CF 优选 IP。
    // WebView 打开 APP_URL/FALLBACK_URL 的域名时，用优选 IP 建连、SNI 仍写该域名，
    // 这样既走最快节点、证书校验也正常；拉不到就走 Cloudflare 默认节点。
    private volatile String prefIp = null;
    private volatile boolean prefIpEnabled = true;
    private volatile boolean fellBack = false;
    private volatile String baseUrl = null;

    /** 从 URL 取 host，解析失败返回 null。 */
    private static String hostOf(String url) {
        if (url == null || url.isEmpty()) return null;
        try { return new URL(url).getHost(); } catch (Exception e) { return null; }
    }

    /** 是否为优选域名：构建时注入的 APP_URL / FALLBACK_URL 的 host。 */
    private static boolean isPrefHost(String host) {
        if (host == null || host.isEmpty()) return false;
        return host.equals(hostOf(BuildConfig.APP_URL)) || host.equals(hostOf(BuildConfig.FALLBACK_URL));
    }
    private FrameLayout fullscreenContainer;
    private View customView;
    private WebChromeClient.CustomViewCallback customViewCallback;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // 全屏沉浸
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN,
                WindowManager.LayoutParams.FLAG_FULLSCREEN);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        String url = savedUrl();
        if (url == null || url.isEmpty()) {
            showUrlSetup();
        } else {
            showWebView(url);
        }
    }

    private String savedUrl() {
        String fromPrefs = getSharedPreferences(PREFS, MODE_PRIVATE)
                .getString(KEY_URL, null);
        if (fromPrefs != null && !fromPrefs.isEmpty()) {
            return withAccessKey(fromPrefs);
        }
        // 构建时填入的地址优先于空值
        String builtIn = BuildConfig.APP_URL;
        return (builtIn == null || builtIn.isEmpty()) ? null : withAccessKey(builtIn);
    }

    /**
     * 本地扩展：给地址追加访问密钥（?key=），后端据此下发 Cookie。
     * 优先用用户在设置里填的，其次用构建时注入的 APP_ACCESS_KEY。
     * 没有密钥时原样返回（后端没开鉴权的情况）。
     */
    private String withAccessKey(String url) {
        String key = getSharedPreferences(PREFS, MODE_PRIVATE)
                .getString(KEY_ACCESS, null);
        if (key == null || key.isEmpty()) {
            key = BuildConfig.APP_ACCESS_KEY;
        }
        if (key == null || key.isEmpty() || url == null || url.isEmpty()) {
            return url;
        }
        try {
            // 纯字符串拼接，避免使用 Uri.Builder 的较新方法（本工程 minSdk 24）
            int hash = url.indexOf('#');
            String frag = hash >= 0 ? url.substring(hash) : "";
            String base = hash >= 0 ? url.substring(0, hash) : url;
            int qm = base.indexOf('?');
            String path = qm >= 0 ? base.substring(0, qm) : base;
            String query = qm >= 0 ? base.substring(qm + 1) : "";
            StringBuilder sb = new StringBuilder();
            if (!query.isEmpty()) {
                for (String pair : query.split("&")) {
                    if (pair.isEmpty()) continue;
                    String k = android.net.Uri.decode(pair.split("=", 2)[0]);
                    if ("key".equals(k)) continue;
                    if (sb.length() > 0) sb.append('&');
                    sb.append(pair);
                }
            }
            if (sb.length() > 0) sb.append('&');
            sb.append("key=").append(android.net.Uri.encode(key));
            return path + "?" + sb + frag;
        } catch (Exception e) {
            return url;
        }
    }

    /** 首次打开：输入复刻版网页地址 +（可选）访问密钥，保存在本地。 */
    private void showUrlSetup() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (24 * getResources().getDisplayMetrics().density);
        root.setPadding(pad, pad * 3, pad, pad);

        TextView title = new TextView(this);
        title.setText("HGhub");
        title.setTextSize(28);
        root.addView(title);

        TextView hint = new TextView(this);
        hint.setText("输入复刻版网页地址（部署后的地址），只输一次，之后直接打开刷剧。");
        hint.setPadding(0, pad, 0, pad);
        root.addView(hint);

        EditText input = new EditText(this);
        input.setHint("https://…");
        String builtIn = BuildConfig.APP_URL;
        if (builtIn != null && !builtIn.isEmpty()) {
            input.setText(builtIn);
        }
        root.addView(input);

        // 本地扩展：访问密钥（后端设了 HGHUB_ACCESS_KEY 时需要）
        TextView keyHint = new TextView(this);
        keyHint.setText("访问密钥（后端开启了鉴权时填写，可留空）");
        keyHint.setPadding(0, pad, 0, 0);
        root.addView(keyHint);

        EditText keyInput = new EditText(this);
        keyInput.setHint("访问密钥");
        keyInput.setSingleLine(true);
        String savedKey = getSharedPreferences(PREFS, MODE_PRIVATE)
                .getString(KEY_ACCESS, null);
        if (savedKey != null && !savedKey.isEmpty()) {
            keyInput.setText(savedKey);
        } else if (BuildConfig.APP_ACCESS_KEY != null) {
            keyInput.setText(BuildConfig.APP_ACCESS_KEY);
        }
        root.addView(keyInput);

        Button open = new Button(this);
        open.setText("打开");
        open.setOnClickListener(v -> {
            String url = input.getText().toString().trim();
            String key = keyInput.getText().toString().trim();
            if (!url.isEmpty()) {
                if (!url.startsWith("http://") && !url.startsWith("https://")) {
                    url = "https://" + url;
                }
                getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                        .putString(KEY_URL, url)
                        .putString(KEY_ACCESS, key)
                        .apply();
                showWebView(withAccessKey(url));
            }
        });
        root.addView(open);

        Button clear = new Button(this);
        clear.setText("清除已保存地址与密钥");
        clear.setOnClickListener(v -> {
            getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                    .remove(KEY_URL).remove(KEY_ACCESS).apply();
            input.setText("");
            keyInput.setText("");
        });
        root.addView(clear);

        setContentView(root);
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void showWebView(String url) {
        FrameLayout root = new FrameLayout(this);
        webView = new WebView(this);
        root.addView(webView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        fullscreenContainer = new FrameLayout(this);
        fullscreenContainer.setVisibility(View.GONE);
        root.addView(fullscreenContainer, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);
        baseUrl = url;
        String cachedIp = getSharedPreferences(PREFS, MODE_PRIVATE).getString("pref_ip", null);
        if (cachedIp != null && !cachedIp.isEmpty()) {
            // 有缓存的优选 IP：直接用它秒开，后台再刷新
            prefIp = cachedIp;
            fetchPrefIpAsync(url, null);
            loadBundledPage(url);
        } else {
            // 没缓存：先拉优选 IP（最多等约 3 秒），拿到后再加载首屏
            fetchPrefIpAsync(url, new Runnable() {
                @Override public void run() {
                    runOnUiThread(new Runnable() {
                        @Override public void run() { loadBundledPage(url); }
                    });
                }
            });
        }

        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);                       // hls.js 需要
        s.setDomStorageEnabled(true);                       // 登录/历史/收藏
        s.setDatabaseEnabled(true);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setMediaPlaybackRequiresUserGesture(false);       // 刷到即播
        s.setAllowFileAccess(true);                     // 读 assets 里的本地页面
        s.setAllowFileAccessFromFileURLs(true);
        s.setAllowUniversalAccessFromFileURLs(true);    // 本地页可请求服务器 API
        s.setAllowContentAccess(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        s.setTextZoom(100);

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(webView, true);

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                // 站内跳转留在 WebView 里
                view.loadUrl(url);
                return true;
            }

            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                WebResourceResponse r = fetchViaPrefIp(request);
                return r != null ? r : super.shouldInterceptRequest(view, request);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                // 读网页设置里的优选 IP 开关 + 运营商，下次加载生效
                view.evaluateJavascript(
                        "(function(){try{return JSON.stringify({on:localStorage.getItem('hg_prefip'),isp:localStorage.getItem('hg_pref_isp')});}catch(e){return '{}';}})();",
                        new android.webkit.ValueCallback<String>() {
                            @Override
                            public void onReceiveValue(String v) {
                                try {
                                    if (v != null && v.contains("\"on\":\"false\"")) prefIpEnabled = false;
                                    else if (v != null && v.contains("\"on\":\"true\"")) prefIpEnabled = true;
                                    if (v != null) {
                                        Matcher im = Pattern.compile("\"isp\":\"(ct|cu|cmcc|auto)\"").matcher(v);
                                        if (im.find()) {
                                            String isp = im.group(1);
                                            if ("auto".equals(isp)) isp = "ct"; // 网页 auto 对应服务端 ct 列表
                                            String old = getSharedPreferences(PREFS, MODE_PRIVATE).getString("pref_isp", "ct");
                                            if (!isp.equals(old)) {
                                                getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString("pref_isp", isp).apply();
                                                fetchPrefIpOnly(); // 运营商换了，后台刷新优选 IP，下次加载生效
                                            }
                                        }
                                    }
                                } catch (Exception ignored) {}
                            }
                        });
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, android.webkit.WebResourceError error) {
                super.onReceivedError(view, request, error);
                maybeFallback(view, request.getUrl() != null ? request.getUrl().toString() : "");
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse errorResponse) {
                super.onReceivedHttpError(view, request, errorResponse);
                // 优选域名还没通（隧道未跑起来时会报 530）就回退到直连服务器地址
                if (errorResponse != null && errorResponse.getStatusCode() >= 500) {
                    maybeFallback(view, request.getUrl() != null ? request.getUrl().toString() : "");
                }
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onShowCustomView(View view, CustomViewCallback callback) {
                if (customView != null) {
                    callback.onCustomViewHidden();
                    return;
                }
                customView = view;
                customViewCallback = callback;
                webView.setVisibility(View.GONE);
                fullscreenContainer.setVisibility(View.VISIBLE);
                fullscreenContainer.addView(view, new FrameLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT));
            }

            @Override
            public void onHideCustomView() {
                if (customView == null) {
                    return;
                }
                fullscreenContainer.removeView(customView);
                customView = null;
                fullscreenContainer.setVisibility(View.GONE);
                if (customViewCallback != null) {
                    customViewCallback.onCustomViewHidden();
                }
                webView.setVisibility(View.VISIBLE);
            }
        });
    }

    /** 优选域名打不开（5xx/网络错）时，回退到构建时注入的直连地址（仅一次）。 */
    private void maybeFallback(WebView view, String failedUrl) {
        if (fellBack || failedUrl == null || !isPrefHost(hostOf(failedUrl))) return;
        String fb = BuildConfig.FALLBACK_URL;
        if (fb == null || fb.isEmpty()) return;
        fellBack = true;
        view.post(new Runnable() {
            @Override public void run() {
                getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_URL, fb).apply();
                loadBundledPage(fb);
            }
        });
    }

    /** 后台拉 cf.090227.xyz 的优选 IP（别人测好的，不用自己测）。完成后（成功或失败）必调 onDone。 */
    private void fetchPrefIpAsync(final String url, final Runnable onDone) {
        if (url == null || !isPrefHost(hostOf(url))) { // 非优选域名不需要优选 IP
            if (onDone != null) onDone.run();
            return;
        }
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    String isp = getSharedPreferences(PREFS, MODE_PRIVATE).getString("pref_isp", "ct");
                    if (!isp.equals("ct") && !isp.equals("cu") && !isp.equals("cmcc")) isp = "ct";
                    HttpURLConnection c = (HttpURLConnection) new URL("https://cf.090227.xyz/" + isp).openConnection();
                    c.setConnectTimeout(2500);
                    c.setReadTimeout(2500);
                    InputStream in = c.getInputStream();
                    ByteArrayOutputStream out = new ByteArrayOutputStream();
                    byte[] buf = new byte[4096];
                    int n;
                    while ((n = in.read(buf)) != -1) out.write(buf, 0, n);
                    in.close();
                    Matcher m = Pattern.compile("(\\d+\\.\\d+\\.\\d+\\.\\d+)\\s*#").matcher(out.toString("UTF-8"));
                    if (m.find()) {
                        prefIp = m.group(1);
                        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString("pref_ip", prefIp).apply();
                    }
                } catch (Exception ignored) { /* 拉不到就走默认节点 */ }
                if (onDone != null) onDone.run();
            }
        }).start();
    }

    /** 只刷新优选 IP（运营商切换后下次加载生效），不重载页面。 */
    private void fetchPrefIpOnly() {
        if (baseUrl != null) fetchPrefIpAsync(baseUrl, null);
    }

    /**
     * 优选 IP 拦截：只拦截优选域名（APP_URL/FALLBACK_URL 的 host）的 GET 请求。
     * 用优选 IP 连 443，TLS 的 SNI 写该域名（证书校验正常），
     * HTTP 请求头 Host 也写该域名。失败返回 null 走 WebView 默认加载。
     */
    private WebResourceResponse fetchViaPrefIp(WebResourceRequest request) {
        try {
            if (!prefIpEnabled || prefIp == null || request == null) return null;
            if (!"GET".equalsIgnoreCase(request.getMethod())) return null;
            android.net.Uri u = request.getUrl();
            if (u == null || !isPrefHost(u.getHost())) return null;
            String host = u.getHost();
            String path = u.getEncodedPath() == null ? "/" : u.getEncodedPath();
            if (u.getEncodedQuery() != null) path += "?" + u.getEncodedQuery();
            SSLSocket sock = (SSLSocket) SSLSocketFactory.getDefault().createSocket(prefIp, 443);
            SSLParameters params = sock.getSSLParameters();
            params.setServerNames(Collections.singletonList(new SNIHostName(host)));
            sock.setSSLParameters(params);
            sock.setSoTimeout(15000);
            sock.startHandshake();
            StringBuilder hb = new StringBuilder();
            hb.append("GET ").append(path).append(" HTTP/1.1\r\nHost: ").append(host).append("\r\n");
            hb.append("User-Agent: Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36\r\n");
            hb.append("Accept: */*\r\nAccept-Encoding: identity\r\nConnection: close\r\n");
            try {
                String ck = CookieManager.getInstance().getCookie("https://" + host);
                if (ck != null && !ck.isEmpty()) hb.append("Cookie: ").append(ck).append("\r\n");
            } catch (Exception ignored) {}
            hb.append("\r\n");
            sock.getOutputStream().write(hb.toString().getBytes(StandardCharsets.UTF_8));
            sock.getOutputStream().flush();
            InputStream in = sock.getInputStream();
            // 状态行
            String statusLine = readLine(in);
            if (statusLine == null || !statusLine.contains("200")) { try { sock.close(); } catch (Exception ignored) {} return null; }
            // 头
            Map<String, String> headers = new LinkedHashMap<>();
            String line;
            while ((line = readLine(in)) != null && !line.isEmpty()) {
                int i = line.indexOf(':');
                if (i > 0) {
                    String k = line.substring(0, i).trim().toLowerCase();
                    String vv = line.substring(i + 1).trim();
                    headers.put(k, vv);
                    if ("set-cookie".equals(k)) {
                        try { CookieManager.getInstance().setCookie("https://" + host, vv); } catch (Exception ignored) {}
                    }
                }
            }
            byte[] body = readBody(in, headers);
            try { sock.close(); } catch (Exception ignored) {}
            String mime = "text/html";
            String charset = "UTF-8";
            String ct = headers.get("content-type");
            if (ct != null) {
                String[] parts = ct.split(";");
                if (parts.length > 0 && !parts[0].trim().isEmpty()) mime = parts[0].trim();
                for (String p : parts) {
                    p = p.trim();
                    if (p.toLowerCase().startsWith("charset=")) charset = p.substring(8);
                }
            }
            return new WebResourceResponse(mime, charset, new ByteArrayInputStream(body));
        } catch (Exception ignored) {
            return null;
        }
    }

    private static String readLine(InputStream in) throws java.io.IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        int b;
        while ((b = in.read()) != -1) {
            if (b == '\n') break;
            if (b != '\r') out.write(b);
        }
        if (b == -1 && out.size() == 0) return null;
        return out.toString("UTF-8");
    }

    private static byte[] readBody(InputStream in, Map<String, String> headers) throws java.io.IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        if ("chunked".equalsIgnoreCase(headers.get("transfer-encoding"))) {
            while (true) {
                String sizeLine = readLine(in);
                if (sizeLine == null) break;
                int size = Integer.parseInt(sizeLine.trim().split(";")[0], 16);
                if (size == 0) { readLine(in); break; }
                byte[] buf = new byte[size];
                int off = 0;
                while (off < size) { int r = in.read(buf, off, size - off); if (r == -1) break; off += r; }
                out.write(buf, 0, off);
                readLine(in);
            }
            return out.toByteArray();
        }
        String len = headers.get("content-length");
        if (len != null) {
            int total = Integer.parseInt(len.trim());
            byte[] buf = new byte[8192];
            int remain = total;
            while (remain > 0) {
                int r = in.read(buf, 0, Math.min(buf.length, remain));
                if (r == -1) break;
                out.write(buf, 0, r);
                remain -= r;
            }
            return out.toByteArray();
        }
        byte[] buf = new byte[8192];
        int r;
        while ((r = in.read(buf)) != -1) out.write(buf, 0, r);
        return out.toByteArray();
    }

    /**
     * 优先加载 APK 自带的本地页面（assets/hghub/index.html），以部署地址
     * 为 base URL，这样页面里的相对路径（/api/play、/proxy/*、/hls.min.js）
     * 仍解析到服务器；本地页面损坏或缺失时回退到直接联网加载。
     */
    private void loadBundledPage(String baseUrl) {
        try (InputStream in = getAssets().open("hghub/index.html")) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) != -1) {
                out.write(buf, 0, n);
            }
            String html = new String(out.toByteArray(), StandardCharsets.UTF_8);
            String base = baseUrl.endsWith("/") ? baseUrl : baseUrl + "/";
            webView.loadDataWithBaseURL(base, html, "text/html", "UTF-8", null);
        } catch (Exception e) {
            webView.loadUrl(baseUrl);
        }
    }

    @Override
    public void onBackPressed() {
        if (customView != null) {
            // 正在全屏播视频：先退出全屏
            new WebChromeClient().onHideCustomView();
            return;
        }
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
            return;
        }
        super.onBackPressed();
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (webView != null) {
            webView.onPause();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) {
            webView.onResume();
        }
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.destroy();
        }
        super.onDestroy();
    }
}
