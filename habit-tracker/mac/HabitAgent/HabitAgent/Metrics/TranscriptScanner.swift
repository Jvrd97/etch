// [review:need-review] PHASE-03/165
// summary: reads a chunk of a Claude Code transcript (.jsonl) into per-session counters — one assistant turn per message id, tokens from its usage, prompts without tool results as user turns — skips record types it does not know, keeps no message text, leaves a half-written last line for the next pass, and raises an error code when a non-empty file yields nothing readable (also, whatever else is readable, when a record type is unknown but its message names a turn's role)
import Foundation

/// What one session did, as numbers and identifiers. There is no field for text
/// on purpose: the transcripts hold code and private conversation, and a type
/// that cannot hold them cannot leak them.
struct SessionTotals: Codable, Equatable {
    var assistantTurns = 0
    var userTurns = 0
    var inputTokens = 0
    var outputTokens = 0
    var cacheReadTokens = 0
    var cacheCreationTokens = 0
    var startedAt: Date?
    var endedAt: Date?
    var cwd: String?
    var gitBranch: String?
    var cliVersion: String?
    /// Sorted and unique, so two passes over the same data compare equal.
    var models: [String] = []

    /// Widens the window and keeps the project, branch and version of the newest record.
    mutating func note(at moment: Date, cwd: String?, gitBranch: String?, cliVersion: String?) {
        if startedAt.map({ moment < $0 }) ?? true { startedAt = moment }
        if endedAt.map({ moment >= $0 }) ?? true {
            endedAt = moment
            self.cwd = cwd ?? self.cwd
            self.gitBranch = gitBranch ?? self.gitBranch
            self.cliVersion = cliVersion ?? self.cliVersion
        }
    }

    mutating func add(model: String) {
        guard !models.contains(model) else { return }
        models = (models + [model]).sorted()
    }

    /// Sums the part of the session another file holds (a subagent writes its own file).
    mutating func merge(_ other: SessionTotals) {
        assistantTurns += other.assistantTurns
        userTurns += other.userTurns
        inputTokens += other.inputTokens
        outputTokens += other.outputTokens
        cacheReadTokens += other.cacheReadTokens
        cacheCreationTokens += other.cacheCreationTokens
        other.models.forEach { add(model: $0) }
        guard let otherStart = other.startedAt, let otherEnd = other.endedAt else { return }
        let newer = endedAt.map { otherEnd >= $0 } ?? true
        if startedAt.map({ otherStart < $0 }) ?? true { startedAt = otherStart }
        if newer {
            endedAt = otherEnd
            cwd = other.cwd ?? cwd
            gitBranch = other.gitBranch ?? gitBranch
            cliVersion = other.cliVersion ?? cliVersion
        }
    }
}

/// Where the scan of one file stands. Persisted between passes, so the next pass
/// reads only what was appended after `offset`.
struct FileScanState: Codable, Equatable {
    /// Bytes consumed: the end of the last complete line.
    var offset: Int64 = 0
    var size: Int64 = 0
    var modified: Date?
    /// The last few message ids. One message is written once per content block,
    /// and the pass may end between two of its records.
    var recentMessageIDs: [String] = []
    /// Records that yielded a counter, and lines that looked like a turn but did not.
    var readable = 0
    var suspect = 0
    /// Records of an unknown `type` whose message names a turn's role: the CLI renamed
    /// what this scanner counts. Kept apart from `readable`, which the other, still known
    /// type (or the older part of a resumed session) keeps above zero.
    var renamed = 0
    /// What this file contributes to each session; a session is the sum over files.
    var contributions: [String: SessionTotals] = [:]

    var errorCode: String? { renamed > 0 || (readable == 0 && suspect > 0) ? TranscriptScanner.unreadableCode : nil }

    /// The file is gone: what it counted stays in the totals, but its signals no longer hold.
    mutating func clearSignals() {
        suspect = 0
        renamed = 0
    }
}

enum TranscriptScanner {
    /// A code and never a message: a log line with a path or a prompt in it is the leak.
    static let unreadableCode = "claude_transcript_unreadable"
    private static let recentIDWindow = 8
    private static let syntheticModel = "<synthetic>"
    /// Known record types that hold a message with a role but are not turns (the request blob).
    private static let bookkeepingTypesWithRole: Set<String> = ["api-request-blob"]
    private static let turnMarkers = ["\"assistant\"", "\"user\""].map { Array($0.utf8) }
    private static let newline = UInt8(ascii: "\n")

    /// Consumes the complete lines of `chunk` and advances `state.offset` past them.
    /// A last line without its newline is still being written and stays unread.
    static func scan(_ chunk: Data, into state: inout FileScanState) {
        var clock = TimestampParser()
        chunk.withUnsafeBytes { (raw: UnsafeRawBufferPointer) in
            guard let base = raw.baseAddress else { return }
            let end = raw.count
            var lineStart = 0
            while lineStart < end,
                  let found = memchr(base + lineStart, Int32(newline), end - lineStart) {
                let lineEnd = base.distance(to: found)
                read(UnsafeRawBufferPointer(start: base + lineStart, count: lineEnd - lineStart), into: &state, clock: &clock)
                lineStart = lineEnd + 1
            }
            state.offset += Int64(lineStart)
        }
    }

