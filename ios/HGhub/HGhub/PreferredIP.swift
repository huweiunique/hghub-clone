import Foundation
import Network
import WebKit

/// 只改 TCP 连接目标；CONNECT 内的 TLS 仍由 WebKit/URLSession 按原域名验证。
/// 不修改系统代理，不解密 HTTPS，不把访问密钥交给第三方优选列表。
final class CFConnectProxy {
    private let queue = DispatchQueue(label: "hghub.cf-connect")
    private let host: String
    private let port: UInt16
    private let ip: String
    private let fallback: Bool
    private let onFallback: () -> Void
    private var listener: NWListener?
    private var tunnels: [UUID: Tunnel] = [:]

    init(host: String, port: UInt16, ip: String, fallback: Bool = true,
         onFallback: @escaping () -> Void = {}) {
        self.host = host.lowercased(); self.port = port; self.ip = ip
        self.fallback = fallback; self.onFallback = onFallback
    }

    func start(_ completion: @escaping (UInt16?) -> Void) {
        queue.async { [self] in
            do {
                let parameters = NWParameters.tcp
                parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
                let listener = try NWListener(using: parameters)
                self.listener = listener
                var finished = false
                func finish(_ port: UInt16?) {
                    guard !finished else { return }; finished = true
                    DispatchQueue.main.async { completion(port) }
                }
                listener.stateUpdateHandler = { state in
                    switch state {
                    case .ready:
                        listener.stateUpdateHandler = nil; finish(listener.port?.rawValue)
                    case .failed, .cancelled:
                        listener.stateUpdateHandler = nil; finish(nil)
                    default: break
                    }
                }
                listener.newConnectionHandler = { [weak self] incoming in
                    guard let self = self else { incoming.cancel(); return }
                    let id = UUID()
                    let tunnel = Tunnel(incoming: incoming, host: self.host, port: self.port,
                                        ip: self.ip, fallback: self.fallback, queue: self.queue,
                                        onFallback: self.onFallback,
                                        onClose: { [weak self] in self?.tunnels.removeValue(forKey: id) })
                    self.tunnels[id] = tunnel
                    tunnel.start()
                }
                listener.start(queue: queue)
                queue.asyncAfter(deadline: .now() + 3) {
                    if !finished { listener.cancel(); finish(nil) }
                }
            } catch { DispatchQueue.main.async { completion(nil) } }
        }
    }

    func stop() {
        queue.async { [self] in
            listener?.cancel(); listener = nil
            let active = Array(tunnels.values)
            active.forEach { $0.close() }
            tunnels.removeAll()
        }
    }

    private final class Tunnel {
        let incoming: NWConnection
        let host: String
        let port: UInt16
        let ip: String
        let fallback: Bool
        let queue: DispatchQueue
        let onFallback: () -> Void
        let onClose: () -> Void
        var outgoing: NWConnection?
        var header = Data()
        var closed = false
        var established = false
        var generation = 0
        var completedDirections = 0

        init(incoming: NWConnection, host: String, port: UInt16, ip: String,
             fallback: Bool, queue: DispatchQueue, onFallback: @escaping () -> Void,
             onClose: @escaping () -> Void) {
            self.incoming = incoming; self.host = host; self.port = port; self.ip = ip
            self.fallback = fallback; self.queue = queue
            self.onFallback = onFallback; self.onClose = onClose
        }

        func start() {
            incoming.stateUpdateHandler = { [weak self] state in
                if case .failed = state { self?.close() }
            }
            incoming.start(queue: queue)
            readHeader()
            queue.asyncAfter(deadline: .now() + 15) { [weak self] in
                if let self = self, !self.established { self.close() }
            }
        }

        func readHeader() {
            incoming.receive(minimumIncompleteLength: 1, maximumLength: 8192) { [weak self] data, _, done, error in
                guard let self = self, !self.closed else { return }
                if let data = data { self.header.append(data) }
                guard self.header.count <= 16384, error == nil else { self.close(); return }
                if let end = self.header.range(of: Data("\r\n\r\n".utf8)) {
                    let first = String(decoding: self.header[..<end.lowerBound], as: UTF8.self)
                        .components(separatedBy: "\r\n")[0].split(separator: " ")
                    // 即使 WebKit 将子域名也匹配到代理，这里仍只允许精确后端域名和端口。
                    guard first.count == 3, first[0] == "CONNECT",
                          first[1].lowercased() == "\(self.host):\(self.port)",
                          first[2] == "HTTP/1.1" else { self.close(); return }
                    self.header = Data(self.header[end.upperBound...])
                    self.connect(to: self.ip, isFallback: false)
                } else if done { self.close() }
                else { self.readHeader() }
            }
        }

