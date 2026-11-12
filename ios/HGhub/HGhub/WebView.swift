import SwiftUI
import WebKit

struct ContentView: View {
    @ObservedObject var settings: AppSettings
    @State private var showSetup = false

    var body: some View {
        ZStack(alignment: .topTrailing) {
            if let url = settings.entryURL {
                WebView(url: url)
                    .ignoresSafeArea(edges: .bottom)
            } else {
                VStack(spacing: 12) {
                    Text("HGhub").font(.largeTitle).bold()
                    Text("还没有配置后端地址").foregroundStyle(.secondary)
                    Button("设置地址") { showSetup = true }
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
            SetupView(settings: settings, isPresented: $showSetup)
        }
        .onAppear {
            if settings.entryURL == nil { showSetup = true }
        }
    }
}

struct SetupView: View {
    @ObservedObject var settings: AppSettings
    @Binding var isPresented: Bool

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
                    TextField("访问密钥（可选）", text: $settings.accessKey)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                } header: {
                    Text("访问密钥")
                } footer: {
                    Text("后端设了 HGHUB_ACCESS_KEY 时填写；打开时会自动换 Cookie，之后不用再输入。")
                }
            }
            .navigationTitle("设置")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") { isPresented = false }
                }
            }
        }
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
