import SwiftUI
import WebKit

struct ContentView: View {
    @ObservedObject var settings: AppSettings
    @State private var showSetup = false
    @State private var loadFailed = false
    @State private var immersivePlayback = false
    @State private var preparingConnection = true
    // 地址/密钥变化后强制重建 WebView（否则 WKWebView 不会重新加载新地址）
    @State private var reloadToken = UUID()

    var body: some View {
        ZStack {
            if let url = settings.entryURL {
                WebView(url: url,
                        hasKey: !settings.normalizedAccessKey.isEmpty,
                        onSettings: { showSetup = true },
                        onPlayerState: { immersivePlayback = $0 },
                        onPrepared: { preparingConnection = false },
                        onLoadFailed: { loadFailed = true })
                    .id(reloadToken)
                    .ignoresSafeArea(edges: immersivePlayback ? .all : .bottom)
            } else {
                VStack(spacing: 12) {
                    Text("HGhub").font(.largeTitle).bold()
                    Text("还没有配置后端地址").foregroundStyle(.secondary)
                    Button("设置地址与密钥") { showSetup = true }
                        .buttonStyle(.borderedProminent)
                }
            }
            if preparingConnection && settings.entryURL != nil && !loadFailed {
                ProgressView("正在准备连接…")
                    .padding(24)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
            }
            if loadFailed {
                VStack(spacing: 16) {
                    Text("服务连接失败").font(.headline)
                    Button("配置后端地址与密钥") { showSetup = true }
                        .buttonStyle(.borderedProminent)
                    Button("重试") { loadFailed = false; preparingConnection = true; reloadToken = UUID() }
                }
                .padding(24)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
            }
        }
        .statusBarHidden(immersivePlayback)
        .sheet(isPresented: $showSetup) {
            SetupView(settings: settings, isPresented: $showSetup) {
                loadFailed = false
                immersivePlayback = false
                preparingConnection = true
                reloadToken = UUID()
            }
        }
        .onAppear {
            if settings.entryURL == nil { showSetup = true }
        }
    }
}

struct SetupView: View {
    @ObservedObject var settings: AppSettings
    @Binding var isPresented: Bool
    var onSaved: () -> Void = {}

    @State private var draftURL = ""
    @State private var draftKey = ""
    @State private var testing = false
    @State private var testResult: String?
    @State private var testOK = false

    var body: some View {
        NavigationStack {
            Form {
                Section("后端地址") {
                    TextField("http://192.168.1.10:8081/", text: $draftURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                }
                Section {
                    SecureField("访问密钥（后端开启鉴权时必填）", text: $draftKey)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                } header: {
                    Text("访问密钥")
                } footer: {
                    Text("密钥只保存在本机，不会随安装包分发。可以填任意字符串（字母/数字/符号），长度越长越安全。"
                         + "连接成功会自动换 Cookie，之后不用再输入。")
                }
                Section {
                    Button(testing ? "测试中…" : "测试连接") { test() }
                        .disabled(testing || draftEntryURL == nil)
                    if let r = testResult {
                        Text(r).font(.footnote).foregroundStyle(testOK ? .green : .red)
                    }
                }
                Section("构建时内置地址（只读）") {
                    LabeledContent("地址") {
                        Text(settings.builtInURL.isEmpty ? "—" : settings.builtInURL)
                            .lineLimit(1).truncationMode(.middle)
                    }
                    if !settings.builtInURL.isEmpty {
                        Button("恢复内置地址") { draftURL = settings.builtInURL }
                    }
                }
                Section("版本") {
                    Text(AppSettings.versionDescription)
                        .font(.footnote)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .disabled(testing)
            .navigationTitle("设置")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { isPresented = false }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存并打开") {
                        settings.appURL = draftURL.trimmingCharacters(in: .whitespacesAndNewlines)
                        settings.accessKey = draftKey
                        onSaved()
                        isPresented = false
                    }
                    .disabled(testing || draftEntryURL == nil)
                }
            }
            .onAppear {
                draftURL = settings.appURL
                draftKey = settings.accessKey
            }
            .onChange(of: draftURL) { _ in testResult = nil }
            .onChange(of: draftKey) { _ in testResult = nil }
        }
    }

