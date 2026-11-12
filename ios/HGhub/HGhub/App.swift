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

/// 后端地址 + 访问密钥。构建时由 build-ipa.sh 写进 AppConfig.plist；
/// 用户也可以在 App 里改（存 UserDefaults，优先级高于内置值）。
final class AppSettings: ObservableObject {
    private let defaults = UserDefaults.standard

    @Published var appURL: String {
        didSet { defaults.set(appURL, forKey: "app_url") }
    }
    @Published var accessKey: String {
        didSet { defaults.set(accessKey, forKey: "access_key") }
    }

    init() {
        let builtInURL = AppSettings.bundleValue("AppURL")
        let builtInKey = AppSettings.bundleValue("AccessKey")
        let savedURL = defaults.string(forKey: "app_url") ?? ""
        let savedKey = defaults.string(forKey: "access_key") ?? ""
        appURL = savedURL.isEmpty ? builtInURL : savedURL
        accessKey = savedKey.isEmpty ? builtInKey : savedKey
    }

    static func bundleValue(_ key: String) -> String {
        guard let path = Bundle.main.path(forResource: "AppConfig", ofType: "plist"),
              let dict = NSDictionary(contentsOfFile: path),
              let value = dict[key] as? String else { return "" }
        return value
    }

    /// 拼出带密钥的入口地址（首页用 ?key= 换 Cookie，之后所有请求凭 Cookie）
    var entryURL: URL? {
        guard !appURL.isEmpty, var comps = URLComponents(string: appURL) else { return nil }
        if !accessKey.isEmpty {
            var q = comps.queryItems ?? []
            q.removeAll { $0.name == "key" }
            q.append(URLQueryItem(name: "key", value: accessKey))
            comps.queryItems = q
        }
        return comps.url
    }
}