        func connect(to target: String, isFallback: Bool) {
            generation += 1
            let current = generation
            let connection = NWConnection(host: NWEndpoint.Host(target),
                                          port: NWEndpoint.Port(rawValue: port)!, using: .tcp)
            outgoing = connection
            func failed() {
                guard !self.closed, current == self.generation, !self.established else { return }
                self.generation += 1
                connection.cancel()
                if self.fallback && !isFallback {
                    DispatchQueue.main.async { self.onFallback() }
                    self.connect(to: self.host, isFallback: true)
                } else { self.close() }
            }
            connection.stateUpdateHandler = { [weak self] state in
                guard let self = self, !self.closed, current == self.generation else { return }
                switch state {
                case .ready:
                    self.established = true
                    self.incoming.send(content: Data("HTTP/1.1 200 Connection Established\r\n\r\n".utf8),
                                       completion: .contentProcessed { [weak self] error in
                        guard let self = self, error == nil else { self?.close(); return }
                        connection.send(content: self.header, completion: .contentProcessed { [weak self] error in
                            guard let self = self, error == nil else { self?.close(); return }
                            self.header.removeAll()
                            self.pipe(self.incoming, to: connection)
                            self.pipe(connection, to: self.incoming)
                        })
                    })
                case .failed:
                    if self.established { self.close() } else { failed() }
                default: break
                }
            }
            connection.start(queue: queue)
            queue.asyncAfter(deadline: .now() + 5) { failed() }
        }

        func pipe(_ source: NWConnection, to target: NWConnection) {
            // Smaller bounded reads keep NWConnection flowing across a large write followed by
            // TCP half-close; a single 64 KiB read can be reported as complete before queued tail bytes.
            source.receive(minimumIncompleteLength: 1, maximumLength: 16384) { [weak self] data, _, done, error in
                guard let self = self, !self.closed else { return }
                guard error == nil else { self.close(); return }
                // 先完成最后一块数据的发送，再单独发 FIN，保持数据和写关闭的顺序。
                target.send(content: data, isComplete: true, completion: .contentProcessed { [weak self] error in
                    guard let self = self, !self.closed else { return }
                    if error != nil { self.close() }
                    else if done {
                        target.send(content: nil, contentContext: .finalMessage, isComplete: true,
                                    completion: .contentProcessed { [weak self] error in
                            guard let self = self, !self.closed else { return }
                            if error != nil { self.close(); return }
                            self.completedDirections += 1
                            if self.completedDirections == 2 { self.close() }
                            else {
                                self.queue.asyncAfter(deadline: .now() + 15) { [weak self] in self?.close() }
                            }
                        })
                    } else { self.pipe(source, to: target) }
                })
            }
        }

        func close() {
            guard !closed else { return }; closed = true
            incoming.stateUpdateHandler = nil; outgoing?.stateUpdateHandler = nil
            incoming.cancel(); outgoing?.cancel(); onClose()
        }
    }
}

@MainActor
final class PreferredIPController {
    let url: URL
    private let key: String
    private var proxy: CFConnectProxy?
    private weak var store: WKWebsiteDataStore?
    private var mode = "auto"
    private var isp = "ct"
    private var customIPs: [String] = []
    private var automaticIPs: [String] = []
    private var fetchedAt: TimeInterval = 0
    private var selectedIP = ""
    private var selectedAt: TimeInterval = 0
    private var selectedMilliseconds: Double?
    private var status = "default"
    private var message = "普通连接"
    private var busy = false
    private var stopped = false
    private var measurements: [PreferredIPMeasurement] = []
    private var measurementTask: Task<Void, Error>?
    private var cancelRequested = false
    private let loadAutomatic: (@MainActor (String) async throws -> [String])?
    private let measureIP: (@MainActor (String) async throws -> Double)?

