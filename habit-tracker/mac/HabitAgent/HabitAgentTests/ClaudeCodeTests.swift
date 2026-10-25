// [review:need-review] PHASE-03/165
// summary: proves the Claude Code transcript scanner on .jsonl fixtures — turns and tokens counted once per message, unknown record types skipped silently, an error code (not silence) when a non-empty file yields nothing readable, resuming from a saved offset without re-reading, a half-written last line left for the next pass — and that the session payload carries counters only
import XCTest
@testable import HabitAgent

final class ClaudeCodeTests: XCTestCase {
    private let sessionID = "aaaaaaaa-0000-4000-8000-000000000001"

    private func fixture(_ name: String) throws -> Data {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: name, withExtension: "jsonl"), "fixture \(name)")
        return try Data(contentsOf: url)
    }

    private func scanned(_ name: String) throws -> (FileScanState, Data) {
        let data = try fixture(name)
        var state = FileScanState()
        TranscriptScanner.scan(data, into: &state)
        return (state, data)
    }

    // MARK: counting

    func testCountsTurnsAndTokensOncePerMessage() throws {
        let (state, _) = try scanned("session_basic")
        let totals = try XCTUnwrap(state.contributions[sessionID])

        // msg_01 is written twice (one record per content block) and counts once.
        XCTAssertEqual(totals.assistantTurns, 2)
        // A string prompt and a text-block prompt are turns; a tool_result is not.
        XCTAssertEqual(totals.userTurns, 2)
        XCTAssertEqual(totals.inputTokens, 11)
        XCTAssertEqual(totals.outputTokens, 22)
        XCTAssertEqual(totals.cacheReadTokens, 103)
        XCTAssertEqual(totals.cacheCreationTokens, 9)
    }

    func testTakesWindowProjectBranchAndModelsFromTheRecords() throws {
        let (state, _) = try scanned("session_basic")
        let totals = try XCTUnwrap(state.contributions[sessionID])

        XCTAssertEqual(totals.cwd, "/Users/me/Projects/talvior")
        // The branch and version are the latest ones seen, not the first.
        XCTAssertEqual(totals.gitBranch, "swarm/165")
        XCTAssertEqual(totals.cliVersion, "2.1.310")
        XCTAssertEqual(totals.models, ["claude-opus-5-5", "claude-sonnet-5-5"])
        XCTAssertEqual(totals.startedAt, ISO8601DateFormatter().date(from: "2026-10-25T10:00:00Z"))
        XCTAssertEqual(totals.endedAt, ISO8601DateFormatter().date(from: "2026-10-25T10:05:00Z"))
    }

    func testUnknownRecordTypesAreSkippedWithoutAnError() throws {
        let (state, _) = try scanned("session_basic")

        XCTAssertNil(state.errorCode)
        XCTAssertGreaterThan(state.readable, 0)
    }

    func testAFileOfBookkeepingRecordsOnlyIsNotAnError() throws {
        let (state, _) = try scanned("bookkeeping_only")

        XCTAssertTrue(state.contributions.isEmpty)
        XCTAssertNil(state.errorCode)
    }

    // MARK: format drift

    func testANonEmptyFileWithNothingReadableRaisesAnErrorCode() throws {
        let (state, _) = try scanned("drifted")

        XCTAssertTrue(state.contributions.isEmpty)
        XCTAssertEqual(state.errorCode, TranscriptScanner.unreadableCode)
    }

    func testARenamedTurnTypeRaisesTheCodeInsteadOfPassingSilently() throws {
        // `type` is "turn" and the message still says assistant/user: the CLI renamed what is counted.
        let (state, _) = try scanned("turn_type_drift")

        XCTAssertTrue(state.contributions.isEmpty)
        XCTAssertEqual(state.errorCode, TranscriptScanner.unreadableCode)
    }

    func testARenamedAssistantTypeRaisesTheCodeWhileUserRecordsStayReadable() throws {
        // Only `assistant` was renamed: user records keep `readable` above zero, yet every turn and token is lost.
        let (state, _) = try scanned("assistant_type_drift")

        XCTAssertGreaterThan(state.readable, 0)
        XCTAssertEqual(state.contributions[sessionID]?.assistantTurns, 0)
        XCTAssertEqual(state.errorCode, TranscriptScanner.unreadableCode)
    }

    func testAResumedSessionAppendedByARenamingCLIRaisesTheCode() throws {
        var state = FileScanState()
        TranscriptScanner.scan(try fixture("session_basic"), into: &state)
        XCTAssertNil(state.errorCode)

        TranscriptScanner.scan(try fixture("assistant_type_drift"), into: &state)

        XCTAssertEqual(state.errorCode, TranscriptScanner.unreadableCode)
    }

    func testTheRequestBlobIsBookkeepingNotDrift() {
        let blob = #"{"type":"api-request-blob","message":{"role":"user","content":"x"}}"# + "\n"
        var state = FileScanState()

        TranscriptScanner.scan(Data(blob.utf8), into: &state)

        XCTAssertNil(state.errorCode)
    }

    func testGarbageLinesRaiseTheSameCode() throws {
        let (state, _) = try scanned("garbage")

        XCTAssertEqual(state.errorCode, TranscriptScanner.unreadableCode)
    }

    func testTheErrorCodeNamesNoPathAndNoContent() {
        XCTAssertFalse(TranscriptScanner.unreadableCode.contains("/"))
        XCTAssertFalse(TranscriptScanner.unreadableCode.contains(" "))
    }

    // MARK: resuming

    func testScanningTheAppendedTailEqualsScanningTheWhole() throws {
        let first = try fixture("session_basic")
        let more = try fixture("session_appended")

        var whole = FileScanState()
        TranscriptScanner.scan(first + more, into: &whole)

        var resumed = FileScanState()
        TranscriptScanner.scan(first, into: &resumed)
        let offset = Int(resumed.offset)
        XCTAssertEqual(offset, first.count)
        TranscriptScanner.scan((first + more).dropFirst(offset), into: &resumed)

        XCTAssertEqual(resumed.contributions, whole.contributions)
        XCTAssertEqual(resumed.offset, Int64(first.count + more.count))
        XCTAssertEqual(resumed.contributions[sessionID]?.assistantTurns, 3)
    }

    func testAMessageSplitAcrossPassesIsStillCountedOnce() throws {
        let data = try fixture("session_basic")
        // Pass one ends between the two records of msg_01 (lines 3 and 4).
        let newline = UInt8(ascii: "\n")
        let cut = data.indices.filter { data[$0] == newline }[2] + 1

        var state = FileScanState()
        TranscriptScanner.scan(data.prefix(cut), into: &state)
        TranscriptScanner.scan(data.dropFirst(cut), into: &state)

        XCTAssertEqual(state.contributions[sessionID]?.assistantTurns, 2)
        XCTAssertEqual(state.contributions[sessionID]?.inputTokens, 11)
    }

    func testAHalfWrittenLastLineIsLeftForTheNextPass() throws {
        let data = try fixture("session_appended")
        let cut = data.count - 20
        var state = FileScanState()

        TranscriptScanner.scan(data.prefix(cut), into: &state)
        XCTAssertEqual(state.offset, 0, "no complete line yet, so nothing is consumed")
        XCTAssertTrue(state.contributions.isEmpty)
        XCTAssertNil(state.errorCode, "a line still being written is not drift")

        TranscriptScanner.scan(data, into: &state)
        XCTAssertEqual(state.contributions[sessionID]?.assistantTurns, 1)
    }

    // MARK: payload

    func testThePayloadCarriesCountersAndNothingElse() throws {
        let (state, _) = try scanned("session_basic")
        let aggregate = try XCTUnwrap(ClaudeSessionPayload(
            sessionID: sessionID,
            totals: try XCTUnwrap(state.contributions[sessionID]),
            goalTitle: "Метрики Claude Code"
        ))

        let body = try JSONEncoder.claudeMetrics.encode(ClaudeSessionBatch(sessions: [aggregate]))
        let text = try XCTUnwrap(String(data: body, encoding: .utf8))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
        let session = try XCTUnwrap((object["sessions"] as? [[String: Any]])?.first)

        XCTAssertFalse(text.contains("SECRET"))
        XCTAssertEqual(
            Set(session.keys),
            ["session_uid", "cwd", "git_branch", "started_at", "ended_at", "assistant_turns", "user_turns",
             "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "models",
             "goal_title", "cli_version"]
        )
        XCTAssertEqual(session["session_uid"] as? String, sessionID)
        XCTAssertEqual(session["models"] as? String, "claude-opus-5-5,claude-sonnet-5-5")
    }

    func testLongFieldsAreCutToWhatTheServerAccepts() {
        var totals = SessionTotals()
        totals.cwd = String(repeating: "d", count: 500)
        totals.startedAt = Date(timeIntervalSince1970: 1_000)
        totals.endedAt = Date(timeIntervalSince1970: 2_000)

        let payload = ClaudeSessionPayload(
            sessionID: sessionID, totals: totals, goalTitle: String(repeating: "g", count: 500)
        )

        XCTAssertEqual(payload?.cwd.count, ClaudeSessionPayload.cwdLimit)
        XCTAssertEqual(payload?.goalTitle?.count, ClaudeSessionPayload.goalLimit)
    }

    func testASessionWithoutAnyTimestampHasNoPayload() {
        XCTAssertNil(ClaudeSessionPayload(sessionID: sessionID, totals: SessionTotals(), goalTitle: nil))
    }
}