    private var draftEntryURL: URL? {
        AppSettings.makeEntryURL(address: draftURL, key: draftKey)
    }

    /// 先请求 /health（不需要密钥），再请求受保护接口确认密钥是否有效
    private func test() {
        guard let base = draftEntryURL, var comps = URLComponents(url: base, resolvingAgainstBaseURL: false) else {
            testOK = false; testResult = "地址格式不对"; return
        }
        testing = true
        testResult = nil
        comps.path = "/health"
        comps.query = nil
        guard let healthURL = comps.url else { testing = false; return }

        var probe = URLComponents(url: base, resolvingAgainstBaseURL: false)!
        probe.path = "/api/site/categories/video"
        probe.queryItems = URLComponents(url: base, resolvingAgainstBaseURL: false)?.queryItems
        guard let probeURL = probe.url else { testing = false; return }

        let cfg = URLSessionConfiguration.ephemeral
        cfg.timeoutIntervalForRequest = 12
        let session = URLSession(configuration: cfg)

        session.dataTask(with: healthURL) { _, resp, err in
            if let err = err {
                DispatchQueue.main.async { finish(false, "连不上：\(err.localizedDescription)") }
                return
            }
            guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else {
                DispatchQueue.main.async { finish(false, "服务异常（HTTP \((resp as? HTTPURLResponse)?.statusCode ?? -1)）") }
                return
            }
            session.dataTask(with: probeURL) { _, r2, _ in
                let code = (r2 as? HTTPURLResponse)?.statusCode ?? -1
                DispatchQueue.main.async {
                    if code == 401 { finish(false, "密钥不正确") }
                    else if code == 200 { finish(true, "连接成功") }
                    else { finish(false, "接口返回 \(code)") }
                }
            }.resume()
        }.resume()
    }

    private func finish(_ ok: Bool, _ msg: String) {
        testing = false
        testOK = ok
        testResult = msg
    }
}