    init(url: URL, loadAutomatic: (@MainActor (String) async throws -> [String])? = nil,
         measureIP: (@MainActor (String) async throws -> Double)? = nil) {
        self.url = url
        self.loadAutomatic = loadAutomatic; self.measureIP = measureIP
        key = "cf_preferred_" + (url.host ?? "") + ":" + String(url.port ?? 443)
        let saved = UserDefaults.standard.dictionary(forKey: key) ?? [:]
        mode = saved["mode"] as? String == "off" ? "off" : "auto"
        isp = saved["isp"] as? String ?? "ct"
        customIPs = saved["customIPs"] as? [String]
            ?? ((try? PreferredIPRanking.parse(saved["customIP"] as? String ?? "", strict: false)) ?? [])
        automaticIPs = saved["automaticIPs"] as? [String] ?? []
        fetchedAt = saved["fetchedAt"] as? TimeInterval ?? 0
        if saved["schema"] as? Int == 2 {
            measurements = (saved["measurements"] as? [[String: Any]] ?? []).compactMap { value in
                guard let ip = value["ip"] as? String, let source = value["source"] as? String,
                      let state = value["state"] as? String else { return nil }
                return PreferredIPMeasurement(ip: ip, source: source, state: state,
                                              milliseconds: value["ms"] as? Double, error: value["error"] as? String ?? "")
            }
            let previous = saved["selectedIP"] as? String ?? ""
            if let milliseconds = saved["selectedMilliseconds"] as? Double,
               milliseconds.isFinite && milliseconds >= 0, Self.validIP(previous) {
                selectedIP = previous
                selectedAt = saved["selectedAt"] as? TimeInterval ?? 0
                selectedMilliseconds = milliseconds
            }
        }
    }

