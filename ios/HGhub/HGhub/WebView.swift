import SwiftUI
import WebKit

struct ContentView: View {
    @ObservedObject var settings: AppSettings
    @State private var showSetup = false
    // 地址/密钥变化后强制重建 WebView（否则 WKWebView 不会重新加载新地址）
    @State private var reloadToken = UUID()

    var body: some View {
        ZStack(alignment: .topTrailing) {
            if let url = settings.entryURL {
                WebView(url: url)
                    .id(reloadToken)
                    .ignoresSafeArea(edges: .bottom)
            } else {
                VStack(spacing: 12) {
                    Text("HGhub").font(.largeTitle).bold()
                    Text("还没有配置后端地址").foregroundStyle(.secondary)
                    Button("设置地址与密钥") { showSetup = true }
                        .buttonStyle(.borderedProminent)
                }
            }
            Button {
                showSetup = true
            } label: {
                Image(systemName: "gearshape.fill")
                    .padding(10)
                    .background(.ultraThinMaterial, in: Circle())
            }
            .padding(.trailing, 14)
            .padding(.top, 54)
            .opacity(0.85)
        }
        .sheet(isPresented: $showSetup) {
            SetupView(settings: settings, isPresented: $showSetup) {
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

    @State private var testing = false
    @State private var testResult: String?
    @State private var testOK = false

    var body: some View {
        NavigationStack {
            Form {
                Section("后端地址") {
                    TextField("http://192.168.1.10:8081/", text: $settings.appURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                }
                Section {
                    SecureField("访问密钥（后端开启鉴权时必填）", text: $settings.accessKey)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    HStack {
                        Button(testing ? "测试中…" : "测试连接") { test() }
                            .disabled(testing || settings.entryURL == nil)
                        Spacer()
                        if let r = testResult {
                            Text(r)
                                .font(.footnote)
                                .foregroundStyle(testOK ? .green : .red)
                        }
                    }
                } header: {
                    Text("访问密钥")
                } footer: {
                    Text("密钥只保存在本机，不会随安装包分发。可以填任意字符串（字母/数字/符号），长度越长越安全。"
                         + "连接成功会自动换 Cookie，之后不用再输入。")
                }
                Section("构建时内置（只读）") {
                    LabeledContent("地址") {
                        Text(settings.builtInURL.isEmpty ? "—" : settings.builtInURL)
                            .lineLimit(1).truncationMode(.middle)
                    }
                    if !settings.builtInURL.isEmpty {
                        Button("恢复内置地址") { settings.restoreBuiltIn() }
                    }
                }
            }
            .navigationTitle("设置")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { isPresented = false }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存并打开") {
                        onSaved()
                        isPresented = false
                    }
                }
            }
        }
    }

    /// 先请求 /health（不需要密钥），再请求受保护接口确认密钥是否有效
    private func test() {
        guard let base = URL(string: settings.appURL), var comps = URLComponents(url: base, resolvingAgainstBaseURL: false) else {
            testOK = false; testResult = "地址格式不对"; return
        }
        testing = true
        testResult = nil
        comps.path = "/health"
        comps.query = nil
        guard let healthURL = comps.url else { testing = false; return }

        var probe = URLComponents(url: base, resolvingAgainstBaseURL: false)!
        probe.path = "/api/site/categories/video"
        let key = settings.normalizedAccessKey
        probe.queryItems = key.isEmpty ? nil : [URLQueryItem(name: "key", value: key)]
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

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []
        config.websiteDataStore = .default()
        config.preferences.javaScriptCanOpenWindowsAutomatically = true

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.isOpaque = false
        webView.backgroundColor = .black
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        // 地址变化时重新加载（设置面板保存后）
        if let current = webView.url?.absoluteString,
           current.hasPrefix(url.absoluteString.components(separatedBy: "?").first ?? "") {
            return
        }
        webView.load(URLRequest(url: url))
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator: NSObject, WKNavigationDelegate {
        func webView(_ webView: WKWebView,
                     decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            decisionHandler(.allow)
        }
    }
}