final class ClaudeMetricsServiceTests: XCTestCase {
    private var root: URL!
    private var projects: URL!
    private var goals: URL!
    private var stateURL: URL!
    private var sent: SentBatches!

    /// Batches the fake server received, in order.
    actor SentBatches {
        private(set) var batches: [[ClaudeSessionPayload]] = []
        var failure: Error?
        func record(_ batch: [ClaudeSessionPayload]) throws {
            if let failure { throw failure }
            batches.append(batch)
        }
        func fail(with error: Error?) { failure = error }
    }

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("claude-metrics-\(UUID().uuidString)")
        projects = root.appendingPathComponent("projects/-Users-me-talvior")
        goals = root.appendingPathComponent("goals")
        stateURL = root.appendingPathComponent("state.json")
        try FileManager.default.createDirectory(at: projects, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: goals, withIntermediateDirectories: true)
        sent = SentBatches()
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: root)
    }

    private func makeService() -> ClaudeMetricsService {
        let sent = self.sent!
        return ClaudeMetricsService(
            projectsDirectory: root.appendingPathComponent("projects"),
            goalsDirectory: goals,
            stateURL: stateURL
        ) { try await sent.record($0) }
    }

    private func install(_ fixture: String, as name: String = "a.jsonl", append: Bool = false) throws {
        let bundle = Bundle(for: Self.self)
        let data = try Data(contentsOf: XCTUnwrap(bundle.url(forResource: fixture, withExtension: "jsonl")))
        let target = projects.appendingPathComponent(name)
        if append, let handle = try? FileHandle(forWritingTo: target) {
            try handle.seekToEnd()
            try handle.write(contentsOf: data)
            try handle.close()
        } else {
            try data.write(to: target)
        }
    }

    private let sessionID = "aaaaaaaa-0000-4000-8000-000000000001"

    func testASessionIsSentOnceWithItsGoalTitle() async throws {
        try install("session_basic")
        try "Метрики Claude Code\nвторая строка".write(to: goals.appendingPathComponent(sessionID), atomically: true, encoding: .utf8)
        let service = makeService()

        let report = await service.runPass()

        XCTAssertEqual(report.sessionsSent, 1)
        let batches = await sent.batches
        XCTAssertEqual(batches.first?.first?.goalTitle, "Метрики Claude Code")
        XCTAssertEqual(batches.first?.first?.assistantTurns, 2)
    }

    func testAnUnchangedPassReadsNothingAndSendsNothing() async throws {
        try install("session_basic")
        let service = makeService()
        await service.runPass()

        let second = await service.runPass()

        XCTAssertEqual(second, ClaudeMetricsService.Report())
        let batches = await sent.batches
        XCTAssertEqual(batches.count, 1)
    }

    func testAppendedLinesAreReadFromTheSavedOffsetAndRestateTheSameSession() async throws {
        try install("session_basic")
        let service = makeService()
        let firstReport = await service.runPass()
        try install("session_appended", append: true)

        let second = await service.runPass()

        XCTAssertEqual(second.filesRead, 1)
        let appendedBytes = try Data(contentsOf: XCTUnwrap(Bundle(for: Self.self).url(forResource: "session_appended", withExtension: "jsonl"))).count
        XCTAssertEqual(second.bytesRead, Int64(appendedBytes), "only the tail is read, not the whole file")
        XCTAssertLessThan(second.bytesRead, firstReport.bytesRead)
        let batches = await sent.batches
        XCTAssertEqual(batches.count, 2)
        XCTAssertEqual(batches[1].first?.sessionUID, batches[0].first?.sessionUID)
        XCTAssertEqual(batches[1].first?.assistantTurns, 3)
    }

    func testTheScanStateSurvivesARestart() async throws {
        try install("session_basic")
        await makeService().runPass()

        let report = await makeService().runPass()

        XCTAssertEqual(report, ClaudeMetricsService.Report())
    }

    func testAFailedSendIsRetriedByTheNextPass() async throws {
        try install("session_basic")
        let service = makeService()
        await sent.fail(with: URLError(.notConnectedToInternet))

        let failed = await service.runPass()
        let code = await service.errorCode
        XCTAssertEqual(failed.sessionsSent, 0)
        XCTAssertEqual(code, "NSURLErrorDomain -1009")

        await sent.fail(with: nil)
        let retried = await service.runPass()
        XCTAssertEqual(retried.sessionsSent, 1)
        let recovered = await service.errorCode
        XCTAssertNil(recovered)
    }

    func testAnUnreadableTranscriptSurfacesAsTheErrorCode() async throws {
        try install("drifted")
        let service = makeService()

        await service.runPass()

        let code = await service.errorCode
        XCTAssertEqual(code, TranscriptScanner.unreadableCode)
    }

    func testADeletedFileNoLongerHoldsTheErrorCodeNorLosesItsSession() async throws {
        try install("session_basic", as: "ok.jsonl")
        try install("assistant_type_drift", as: "renamed.jsonl")
        let service = makeService()
        await service.runPass()
        let raised = await service.errorCode
        XCTAssertEqual(raised, TranscriptScanner.unreadableCode)

        try FileManager.default.removeItem(at: projects.appendingPathComponent("renamed.jsonl"))
        await service.runPass()

        let cleared = await service.errorCode
        XCTAssertNil(cleared)
        let batches = await sent.batches
        XCTAssertEqual(batches.last?.first?.assistantTurns, 2, "history of a deleted transcript stays in the totals")
    }

    func testTwoFilesOfOneSessionAreSummed() async throws {
        try install("session_basic", as: "main.jsonl")
        try install("session_appended", as: "sub.jsonl")
        let service = makeService()

        await service.runPass()

        let batches = await sent.batches
        XCTAssertEqual(batches.first?.count, 1)
        XCTAssertEqual(batches.first?.first?.assistantTurns, 3)
    }

    func testARefusedSessionDoesNotBlockTheOthersNorRepeat() async throws {
        try install("session_basic")
        await sent.fail(with: ClaudeSessionsAPIError.rejected)
        let service = makeService()

        await service.runPass()
        let code = await service.errorCode
        XCTAssertEqual(code, ClaudeMetricsService.rejectedCode)

        await sent.fail(with: nil)
        let again = await service.runPass()
        XCTAssertEqual(again.sessionsSent, 0, "the refused session waits until it changes")
    }

    func testASessionThatCannotBeReadIsRetriedAndRaisesTheCode() async throws {
        try install("session_basic")
        let file = projects.appendingPathComponent("a.jsonl")
        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: file.path)
        let service = makeService()

        let failed = await service.runPass()
        let code = await service.errorCode
        XCTAssertEqual(failed.sessionsSent, 0)
        XCTAssertNotNil(code)
        XCTAssertFalse(code?.contains("/") ?? false, "a code, not a path")

        // Size and mtime were not recorded, so the finished file is read once it can be.
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: file.path)
        let retried = await service.runPass()
        XCTAssertEqual(retried.sessionsSent, 1)
        let recovered = await service.errorCode
        XCTAssertNil(recovered)
    }

    func testTheStateDirectoryIsCreatedOwnerOnly() async throws {
        try install("session_basic")
        let directory = root.appendingPathComponent("agent-support")
        let service = ClaudeMetricsService(
            projectsDirectory: root.appendingPathComponent("projects"),
            goalsDirectory: goals,
            stateURL: directory.appendingPathComponent("claude-metrics.json")
        ) { _ in }

        await service.runPass()

        let attributes = try FileManager.default.attributesOfItem(atPath: directory.path)
        XCTAssertEqual(attributes[.posixPermissions] as? Int, AgentPaths.directoryPermissions)
        XCTAssertTrue(FileManager.default.fileExists(atPath: directory.appendingPathComponent("claude-metrics.json").path))
    }

    func testThePassRunsAtUtilityPriority() async throws {
        try install("session_basic")
        let seen = PriorityBox()
        let service = ClaudeMetricsService(
            projectsDirectory: root.appendingPathComponent("projects"),
            goalsDirectory: goals,
            stateURL: nil
        ) { _ in await seen.record(Task.currentPriority) }

        await service.start()
        for _ in 0..<100 where await seen.value == nil { try await Task.sleep(nanoseconds: 50_000_000) }
        await service.stop()

        let priority = await seen.value
        XCTAssertEqual(priority, .utility)
    }

    actor PriorityBox {
        private(set) var value: TaskPriority?
        func record(_ priority: TaskPriority) { value = priority }
    }

    // MARK: the sender (address on the main actor)

    private func timedPayload() -> ClaudeSessionPayload? {
        var totals = SessionTotals()
        totals.startedAt = Date(timeIntervalSince1970: 1_000)
        totals.endedAt = Date(timeIntervalSince1970: 2_000)
        return ClaudeSessionPayload(sessionID: sessionID, totals: totals, goalTitle: nil)
    }

    @MainActor
    final class AddressBook {
        var address: String? = "https://habit.example"
        private(set) var readOnMain: [Bool] = []
        func read() -> String? {
            readOnMain.append(Thread.isMainThread)
            return address
        }
    }

    func testTheSenderReadsTheMainActorAddressOnTheMainActorAndPostsTheBatch() async throws {
        let book = await AddressBook()
        ClaudeStubProtocol.handler = { request in (request, 201) }
        let send = ClaudeMetricsService.sender(
            serverAddress: { book.read() }, apiKey: { "secret" }, session: ClaudeStubProtocol.session()
        )
        let payload = try XCTUnwrap(timedPayload())

        // Called from a plain task, as the service's actor does: not from the main thread.
        try await Task.detached { try await send([payload]) }.value

        let reads = await book.readOnMain
        XCTAssertEqual(reads, [true])
        let request = try XCTUnwrap(ClaudeStubProtocol.lastRequest)
        XCTAssertEqual(request.url?.path, "/api/v1/agent/claude-sessions")
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-API-Key"), "secret")
    }

    func testTheSenderFailsWithoutAnAddressOrKey() async throws {
        let book = await AddressBook()
        await MainActor.run { book.address = nil }
        let withoutAddress = ClaudeMetricsService.sender(
            serverAddress: { book.read() }, apiKey: { "secret" }, session: ClaudeStubProtocol.session()
        )
        let withoutKey = ClaudeMetricsService.sender(
            serverAddress: { "https://habit.example" }, apiKey: { nil }, session: ClaudeStubProtocol.session()
        )
        let payload = try XCTUnwrap(timedPayload())

        for send in [withoutAddress, withoutKey] {
            do {
                try await send([payload])
                XCTFail("expected a refusal")
            } catch {
                XCTAssertEqual((error as? URLError)?.code, .userAuthenticationRequired)
            }
        }
    }

    func testTheEndpointKeepsTheAddressRulesOfTheActivityEndpoint() {
        XCTAssertEqual(ClaudeSessionsAPI.endpoint(for: "https://habit.example")?.path, "/api/v1/agent/claude-sessions")
        XCTAssertEqual(ClaudeSessionsAPI.endpoint(for: "http://localhost:8000")?.absoluteString, "http://localhost:8000/api/v1/agent/claude-sessions")
        XCTAssertNil(ClaudeSessionsAPI.endpoint(for: "http://habit.example"), "plain http is for loopback only")
    }

    /// Opt-in: `TEST_RUNNER_HABIT_CLAUDE_REAL_SCAN=1` times a pass over the real `~/.claude/projects`.
    func testRealDirectoryPassIsFastTheSecondTime() async throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["HABIT_CLAUDE_REAL_SCAN"] == "1")
        let claude = URL(fileURLWithPath: "/Users/\(NSUserName())/.claude")
        let sent = self.sent!
        let service = ClaudeMetricsService(
            projectsDirectory: claude.appendingPathComponent("projects"),
            goalsDirectory: claude.appendingPathComponent("statusline/goals"),
            stateURL: nil
        ) { try await sent.record($0) }

        let start = Date()
        let first = await service.runPass()
        let firstSeconds = Date().timeIntervalSince(start)
        let secondStart = Date()
        let second = await service.runPass()
        let secondSeconds = Date().timeIntervalSince(secondStart)

        print("REAL-SCAN first: \(first) in \(firstSeconds)s; second: \(second) in \(secondSeconds)s")
        // Sessions running right now still grow between the passes; everything else is skipped.
        XCTAssertLessThan(second.bytesRead, first.bytesRead / 100)
        XCTAssertLessThan(secondSeconds, 10)
    }
}

/// Answers every request locally; remembers the last one.
private final class ClaudeStubProtocol: URLProtocol {
    nonisolated(unsafe) static var handler: ((URLRequest) -> (URLRequest, Int))?
    nonisolated(unsafe) static var lastRequest: URLRequest?

    static func session() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ClaudeStubProtocol.self]
        return URLSession(configuration: configuration)
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let (request, status) = Self.handler?(request) ?? (request, 500)
        Self.lastRequest = request
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data())
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
