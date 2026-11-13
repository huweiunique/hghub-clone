import SwiftUI

@main
struct HGhubApp: App {
    @StateObject private var settings = AppSettings()

    var body: some Scene {
        WindowGroup {
            ContentView(settings: settings)
                .preferredColorScheme(.dark)
                .statusBarHidden(false)
        }
    }
}

/// 后端地址 + 访问密钥。
/// 地址可以由构建时注入（AppConfig.plist 的 AppURL）；**密钥一律不内置**，
/// 首次打开由用户输入并保存在本机（UserDefaults），避免分发包里带密钥。
final class AppSettings: ObservableObject {
    private let defaults = UserDefaults.standard

    /// 构建时内置的地址（只读，给设置面板展示）；密钥永远为空
    let builtInURL: String
    let builtInKey = ""

    @Published var appURL: String {
        didSet { defaults.set(appURL, forKey: "app_url") }
    }
    @Published var accessKey: String {
        didSet { defaults.set(accessKey, forKey: "access_key") }
    }

    init() {
        let bURL = AppSettings.bundleValue("AppURL")
        builtInURL = bURL
        let savedURL = defaults.string(forKey: "app_url") ?? ""
        let savedKey = defaults.string(forKey: "access_key") ?? ""
        appURL = savedURL.isEmpty ? bURL : savedURL
        accessKey = savedKey
    }

    /// 恢复为构建时内置的地址（密钥保持用户输入的值）
    func restoreBuiltIn() {
        appURL = builtInURL
    }

    static func bundleValue(_ key: String) -> String {
        guard let path = Bundle.main.path(forResource: "AppConfig", ofType: "plist"),
              let dict = NSDictionary(contentsOfFile: path),
              let value = dict[key] as? String else { return "" }
        return value
    }

    /// 密钥去掉首尾空白/换行：粘贴时最容易带上，服务端按原样比对会判错，
    /// 表现为“网页里能进、App 里一直重复弹框”。
    var normalizedAccessKey: String {
        accessKey.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// 拼出带密钥的入口地址（首页用 ?key= 换 Cookie，之后所有请求凭 Cookie）
    var entryURL: URL? {
        guard !appURL.isEmpty, var comps = URLComponents(string: appURL) else { return nil }
        let key = normalizedAccessKey
        if !key.isEmpty {
            var q = comps.queryItems ?? []
            q.removeAll { $0.name == "key" }
            q.append(URLQueryItem(name: "key", value: key))
            comps.queryItems = q
        }
        return comps.url
    }
}
