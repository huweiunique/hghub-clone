import Foundation
import Network

struct PreferredIPCandidate: Sendable {
    let ip: String
    let source: String
}

struct PreferredIPMeasurement: Sendable {
    let ip: String
    let source: String
    var state: String
    var milliseconds: Double?
    var error = ""

    var json: [String: Any] {
        var value: [String: Any] = ["ip": ip, "source": source, "state": state, "error": error]
        if let milliseconds = milliseconds { value["ms"] = milliseconds }
        return value
    }
}

enum PreferredIPRanking {
    static func identity(_ ip: String) -> Data? {
        IPv4Address(ip)?.rawValue ?? IPv6Address(ip)?.rawValue
    }

    static func parse(_ text: String, strict: Bool) throws -> [String] {
        let tokens = text.components(separatedBy: .newlines).flatMap { line in
            line.components(separatedBy: "#")[0].components(separatedBy:
                CharacterSet.whitespaces.union(CharacterSet(charactersIn: ",，")))
        }.filter { !$0.isEmpty }
        var ips: [String] = []
        var seen = Set<Data>()
        for token in tokens {
            guard let key = identity(token) else {
                if strict {
                    throw NSError(domain: "HGhub.PreferredIP", code: 1,
                                  userInfo: [NSLocalizedDescriptionKey: "无效 IP：\(token.prefix(60))；请只填 IP，不含协议和端口"])
                }
                continue
            }
            if seen.insert(key).inserted { ips.append(token) }
        }
        return ips
    }

    static func merge(automatic: [String], custom: [String]) -> [PreferredIPCandidate] {
        var candidates: [PreferredIPCandidate] = []
        var positions: [Data: Int] = [:]
        for (source, values) in [("自动", automatic), ("自定义", custom)] {
            for ip in values {
                guard let key = identity(ip) else { continue }
                if let index = positions[key] {
                    if candidates[index].source != source {
                        candidates[index] = PreferredIPCandidate(ip: candidates[index].ip, source: "自动＋自定义")
                    }
                } else {
                    positions[key] = candidates.count
                    candidates.append(PreferredIPCandidate(ip: ip, source: source))
                }
            }
        }
        return candidates
    }

    static func best(_ results: [PreferredIPMeasurement]) -> PreferredIPMeasurement? {
        // 相同耗时保持候选顺序；失败和未完成的候选永不参与选择。
        results.filter { $0.state == "ok" && ($0.milliseconds ?? -1) >= 0 && $0.milliseconds!.isFinite }
            .enumerated().min {
                if $0.element.milliseconds == $1.element.milliseconds { return $0.offset < $1.offset }
                return $0.element.milliseconds! < $1.element.milliseconds!
            }?.element
    }
}
