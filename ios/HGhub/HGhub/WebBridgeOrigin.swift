import Foundation

/// WebKit 可能用 0 表示 URL 的默认端口；比较来源时统一展开，仍严格限制主框架、协议、域名及端口。
enum WebBridgeOrigin {
    static func allows(scheme: String, host: String, port: Int, isMainFrame: Bool, backend: URL) -> Bool {
        let standardPort = scheme == "https" ? 443 : 80
        return isMainFrame && scheme == backend.scheme && host == backend.host
            && (port == 0 ? standardPort : port) == (backend.port ?? (backend.scheme == "https" ? 443 : 80))
    }
}
