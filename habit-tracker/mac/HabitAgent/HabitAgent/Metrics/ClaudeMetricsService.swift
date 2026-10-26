// [review:need-review] PHASE-03/165
// summary: the pass that turns ~/.claude/projects into session aggregates — reads only files whose size or mtime moved, and only past the saved offset, keeps the scan state on disk between launches, forgets transcripts deleted from disk (their totals stay, their error signals go), and sends the sessions that changed since the last successful send; failures leave them to the next pass (a file that could not be read keeps its old size and mtime, so it is read again). Runs at utility priority and yields between files
import Foundation

/// The last thing sent for a session; a session is sent again only when this differs.
struct SentMark: Codable, Equatable {
    var totals: SessionTotals
    var goalTitle: String?
}

struct ClaudeMetricsState: Codable, Equatable {
    /// Keyed by absolute path. A file the CLI has pruned stays here on purpose:
    /// dropping it would shrink the sessions it fed and restate them smaller.
    var files: [String: FileScanState] = [:]
    var sent: [String: SentMark] = [:]
}

actor ClaudeMetricsService {
    struct Report: Equatable {
        var filesRead = 0
        var bytesRead: Int64 = 0
        var sessionsSent = 0
    }

    typealias Send = ([ClaudeSessionPayload]) async throws -> Void

    static let passInterval: TimeInterval = 300
    /// The server refuses more per request (`MAX_CLAUDE_SESSIONS_BATCH`).
    static let batchSize = 200
    static let rejectedCode = "claude_session_rejected"
    private static let firstChunkBytes = 16 * 1024 * 1024
    private static let largestChunkBytes = 512 * 1024 * 1024

    private let projectsDirectory: URL
    private let goalsDirectory: URL
    private let stateURL: URL?
    private let send: Send
    private var state: ClaudeMetricsState
    private var task: Task<Void, Never>?
    private var isPassing = false
    private var pushErrorCode: String?
    private var readErrorCode: String?

    init(projectsDirectory: URL, goalsDirectory: URL, stateURL: URL?, send: @escaping Send) {
        self.projectsDirectory = projectsDirectory
        self.goalsDirectory = goalsDirectory
        self.stateURL = stateURL
        self.send = send
        state = stateURL.flatMap { try? JSONDecoder().decode(ClaudeMetricsState.self, from: Data(contentsOf: $0)) } ?? ClaudeMetricsState()
    }

    static func live(
        serverAddress: @escaping @MainActor @Sendable () -> String?,
        apiKey: @escaping @Sendable () -> String?
    ) -> ClaudeMetricsService {
        let claude = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".claude")
        return ClaudeMetricsService(
            projectsDirectory: claude.appendingPathComponent("projects"),
            goalsDirectory: claude.appendingPathComponent("statusline/goals"),
            stateURL: AgentPaths.directory.appendingPathComponent("claude-metrics.json"),
            send: sender(serverAddress: serverAddress, apiKey: apiKey)
        )
    }

    /// The address lives on the main actor (`ActivitySampler`): it is read there, as a snapshot,
    /// before the request leaves this actor.
    static func sender(
        serverAddress: @escaping @MainActor @Sendable () -> String?,
        apiKey: @escaping @Sendable () -> String?,
        session: URLSession = AgentAPIClient.diskFreeSession
    ) -> Send {
        { sessions in
            guard let address = await serverAddress(), let key = apiKey() else { throw URLError(.userAuthenticationRequired) }
            try await ClaudeSessionsAPI(serverAddress: address, apiKey: key, session: session).send(sessions)
        }
    }

    /// A code for the heartbeat's `last_error`, or nil. Unreadable transcripts come first:
    /// they are the quiet failure, where the metric would drop to zero unnoticed.
    var errorCode: String? {
        state.files.values.contains { $0.errorCode != nil } ? TranscriptScanner.unreadableCode : readErrorCode ?? pushErrorCode
    }

    func start() {
        guard task == nil else { return }
        // Utility: the first pass walks gigabytes and must not compete with the app the person is using.
        task = Task(priority: .utility) { [weak self] in
            while !Task.isCancelled {
                _ = await self?.runPass()
                try? await Task.sleep(nanoseconds: UInt64(Self.passInterval * 1_000_000_000))
            }
        }
    }

    func stop() {
        task?.cancel()
        task = nil
    }

    @discardableResult
    func runPass() async -> Report {
        guard !isPassing else { return Report() }
        isPassing = true
        defer { isPassing = false }
        var report = Report()
        await scanFiles(into: &report)
        await push(into: &report)
        save()
        return report
    }

    // MARK: scanning

    private func scanFiles(into report: inout Report) async {
        readErrorCode = nil
        let keys: [URLResourceKey] = [.contentModificationDateKey, .fileSizeKey, .isRegularFileKey]
        guard let walker = FileManager.default.enumerator(at: projectsDirectory, includingPropertiesForKeys: keys) else { return }
        // `nextObject()`, not a for-in: the enumerator's iterator is unavailable across an `await`.
        var seen: Set<String> = []
        while let url = walker.nextObject() as? URL {
            guard url.pathExtension == "jsonl",
                  let values = try? url.resourceValues(forKeys: Set(keys)), values.isRegularFile == true,
                  let size = values.fileSize.map(Int64.init), let modified = values.contentModificationDate else { continue }
            seen.insert(url.path)
            var file = state.files[url.path] ?? FileScanState()
            guard size != file.size || modified != file.modified else { continue }
            // Shorter than what was consumed: the file was rewritten, so its old
            // contribution is void and it is read again from the top.
            if size < file.offset { file = FileScanState() }
            do {
                report.bytesRead += try readTail(of: url, from: file.offset, into: &file)
                // Size and mtime are recorded only for a read that finished: otherwise a finished
                // session would look unchanged and never be read again.
                file.size = size
                file.modified = modified
            } catch {
                readErrorCode = AgentLog.code(of: error)
            }
            state.files[url.path] = file
            report.filesRead += 1
            await Task.yield()
        }
        forgetDeletedFiles(keeping: seen)
    }

    /// A deleted transcript would hold `claude_transcript_unreadable` forever. One that counted
    /// nothing is dropped; one that counted something keeps its totals (the server already has
    /// them, and a shrinking session would overwrite them) and loses only its error signals.
    private func forgetDeletedFiles(keeping seen: Set<String>) {
        for (path, var file) in state.files where !seen.contains(path) {
            if file.contributions.isEmpty {
                state.files[path] = nil
            } else if file.errorCode != nil {
                file.clearSignals()
                state.files[path] = file
            }
        }
    }

    /// Reads from `offset` in chunks; a chunk with no newline is doubled until its line fits.
    /// What was consumed before a failure stays in `file`, so the retry resumes from there.
    private func readTail(of url: URL, from offset: Int64, into file: inout FileScanState) throws -> Int64 {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var chunkBytes = Self.firstChunkBytes
        var total: Int64 = 0
        while true {
            let before = file.offset
            try handle.seek(toOffset: UInt64(before))
            guard let chunk = try handle.read(upToCount: chunkBytes), !chunk.isEmpty else { break }
            total += Int64(chunk.count)
            TranscriptScanner.scan(chunk, into: &file)
            if file.offset == before {
                // No complete line: the tail is still being written, or one line outgrew the chunk.
                if chunk.count < chunkBytes || chunkBytes >= Self.largestChunkBytes { break }
                chunkBytes *= 2
            }
        }
        return total
    }

    // MARK: sending

    private func push(into report: inout Report) async {
        let sessions = SessionAggregator.sessions(from: state.files)
        var pending: [(id: String, mark: SentMark, payload: ClaudeSessionPayload)] = []
        for (id, totals) in sessions {
            let mark = SentMark(totals: totals, goalTitle: SessionAggregator.goalTitle(sessionID: id, goalsDirectory: goalsDirectory))
            guard state.sent[id] != mark,
                  let payload = ClaudeSessionPayload(sessionID: id, totals: totals, goalTitle: mark.goalTitle) else { continue }
            pending.append((id, mark, payload))
        }
        // The newest first: the day on screen matters more than a year-old history.
        pending.sort { $0.payload.endedAt > $1.payload.endedAt }
        pushErrorCode = nil

        for start in stride(from: 0, to: pending.count, by: Self.batchSize) {
            let batch = Array(pending[start..<min(start + Self.batchSize, pending.count)])
            do {
                try await send(batch.map(\.payload))
                batch.forEach { state.sent[$0.id] = $0.mark }
                report.sessionsSent += batch.count
            } catch ClaudeSessionsAPIError.rejected {
                await sendOneByOne(batch, into: &report)
            } catch {
                pushErrorCode = AgentLog.code(of: error)
                return
            }
        }
    }

    /// A batch the server refused whole holds a session it will never take; send them apart
    /// and stop retrying the one that is refused, until it changes.
    private func sendOneByOne(_ batch: [(id: String, mark: SentMark, payload: ClaudeSessionPayload)], into report: inout Report) async {
        for item in batch {
            do {
                try await send([item.payload])
                report.sessionsSent += 1
            } catch ClaudeSessionsAPIError.rejected {
                pushErrorCode = Self.rejectedCode
            } catch {
                pushErrorCode = AgentLog.code(of: error)
                return
            }
            state.sent[item.id] = item.mark
        }
    }

    private func save() {
        guard let stateURL else { return }
        do {
            // The state says which projects the person worked in: the directory is owner-only, as the queue's is.
            try FileManager.default.createDirectory(
                at: stateURL.deletingLastPathComponent(), withIntermediateDirectories: true,
                attributes: [.posixPermissions: AgentPaths.directoryPermissions]
            )
            try JSONEncoder().encode(state).write(to: stateURL, options: .atomic)
        } catch {
            pushErrorCode = AgentLog.code(of: error)
        }
    }
}