/// WKWebView 壳：保留 Cookie（登录后免输密钥）、允许自动播放、支持内联视频。
struct WebView: UIViewRepresentable {
    let url: URL
    let hasKey: Bool
    let onSettings: () -> Void
    let onPlayerState: (Bool) -> Void
    let onPrepared: () -> Void
    let onLoadFailed: () -> Void

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []
        config.websiteDataStore = .default()
        config.preferences.javaScriptCanOpenWindowsAutomatically = true
        config.userContentController.add(context.coordinator, name: "hgSettings")
        config.userContentController.add(context.coordinator, name: "hgPlayer")
        config.userContentController.addScriptMessageHandler(context.coordinator, contentWorld: .page,
                                                              name: "hgPreferredIP")
        // 入口随 App 分发，原版服务无需部署 local_ext；只向同源主框架提供脱敏摘要。
        if let path = Bundle.main.path(forResource: "app_settings", ofType: "js"),
           let script = try? String(contentsOfFile: path, encoding: .utf8),
           var address = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            address.queryItems = address.queryItems?.filter { $0.name != "key" }
            let summary: [String: Any] = ["address": address.string ?? "", "hasKey": hasKey,
                                         "versionDescription": AppSettings.versionDescription,
                                         "preferredIPSupported": context.coordinator.preferredIP.supported]
            if let data = try? JSONSerialization.data(withJSONObject: summary),
               let json = String(data: data, encoding: .utf8) {
                let preferredScript = Bundle.main.path(forResource: "prefip_patch", ofType: "js")
                    .flatMap { try? String(contentsOfFile: $0, encoding: .utf8) } ?? ""
                let injected = "if (location.origin === new URL((\(json)).address).origin) { window.HGAppConfig = \(json);\n\(script)\n\(preferredScript)\n}"
                config.userContentController.addUserScript(WKUserScript(
                    source: injected, injectionTime: .atDocumentEnd, forMainFrameOnly: true))
            }
        }

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.isOpaque = false
        webView.backgroundColor = .black
        context.coordinator.preferredIP.prepare(store: config.websiteDataStore) { [weak webView, weak coordinator = context.coordinator] in
            coordinator?.initialLoadStarted = true
            onPrepared()
            webView?.load(URLRequest(url: url))
        }
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        guard context.coordinator.initialLoadStarted else { return }
        // 地址变化时重新加载（设置面板保存后）
        if let current = webView.url?.absoluteString,
           current.hasPrefix(url.absoluteString.components(separatedBy: "?").first ?? "") {
            return
        }
        webView.load(URLRequest(url: url))
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(url: url, onSettings: onSettings, onPlayerState: onPlayerState, onLoadFailed: onLoadFailed)
    }

    static func dismantleUIView(_ uiView: WKWebView, coordinator: Coordinator) {
        uiView.configuration.userContentController.removeScriptMessageHandler(forName: "hgSettings")
        uiView.configuration.userContentController.removeScriptMessageHandler(forName: "hgPlayer")
        uiView.configuration.userContentController.removeScriptMessageHandler(forName: "hgPreferredIP", contentWorld: .page)
        coordinator.preferredIP.stop()
        uiView.navigationDelegate = nil
        uiView.stopLoading()
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler, WKScriptMessageHandlerWithReply {
        let url: URL
        let onSettings: () -> Void
        let onPlayerState: (Bool) -> Void
        let onLoadFailed: () -> Void
        let preferredIP: PreferredIPController
        var initialLoadStarted = false

        init(url: URL, onSettings: @escaping () -> Void, onPlayerState: @escaping (Bool) -> Void, onLoadFailed: @escaping () -> Void) {
            self.url = url
            self.onSettings = onSettings
            self.onPlayerState = onPlayerState
            self.onLoadFailed = onLoadFailed
            self.preferredIP = PreferredIPController(url: url)
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage,
                                   replyHandler: @escaping (Any?, String?) -> Void) {
            let origin = message.frameInfo.securityOrigin
            guard message.name == "hgPreferredIP",
                  WebBridgeOrigin.allows(scheme: origin.protocol, host: origin.host, port: origin.port,
                                         isMainFrame: message.frameInfo.isMainFrame, backend: url),
                  let body = message.body as? [String: Any] else {
                replyHandler(nil, "不允许此页面访问优选配置"); return
            }
            Task {
                do { replyHandler(try await preferredIP.handle(body), nil) }
                catch { replyHandler(nil, error.localizedDescription) }
            }
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            let origin = message.frameInfo.securityOrigin
            guard WebBridgeOrigin.allows(scheme: origin.protocol, host: origin.host, port: origin.port,
                                         isMainFrame: message.frameInfo.isMainFrame, backend: url) else { return }
            if message.name == "hgSettings", message.body as? String == "open" { onSettings() }
            if message.name == "hgPlayer", let active = message.body as? Bool { onPlayerState(active) }
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            recover(webView, error: error)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            recover(webView, error: error)
        }

        private func recover(_ webView: WKWebView, error: Error) {
            guard (error as NSError).code != NSURLErrorCancelled else { return }
            if preferredIP.fallbackAfterNavigationFailure() { webView.load(URLRequest(url: url)) }
            else { onLoadFailed() }
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            // HTTP 错误通常不触发 didFail，仍提供可恢复的原生入口。
            webView.evaluateJavaScript("document.getElementById('meBox') !== null && !!window.HGAppConfig") { value, _ in
                if value as? Bool != true { self.onLoadFailed() }
            }
        }
        func webView(_ webView: WKWebView,
                     decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            decisionHandler(.allow)
        }
    }
}