    var supported: Bool {
        if #available(iOS 17.0, *) {
            let port = url.port ?? 443
            guard let host = url.host, !host.contains(":"), !host.contains("[") else { return false }
            return url.scheme == "https" && !Self.validIP(host) && (1...65535).contains(port)
        }
        return false
    }

    func snapshot() -> [String: Any] {
        ["supported": supported, "mode": mode, "isp": isp, "customIPs": customIPs,
         "automaticIPs": automaticIPs, "selectedIP": selectedIP, "selectedAt": selectedAt,
         "results": measurements.map { $0.json }, "running": busy,
         "completed": measurements.filter { ["ok", "failed"].contains($0.state) }.count,
         "total": measurements.count, "status": status, "message": message]
    }

    private func save() {
        var values: [String: Any] = ["schema": 2, "mode": mode, "isp": isp, "customIPs": customIPs,
                                    "automaticIPs": automaticIPs, "fetchedAt": fetchedAt,
                                    "selectedIP": selectedIP, "selectedAt": selectedAt,
                                    "measurements": measurements.map { $0.json }]
        if let selectedMilliseconds = selectedMilliseconds { values["selectedMilliseconds"] = selectedMilliseconds }
        UserDefaults.standard.set(values, forKey: key)
    }

    static func validIP(_ value: String) -> Bool {
        IPv4Address(value) != nil || IPv6Address(value) != nil
    }

    func prepare(store: WKWebsiteDataStore, completion: @escaping () -> Void) {
        self.store = store
        // 首屏复用已测出的选择；批量测速由用户发起，避免首屏等待大量坏地址。
        Task {
            await apply()
            if !stopped { completion() }
        }
    }

    private func fetchIPs() async throws -> [String] {
        if let loadAutomatic = loadAutomatic { return try await loadAutomatic(isp) }
        let path = ["ct", "cu", "cmcc"].contains(isp) ? isp : "ct"
        var request = URLRequest(url: URL(string: "https://cf.090227.xyz/" + path)!)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = 6
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil
        config.timeoutIntervalForResource = 8
        let session = URLSession(configuration: config)
        defer { session.invalidateAndCancel() }
        let (data, response) = try await session.data(for: request)
        try Task.checkCancellation()
        guard (response as? HTTPURLResponse)?.statusCode == 200, data.count <= 256 * 1024 else {
            throw failure("优选列表服务返回异常")
        }
        let ips = try PreferredIPRanking.parse(String(decoding: data, as: UTF8.self), strict: false)
        guard !ips.isEmpty else { throw failure("列表中没有有效 IP") }
        return ips
    }

    @available(iOS 17.0, *)
    private func configuration(port: UInt16) -> ProxyConfiguration {
        var config = ProxyConfiguration(httpCONNECTProxy: .hostPort(host: "127.0.0.1",
                                            port: NWEndpoint.Port(rawValue: port)!), tlsOptions: nil)
        config.matchDomains = [url.host!]
        config.allowFailover = false
        return config
    }

    private func apply() async {
        guard !stopped else { return }
        if #available(iOS 17.0, *) {
            store?.proxyConfigurations = []
            proxy?.stop(); proxy = nil
            guard supported, mode != "off" else {
                status = "default"; message = supported ? "已关闭优选，使用普通连接" : "此地址使用普通连接"
                return
            }
            let ip = selectedIP
            guard Self.validIP(ip) else {
                status = "default"; message = "暂无测速选出的 IP，使用普通连接；请测速择优"; return
            }
            let tunnel = CFConnectProxy(host: url.host!, port: UInt16(url.port ?? 443), ip: ip,
                                        onFallback: { [weak self] in
                self?.status = "fallback"; self?.message = "优选 IP 连接失败，已回退普通连接"
            })
            proxy = tunnel
            let port: UInt16? = await withCheckedContinuation { continuation in
                tunnel.start { continuation.resume(returning: $0) }
            }
            guard !stopped else { tunnel.stop(); return }
            if let port = port {
                store?.proxyConfigurations = [configuration(port: port)]
                status = "configured"; message = "后续新连接使用上次测速选择的 \(ip)；网络变化后请重新测速"
            } else {
                tunnel.stop(); proxy = nil
                status = "default"; message = "本机连接通道启动失败，使用普通连接"
            }
        } else {
            status = "unsupported"; message = "iOS 16 使用普通连接，优选需要 iOS 17 或以上"
        }
    }

    func handle(_ body: [String: Any]) async throws -> [String: Any] {
        let action = body["action"] as? String ?? "status"
        if action == "status" { return snapshot() }
        if action == "cancel" {
            guard busy else { return snapshot() }
            cancelRequested = true; measurementTask?.cancel()
            message = "正在停止测速…"; return snapshot()
        }
        guard supported else { throw failure("优选需要 iOS 17 或以上及 HTTPS 后端域名") }
        guard !busy, !stopped else { throw failure("正在处理，请稍后重试") }
        busy = true; cancelRequested = false
        defer { busy = false; measurementTask = nil }
        if action == "save" {
            let newMode = body["mode"] as? String ?? ""
            let newISP = body["isp"] as? String ?? ""
            guard ["off", "auto"].contains(newMode), ["ct", "cu", "cmcc"].contains(newISP) else {
                throw failure("优选配置无效")
            }
            let newIPs: [String]
            if newMode == "off" { newIPs = customIPs }
            else { newIPs = try PreferredIPRanking.parse(body["customIPs"] as? String ?? "", strict: true) }
            guard newIPs.count <= 128 else { throw failure("自定义候选超过 128 个，请减少后再测") }
            if isp != newISP { automaticIPs = []; fetchedAt = 0 }
            mode = newMode; isp = newISP; customIPs = newIPs
            let pool = PreferredIPRanking.merge(automatic: automaticIPs, custom: customIPs)
            if !pool.contains(where: { PreferredIPRanking.identity($0.ip) == PreferredIPRanking.identity(selectedIP) }) {
                selectedIP = ""; selectedAt = 0; selectedMilliseconds = nil
                await apply()
            }
            save()
            if mode == "off" {
                await apply(); busy = false; return snapshot()
            }
        } else if action != "refresh" && action != "test" { throw failure("不支持的操作") }
        guard mode != "off" else { throw failure("请先开启优选并保存") }
        let task = Task { try await selectBest(refresh: action == "refresh") }
        measurementTask = task
        if cancelRequested { task.cancel() }
        do { try await task.value }
        catch is CancellationError {
            measurements = measurements.map { item in
                var result = item
                if ["pending", "testing"].contains(result.state) { result.state = "cancelled" }
                return result
            }
            // 停止时不采用本轮部分结果，仍在候选池中的上次选择才可保留。
            let pool = PreferredIPRanking.merge(automatic: automaticIPs, custom: customIPs)
            if !pool.contains(where: { PreferredIPRanking.identity($0.ip) == PreferredIPRanking.identity(selectedIP) }) {
                selectedIP = ""; selectedAt = 0; selectedMilliseconds = nil
                await apply()
            }
            message = "已停止测速，未采用本轮部分结果；" + (selectedIP.isEmpty ? "使用普通连接" : "保留上次选择 \(selectedIP)")
            save()
        } catch {
            message = error.localizedDescription
            throw error
        }
        busy = false
        return snapshot()
    }

    private func selectBest(refresh: Bool) async throws {
        var warning = ""
        if refresh || automaticIPs.isEmpty || Date().timeIntervalSince1970 - fetchedAt >= 600 {
            message = "正在获取自动候选列表…"
            do {
                automaticIPs = try await fetchIPs(); fetchedAt = Date().timeIntervalSince1970; save()
            } catch {
                try Task.checkCancellation()
                warning = "自动列表获取失败，使用缓存及自定义 IP；"
            }
        }
        try Task.checkCancellation()
        let candidates = PreferredIPRanking.merge(automatic: automaticIPs, custom: customIPs)
        guard candidates.count <= 128 else { throw failure("合并后超过 128 个候选，请减少自定义 IP 后再测") }
        guard !candidates.isEmpty else { throw failure("没有有效候选，请添加自定义 IP 或重新获取列表") }
        measurements = candidates.map { PreferredIPMeasurement(ip: $0.ip, source: $0.source, state: "pending") }
        message = warning + "正在测速 0/\(candidates.count)…"
        try await withThrowingTaskGroup(of: PreferredIPMeasurement.self) { group in
            var next = min(3, candidates.count)
            for index in 0..<next {
                let candidate = candidates[index]
                measurements[index].state = "testing"
                group.addTask { try await self.measure(candidate) }
            }
            while let result = try await group.next() {
                try Task.checkCancellation()
                guard !stopped else { group.cancelAll(); throw CancellationError() }
                if let index = measurements.firstIndex(where: { $0.ip == result.ip }) { measurements[index] = result }
                let completed = measurements.filter { ["ok", "failed"].contains($0.state) }.count
                message = warning + "正在测速 \(completed)/\(candidates.count)…"
                if next < candidates.count {
                    let candidate = candidates[next]
                    measurements[next].state = "testing"
                    next += 1
                    group.addTask { try await self.measure(candidate) }
                }
            }
        }
        try Task.checkCancellation()
        guard !stopped else { throw CancellationError() }
        let best = PreferredIPRanking.best(measurements)
        selectedIP = best?.ip ?? ""
        selectedAt = best == nil ? 0 : Date().timeIntervalSince1970
        selectedMilliseconds = best?.milliseconds
        save()
        await apply()
        if let best = best {
            message = warning + "测速完成，最低平均耗时 \(Int(best.milliseconds!.rounded())) ms（2 次）：\(best.ip)。" + message
        } else { message = warning + "全部候选测试失败，已回退普通连接" }
    }

    private func measure(_ candidate: PreferredIPCandidate) async throws -> PreferredIPMeasurement {
        do {
            let first = try await probe(ip: candidate.ip)
            try Task.checkCancellation()
            let second = try await probe(ip: candidate.ip)
            return PreferredIPMeasurement(ip: candidate.ip, source: candidate.source, state: "ok",
                                          milliseconds: (first + second) / 2)
        } catch {
            try Task.checkCancellation()
            return PreferredIPMeasurement(ip: candidate.ip, source: candidate.source, state: "failed",
                                          error: error.localizedDescription)
        }
    }

    /// 两次测量各用独立、禁止回退的通道和 Session，防止连接复用或缓存影响排名。
    private func probe(ip: String) async throws -> Double {
        if let measureIP = measureIP { return try await measureIP(ip) }
        guard #available(iOS 17.0, *) else { throw failure("当前系统不支持优选") }
        try Task.checkCancellation()
        let tunnel = CFConnectProxy(host: url.host!, port: UInt16(url.port ?? 443), ip: ip, fallback: false)
        defer { tunnel.stop() }
        let port: UInt16? = await withCheckedContinuation { continuation in
            tunnel.start { continuation.resume(returning: $0) }
        }
        try Task.checkCancellation()
        guard let port = port else { throw failure("测试通道启动失败") }
        let config = URLSessionConfiguration.ephemeral
        config.proxyConfigurations = [configuration(port: port)]
        config.timeoutIntervalForRequest = 8
        config.timeoutIntervalForResource = 10
        config.httpCookieStorage = nil
        config.urlCache = nil
        let session = URLSession(configuration: config, delegate: NoRedirectDelegate(), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        var parts = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        parts.path = "/health"; parts.query = nil; parts.fragment = nil
        var request = URLRequest(url: parts.url!, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 8)
        request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        let start = DispatchTime.now().uptimeNanoseconds
        let (_, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw failure("测试失败：后端 /health 未返回 HTTP 200")
        }
        return Double(DispatchTime.now().uptimeNanoseconds - start) / 1_000_000
    }

    func fallbackAfterNavigationFailure() -> Bool {
        guard proxy != nil, status != "fallback" else { return false }
        if #available(iOS 17.0, *) { store?.proxyConfigurations = [] }
        proxy?.stop(); proxy = nil
        status = "fallback"; message = "优选连接失败，已回退普通连接"
        return true
    }

    func stop() {
        stopped = true; measurementTask?.cancel()
        if #available(iOS 17.0, *) { store?.proxyConfigurations = [] }
        proxy?.stop(); proxy = nil
    }

    private func failure(_ message: String) -> Error {
        NSError(domain: "HGhub.PreferredIP", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }

    private final class NoRedirectDelegate: NSObject, URLSessionTaskDelegate {
        func urlSession(_ session: URLSession, task: URLSessionTask,
                        willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                        completionHandler: @escaping (URLRequest?) -> Void) {
            completionHandler(nil)
        }
    }
}
