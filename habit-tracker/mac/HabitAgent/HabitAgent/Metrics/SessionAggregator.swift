// [review:need-review] PHASE-03/165
// summary: sums the per-file contributions into one aggregate per session id and turns it into the wire payload — counters, project, branch, models and the goal title, with every free-text field cut to the length the server accepts
import Foundation

enum SessionAggregator {
    /// A session is the sum over every file that carries its id (a subagent has its own file).
    static func sessions(from files: [String: FileScanState]) -> [String: SessionTotals] {
        var sessions: [String: SessionTotals] = [:]
        for state in files.values {
            for (id, part) in state.contributions {
                sessions[id, default: SessionTotals()].merge(part)
            }
        }
        return sessions
    }

    /// First line of `~/.claude/statusline/goals/<session_id>`, or nil when there is none.
    static func goalTitle(sessionID: String, goalsDirectory: URL) -> String? {
        // The id comes out of a file and names a file: a separator in it is not a session.
        guard !sessionID.isEmpty, !sessionID.contains("/"), sessionID != "..", sessionID != "." else { return nil }
        let url = goalsDirectory.appendingPathComponent(sessionID)
        guard let handle = try? FileHandle(forReadingFrom: url) else { return nil }
        defer { try? handle.close() }
        let head = (try? handle.read(upToCount: goalReadLimit)) ?? Data()
        let first = String(decoding: head, as: UTF8.self).split(separator: "\n", omittingEmptySubsequences: true).first
        let title = first.map { $0.trimmingCharacters(in: .whitespaces) } ?? ""
        return title.isEmpty ? nil : title
    }

    /// A goal is a line; a file that is not one is not read further.
    private static let goalReadLimit = 4_096
}

/// One session as the server stores it. Counters and identifiers; the `cwd` is a
/// directory name, never a file's content.
struct ClaudeSessionPayload: Encodable, Equatable {
    static let cwdLimit = 300
    static let branchLimit = 120
    static let goalLimit = 200
    static let modelsLimit = 200
    static let versionLimit = 20
    static let uidLimit = 64

    let sessionUID: String
    let cwd: String
    let gitBranch: String?
    let startedAt: Date
    let endedAt: Date
    let assistantTurns: Int
    let userTurns: Int
    let inputTokens: Int
    let outputTokens: Int
    let cacheReadTokens: Int
    let cacheCreationTokens: Int
    let models: String
    let goalTitle: String?
    let cliVersion: String?

    /// Nil for a session that has no moment: the server stores it by its start.
    init?(sessionID: String, totals: SessionTotals, goalTitle: String?) {
        guard let startedAt = totals.startedAt, let endedAt = totals.endedAt else { return nil }
        sessionUID = String(sessionID.prefix(Self.uidLimit))
        cwd = String((totals.cwd ?? "").prefix(Self.cwdLimit))
        gitBranch = totals.gitBranch.map { String($0.prefix(Self.branchLimit)) }
        self.startedAt = startedAt
        self.endedAt = endedAt
        assistantTurns = totals.assistantTurns
        userTurns = totals.userTurns
        inputTokens = totals.inputTokens
        outputTokens = totals.outputTokens
        cacheReadTokens = totals.cacheReadTokens
        cacheCreationTokens = totals.cacheCreationTokens
        models = Self.joined(totals.models)
        self.goalTitle = goalTitle.map { String($0.prefix(Self.goalLimit)) }
        cliVersion = totals.cliVersion.map { String($0.prefix(Self.versionLimit)) }
    }

    /// Whole model names that fit, never half of one.
    private static func joined(_ models: [String]) -> String {
        var text = ""
        for model in models {
            let next = text.isEmpty ? model : text + "," + model
            if next.count > modelsLimit { break }
            text = next
        }
        return text
    }
}

struct ClaudeSessionBatch: Encodable {
    let sessions: [ClaudeSessionPayload]
}

extension JSONEncoder {
    /// snake_case keys and ISO 8601 moments, as the server's schema spells them.
    static var claudeMetrics: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }
}