    private static func read(_ line: UnsafeRawBufferPointer, into state: inout FileScanState, clock: inout TimestampParser) {
        let trimmed = trim(line)
        guard !trimmed.isEmpty else { return }
        guard trimmed.first == UInt8(ascii: "{"), trimmed.last == UInt8(ascii: "}") else {
            state.suspect += 1
            return
        }
        // Most lines are request blobs and bookkeeping; only a line that names a
        // role is worth decoding.
        guard turnMarkers.contains(where: { contains(trimmed, $0) }) else { return }
        guard let record = try? JSONSerialization.jsonObject(with: Data(trimmed)) as? [String: Any] else {
            state.suspect += 1
            return
        }
        switch record["type"] as? String {
        case "assistant": readAssistant(record, into: &state, clock: &clock)
        case "user": readUser(record, into: &state, clock: &clock)
        default: noteUnknownType(of: record, into: &state)
        }
    }

    /// An unknown `type` is skipped quietly, unless the record carries a turn's role:
    /// then the CLI renamed what this scanner counts, and the file must not read as clean,
    /// whatever else in it is still readable.
    private static func noteUnknownType(of record: [String: Any], into state: inout FileScanState) {
        if let type = record["type"] as? String, bookkeepingTypesWithRole.contains(type) { return }
        guard let role = (record["message"] as? [String: Any])?["role"] as? String,
              role == "assistant" || role == "user" else { return }
        state.renamed += 1
    }

    private static func readAssistant(_ record: [String: Any], into state: inout FileScanState, clock: inout TimestampParser) {
        guard let identity = identity(of: record, clock: &clock),
              let message = record["message"] as? [String: Any],
              let usage = message["usage"] as? [String: Any],
              usage["output_tokens"] is Int || usage["input_tokens"] is Int else {
            state.suspect += 1
            return
        }
        state.readable += 1
        var totals = state.contributions[identity.session] ?? SessionTotals()
        totals.note(at: identity.moment, cwd: record["cwd"] as? String, gitBranch: record["gitBranch"] as? String,
                    cliVersion: record["version"] as? String)
        defer { state.contributions[identity.session] = totals }

        let model = message["model"] as? String
        if model == syntheticModel { return }
        if let id = message["id"] as? String {
            if state.recentMessageIDs.contains(id) { return }
            state.recentMessageIDs = Array((state.recentMessageIDs + [id]).suffix(recentIDWindow))
        }
        totals.assistantTurns += 1
        totals.inputTokens += usage["input_tokens"] as? Int ?? 0
        totals.outputTokens += usage["output_tokens"] as? Int ?? 0
        totals.cacheReadTokens += usage["cache_read_input_tokens"] as? Int ?? 0
        totals.cacheCreationTokens += usage["cache_creation_input_tokens"] as? Int ?? 0
        if let model { totals.add(model: model) }
    }

    private static func readUser(_ record: [String: Any], into state: inout FileScanState, clock: inout TimestampParser) {
        guard let identity = identity(of: record, clock: &clock), record["message"] is [String: Any] else {
            state.suspect += 1
            return
        }
        state.readable += 1
        var totals = state.contributions[identity.session] ?? SessionTotals()
        totals.note(at: identity.moment, cwd: record["cwd"] as? String, gitBranch: record["gitBranch"] as? String,
                    cliVersion: record["version"] as? String)
        if isPrompt(record) { totals.userTurns += 1 }
        state.contributions[identity.session] = totals
    }

    /// A person's prompt: not a subagent's, not injected metadata, not a tool result.
    private static func isPrompt(_ record: [String: Any]) -> Bool {
        if record["isSidechain"] as? Bool == true || record["isMeta"] as? Bool == true { return false }
        guard let content = (record["message"] as? [String: Any])?["content"] else { return false }
        if content is String { return true }
        guard let blocks = content as? [[String: Any]] else { return false }
        return !blocks.isEmpty && !blocks.contains { $0["type"] as? String == "tool_result" }
    }

    private static func identity(of record: [String: Any], clock: inout TimestampParser) -> (session: String, moment: Date)? {
        guard let session = record["sessionId"] as? String, !session.isEmpty,
              let stamp = record["timestamp"] as? String, let moment = clock.parse(stamp) else { return nil }
        return (session, moment)
    }

    private static func trim(_ line: UnsafeRawBufferPointer) -> UnsafeRawBufferPointer {
        var start = 0
        var end = line.count
        while start < end, isSpace(line[start]) { start += 1 }
        while end > start, isSpace(line[end - 1]) { end -= 1 }
        guard let base = line.baseAddress else { return line }
        return UnsafeRawBufferPointer(start: base + start, count: end - start)
    }

    private static func isSpace(_ byte: UInt8) -> Bool { byte == 0x20 || byte == 0x09 || byte == 0x0D }

    private static func contains(_ haystack: UnsafeRawBufferPointer, _ needle: [UInt8]) -> Bool {
        guard let base = haystack.baseAddress else { return false }
        return needle.withUnsafeBytes { memmem(base, haystack.count, $0.baseAddress, $0.count) != nil }
    }
}

private extension UnsafeRawPointer {
    func distance(to other: UnsafeMutableRawPointer) -> Int { UnsafeRawPointer(other) - self }
}

/// `2026-10-25T14:01:46.256Z` and the same without fractions. One formatter per scan: they are slow to make.
struct TimestampParser {
    private let fractional: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()
    private let plain = ISO8601DateFormatter()

    mutating func parse(_ text: String) -> Date? {
        fractional.date(from: text) ?? plain.date(from: text)
    }
}
