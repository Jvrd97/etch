// [review:need-review] PHASE-03/159
// summary: tests of the floating window — the timer's end cut at the last input, the config poller's outage behaviour on the shared Backoff, the requests the panel makes, the outbox of timer intervals, the date the button opens, and the panel's flags, saved frame and refusal to activate the app
import AppKit
import XCTest
@testable import HabitAgent

// MARK: - Timer

@MainActor
final class TaskTimerTests: XCTestCase {
    /// A clock and a keyboard the test moves by hand.
    @MainActor final class Rig {
        let origin = Date(timeIntervalSince1970: 1_800_000_000)
        lazy var now = origin
        lazy var lastInput = origin
        var emitted: [ManualInterval] = []
        var timer: TaskTimer!

        init() {
            timer = TaskTimer(
                emit: { [unowned self] in emitted.append($0) },
                now: { [unowned self] in now },
                secondsSinceLastInput: { [unowned self] in now.timeIntervalSince(lastInput) },
                timeZone: TimeZone(secondsFromGMT: 0)!
            )
        }

        /// Time passes in 30-second ticks; the person types through it or does not.
        func pass(_ seconds: TimeInterval, typing: Bool) {
            var left = seconds
            while left > 0 {
                let step = min(30, left)
                now = now.addingTimeInterval(step)
                if typing { lastInput = now }
                timer.tick()
                left -= step
            }
        }

        func at(_ seconds: TimeInterval) -> Date { origin.addingTimeInterval(seconds) }
    }

    private let task = TimedTask(id: UUID(), title: "Разобрать почту")

    func testStartAndStopWriteOneIntervalWithTheTask() {
        let rig = Rig()
        rig.timer.start(task: task)
        rig.pass(90, typing: true)
        rig.timer.stop()

        XCTAssertEqual(rig.emitted.count, 1)
        XCTAssertEqual(rig.emitted[0].startedAt, rig.at(0))
        XCTAssertEqual(rig.emitted[0].endedAt, rig.at(90))
        XCTAssertEqual(rig.emitted[0].taskID, task.id)
        XCTAssertEqual(rig.emitted[0].taskTitle, task.title)
        XCTAssertEqual(rig.timer.lastStop, .manual)
    }

    func testElapsedFollowsTheClockWhileRunning() {
        let rig = Rig()
        rig.timer.start(task: task)
        rig.pass(120, typing: true)
        XCTAssertEqual(rig.timer.elapsed, 120)
    }

    func testStoppingAtOnceWritesNothing() {
        let rig = Rig()
        rig.timer.start(task: task)
        rig.timer.stop()
        XCTAssertTrue(rig.emitted.isEmpty)
        XCTAssertFalse(rig.timer.isRunning)
    }

    func testAwayFortyMinutesCutsTheEndAtTheLastInputNotAtTheReturn() {
        let rig = Rig()
        rig.timer.start(task: task)
        rig.pass(300, typing: true)
        rig.pass(40 * 60, typing: false)

        XCTAssertFalse(rig.timer.isRunning, "the idle threshold passed long before the person came back")
        XCTAssertEqual(rig.emitted.count, 1)
        XCTAssertEqual(rig.emitted[0].endedAt, rig.at(300))
        XCTAssertNotEqual(rig.emitted[0].endedAt, rig.now)
        XCTAssertEqual(rig.timer.lastStop, .idle(since: rig.at(300)))
    }

    func testAMacThatSleptThroughTheAbsenceIsCutAtTheLastInputToo() {
        let rig = Rig()
        rig.timer.start(task: task)
        rig.pass(300, typing: true)
        // No ticks at all for forty minutes; the idle reading counts the sleep.
        rig.now = rig.now.addingTimeInterval(40 * 60)
        rig.timer.tick()

        XCTAssertFalse(rig.timer.isRunning)
        XCTAssertEqual(rig.emitted[0].endedAt, rig.at(300))
    }

    func testAMacThatWokeToAKeyPressIsCutAtTheLastTickNotAtTheWakeUp() {
        let rig = Rig()
        rig.timer.start(task: task)
        rig.pass(300, typing: true)
        // The idle reading does not count the sleep and the wake-up key reset it.
        rig.now = rig.now.addingTimeInterval(40 * 60)
        rig.lastInput = rig.now
        rig.timer.tick()

        XCTAssertFalse(rig.timer.isRunning)
        XCTAssertEqual(rig.emitted[0].endedAt, rig.at(300))
        XCTAssertEqual(rig.timer.lastStop, .suspended(since: rig.at(300)))
    }

    func testAPauseShorterThanTheThresholdKeepsTheTimerRunning() {
        let rig = Rig()
        rig.timer.start(task: task)
        rig.pass(60, typing: true)
        rig.pass(9 * 60, typing: false)
        XCTAssertTrue(rig.timer.isRunning)
        XCTAssertTrue(rig.emitted.isEmpty)
    }

    func testTheEndNeverPrecedesTheStart() {
        let rig = Rig()
        rig.timer.start(task: task)
        // The last input was the click that started the timer, and nothing since.
        rig.pass(11 * 60, typing: false)

        XCTAssertFalse(rig.timer.isRunning)
        XCTAssertTrue(rig.emitted.isEmpty, "a stretch of no length is not written")
    }

    func testASecondStartWhileRunningChangesNothing() {
        let rig = Rig()
        rig.timer.start(task: task)
        rig.pass(30, typing: true)
        rig.timer.start(task: nil)
        XCTAssertEqual(rig.timer.task, task)
        XCTAssertEqual(rig.timer.elapsed, 30)
    }

    func testAnIntervalIsWrittenInWholeSecondsAndTheLocalDateOfItsStart() {
        let moscow = TimeZone(identifier: "Europe/Moscow")!
        // 2026-10-25 23:30:10.9 UTC is already the 26th in Moscow.
        let start = Date(timeIntervalSince1970: 1_792_971_010.9)
        let interval = ManualInterval(startedAt: start, endedAt: start.addingTimeInterval(61.4), task: nil, timeZone: moscow)

        XCTAssertEqual(interval.startedAt.timeIntervalSince1970, 1_792_971_010)
        XCTAssertEqual(interval.endedAt.timeIntervalSince1970, 1_792_971_072)
        XCTAssertEqual(interval.localDate, "2026-10-26")
        XCTAssertEqual(interval.utcOffsetMinutes, 180)
    }
}

// MARK: - Poller

@MainActor
final class ConditionalPollerTests: XCTestCase {
    private struct Outage: Error {}

    @MainActor private final class Script {
        var now = Date(timeIntervalSince1970: 1_800_000_000)
        var answers: [Result<PollResponse<String>, Error>] = []
        var etagsAsked: [String?] = []

        func poller(sleep: @escaping ConditionalPoller<String>.Sleep = { _ in }) -> ConditionalPoller<String> {
            ConditionalPoller<String>(
                interval: 30,
                staleAfter: 120,
                maxRetryDelay: 60,
                now: { [unowned self] in now },
                sleep: sleep,
                fetch: { [unowned self] etag in
                    etagsAsked.append(etag)
                    return try answers.removeFirst().get()
                }
            )
        }
    }

    func testAnAnswerIsKeptAndItsETagIsSentNext() async {
        let script = Script()
        let poller = script.poller()
        script.answers = [.success(.modified("A", etag: "\"1\"")), .success(.notModified)]

        await poller.pollOnce()
        await poller.pollOnce()

        XCTAssertEqual(poller.value, "A")
        XCTAssertEqual(script.etagsAsked, [nil, "\"1\""])
    }

    func testNotModifiedKeepsTheValueAndCountsAsFresh() async {
        let script = Script()
        let poller = script.poller()
        script.answers = [.success(.modified("A", etag: "\"1\"")), .success(.notModified)]
        await poller.pollOnce()
        script.now = script.now.addingTimeInterval(100)
        await poller.pollOnce()

        XCTAssertEqual(poller.value, "A")
        XCTAssertEqual(poller.lastSuccessAt, script.now)
        XCTAssertFalse(poller.isStale(at: script.now.addingTimeInterval(100)))
    }

    func testAnOutageKeepsTheLastValueMarksItStaleAndRetriesOnTheBackoff() async {
        let script = Script()
        let poller = script.poller()
        script.answers = [.success(.modified("A", etag: nil))]
        await poller.pollOnce()
        let freshAt = script.now

        script.answers = Array(repeating: .failure(Outage()), count: 4)
        var delays: [TimeInterval] = []
        for _ in 0..<4 {
            script.now = script.now.addingTimeInterval(60)
            await poller.pollOnce()
            delays.append(poller.nextDelay)
        }

        XCTAssertEqual(poller.value, "A", "the window keeps drawing the last known value")
        XCTAssertEqual(delays, [30, 60, 60, 60], "30 s, doubling, held at the poller's ceiling")
        XCTAssertFalse(poller.isStale(at: freshAt.addingTimeInterval(119)))
        XCTAssertTrue(poller.isStale(at: freshAt.addingTimeInterval(121)))
        XCTAssertNotNil(poller.lastFailure)
    }

    func testTheMarkGoesAwayByItselfWhenTheNetworkReturns() async {
        let script = Script()
        let poller = script.poller()
        script.answers = [.success(.modified("A", etag: nil)), .failure(Outage())]
        await poller.pollOnce()
        script.now = script.now.addingTimeInterval(600)
        await poller.pollOnce()
        XCTAssertTrue(poller.isStale(at: script.now))

        script.answers = [.success(.modified("B", etag: nil))]
        await poller.pollOnce()

        XCTAssertEqual(poller.value, "B")
        XCTAssertFalse(poller.isStale(at: script.now))
        XCTAssertNil(poller.lastFailure)
        XCTAssertEqual(poller.nextDelay, 30, "back to the regular interval after a success")
    }

    func testBeforeTheFirstAnswerSilenceIsCountedFromTheStart() async {
        let script = Script()
        let poller = script.poller()
        XCTAssertFalse(poller.isStale(at: script.now.addingTimeInterval(100)))
        XCTAssertTrue(poller.isStale(at: script.now.addingTimeInterval(121)))
    }

    func testACancelledPollIsNotAFailure() async {
        let script = Script()
        let poller = script.poller()
        script.answers = [.failure(CancellationError()), .failure(URLError(.cancelled))]
        await poller.pollOnce()
        await poller.pollOnce()
        XCTAssertNil(poller.lastFailure)
        XCTAssertEqual(poller.nextDelay, 30)
    }

    func testTheRunLoopWaitsTheDelayTheLastPollAskedFor() async {
        let script = Script()
        var waited: [TimeInterval] = []
        var runner: Task<Void, Never>?
        let poller = script.poller(sleep: { delay in
            waited.append(delay)
            if waited.count == 4 { runner?.cancel() }
        })
        script.answers = [.success(.modified("A", etag: nil)), .failure(Outage()), .failure(Outage()), .success(.notModified)]

        runner = Task { await poller.run() }
        await runner?.value

        XCTAssertEqual(waited, [30, 30, 60, 30])
    }

    /// The acceptance bullet «a second implementation of the backoff does not exist»,
    /// as a check on the source tree: one declaration, in the queue's folder.
    func testThereIsExactlyOneBackoffInTheAgent() throws {
        let sources = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("HabitAgent", isDirectory: true)
        let files = try XCTUnwrap(FileManager.default.enumerator(at: sources, includingPropertiesForKeys: nil))
        var declarations: [String] = []
        for case let file as URL in files where file.pathExtension == "swift" {
            let text = try String(contentsOf: file, encoding: .utf8)
            if text.range(of: #"(struct|class|enum|actor)\s+\w*Backoff\w*"#, options: .regularExpression) != nil {
                declarations.append(file.lastPathComponent)
            }
        }
        XCTAssertEqual(declarations, ["Backoff.swift"])
    }
}

// MARK: - Requests

private final class StubURLProtocol: URLProtocol {
    nonisolated(unsafe) static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        do {
            let (response, data) = try XCTUnwrap(Self.handler)(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}

    static func session() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        return URLSession(configuration: configuration)
    }
}

private func body(of request: URLRequest) -> Data {
    guard let stream = request.httpBodyStream else { return request.httpBody ?? Data() }
    stream.open()
    defer { stream.close() }
    var data = Data()
    var buffer = [UInt8](repeating: 0, count: 4096)
    while stream.hasBytesAvailable {
        let count = stream.read(&buffer, maxLength: buffer.count)
        if count <= 0 { break }
        data.append(buffer, count: count)
    }
    return data
}

private func reply(_ request: URLRequest, status: Int, headers: [String: String] = [:], body: String = "") -> (HTTPURLResponse, Data) {
    (HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: headers)!, Data(body.utf8))
}

/// What the server sends: the panel's fields among the rest of the agent's config.
private let configJSON = """
{
  "titles_enabled": true,
  "sampling_seconds": 5,
  "day_mode": {"date": "2026-10-25", "kind": "work", "nocode": false, "source": "schedule"},
  "title_rules": [],
  "current_task": {
    "id": "0b8f1c52-6d77-4c0e-9d0a-2f6a1f3a9b10",
    "title": "Сдать отчёт",
    "starts_at": "2026-10-25T08:00:00Z",
    "ends_at": "2026-10-25T10:00:00.250000Z"
  },
  "day_path": "/day/2026-10-25"
}
"""

final class PanelAPIClientTests: XCTestCase {
    private func client(address: String = "https://habit.example") -> PanelAPIClient {
        PanelAPIClient(serverAddress: address, apiKey: "secret", session: StubURLProtocol.session())
    }

    func testTheConfigIsAskedWithTheKeyAndTheLastETag() async throws {
        var seen: URLRequest?
        StubURLProtocol.handler = { request in
            seen = request
            return reply(request, status: 200, headers: ["ETag": "\"abc\""], body: configJSON)
        }

        let answer = try await client().fetchConfig(etag: "\"old\"")

        XCTAssertEqual(seen?.url?.absoluteString, "https://habit.example/api/v1/agent/config")
        XCTAssertEqual(seen?.value(forHTTPHeaderField: "X-API-Key"), "secret")
        XCTAssertEqual(seen?.value(forHTTPHeaderField: "If-None-Match"), "\"old\"")
        guard case let .modified(config, etag) = answer else { return XCTFail("expected a body") }
        XCTAssertEqual(etag, "\"abc\"")
        XCTAssertEqual(config.date, "2026-10-25")
        XCTAssertEqual(config.dayPath, "/day/2026-10-25")
        XCTAssertEqual(config.currentTask?.title, "Сдать отчёт")
        XCTAssertEqual(config.currentTask?.id, UUID(uuidString: "0B8F1C52-6D77-4C0E-9D0A-2F6A1F3A9B10"))
        XCTAssertEqual(config.currentTask?.startsAt, Date(timeIntervalSince1970: 1_792_915_200))
        XCTAssertEqual(config.currentTask?.endsAt.timeIntervalSince1970 ?? 0, 1_792_922_400.25, accuracy: 0.001)
    }

    func testADayWithNoTaskDecodes() async throws {
        let json = configJSON.replacingOccurrences(
            of: #"(?s)"current_task": \{.*?\},\n  "day_path""#, with: #""current_task": null, "day_path""#, options: .regularExpression
        )
        StubURLProtocol.handler = { reply($0, status: 200, body: json) }

        guard case let .modified(config, _) = try await client().fetchConfig(etag: nil) else { return XCTFail() }
        XCTAssertNil(config.currentTask)
    }

    func testNotModifiedCarriesNoBody() async throws {
        StubURLProtocol.handler = { reply($0, status: 304) }
        let answer = try await client().fetchConfig(etag: "\"abc\"")
        XCTAssertEqual(answer, .notModified)
    }

    func testAServerErrorOnTheConfigIsAFailureNotAnAnswer() async {
        StubURLProtocol.handler = { reply($0, status: 503) }
        do {
            _ = try await client().fetchConfig(etag: nil)
            XCTFail("expected an error")
        } catch {
            XCTAssertEqual(error as? PanelAPIError, .http(status: 503))
        }
    }

    func testAnAddressTheAgentDoesNotAcceptIsNotConfigured() async {
        do {
            _ = try await client(address: "http://habit.example").fetchConfig(etag: nil)
            XCTFail("expected an error")
        } catch {
            XCTAssertEqual(error as? PanelAPIError, .notConfigured)
        }
    }

    func testAManualIntervalGoesUnderItsKeyWithTheTaskItWasSpentOn() async throws {
        var seen: URLRequest?
        var sent = Data()
        StubURLProtocol.handler = { request in
            seen = request
            sent = body(of: request)
            return reply(request, status: 201)
        }
        let task = TimedTask(id: UUID(), title: "Сдать отчёт")
        let start = Date(timeIntervalSince1970: 1_792_915_200)
        let interval = ManualInterval(startedAt: start, endedAt: start.addingTimeInterval(1800), task: task, timeZone: TimeZone(secondsFromGMT: 0)!)

        try await client().send(interval)

        XCTAssertEqual(seen?.httpMethod, "POST")
        XCTAssertEqual(seen?.url?.path, "/api/v1/agent/activity/manual")
        XCTAssertEqual(seen?.value(forHTTPHeaderField: "Idempotency-Key"), interval.key.uuidString)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: sent) as? [String: Any])
        XCTAssertEqual(json["started_at"] as? String, "2026-10-25T08:00:00Z")
        XCTAssertEqual(json["ended_at"] as? String, "2026-10-25T08:30:00Z")
        XCTAssertEqual(json["local_date"] as? String, "2026-10-25")
        XCTAssertEqual(json["plan_item_id"] as? String, task.id.uuidString)
        XCTAssertEqual(json["note"] as? String, "Сдать отчёт")
        XCTAssertEqual(json["utc_offset_minutes"] as? Int, 0)
    }

    func testWhatTheServerWillRefuseAgainIsNotRetried() {
        XCTAssertEqual(PanelAPIClient.error(status: 422), .rejected(status: 422))
        XCTAssertEqual(PanelAPIClient.error(status: 409), .rejected(status: 409))
        XCTAssertEqual(PanelAPIClient.error(status: 429), .http(status: 429))
        XCTAssertEqual(PanelAPIClient.error(status: 408), .http(status: 408))
        XCTAssertEqual(PanelAPIClient.error(status: 502), .http(status: 502))
    }

    /// A wrong key gets rotated, an old server gets a route it did not have: none of
    /// these configuration mistakes are the caller's — retrying after they are fixed
    /// must still work, so dropping the interval here would be the bug `#159`'s circle
    /// 1 review caught (every 4xx but 408/429 was `.rejected` and dropped for good).
    func testAConfigurationRefusalIsNotFinal() {
        XCTAssertEqual(PanelAPIClient.error(status: 401), .http(status: 401))
        XCTAssertEqual(PanelAPIClient.error(status: 403), .http(status: 403))
        XCTAssertEqual(PanelAPIClient.error(status: 404), .http(status: 404))
        XCTAssertEqual(PanelAPIClient.error(status: 405), .http(status: 405))
    }

    func testTheDayPageIsOnTheOriginTheAgentTalksTo() {
        XCTAssertEqual(
            PanelAPIClient.dayPageURL(serverAddress: "https://habit.example", dayPath: "/day/2026-10-25"),
            URL(string: "https://habit.example/day/2026-10-25")
        )
        XCTAssertEqual(
            PanelAPIClient.dayPageURL(serverAddress: "http://localhost:3000", dayPath: "/day/2026-10-25"),
            URL(string: "http://localhost:3000/day/2026-10-25")
        )
        XCTAssertNil(PanelAPIClient.dayPageURL(serverAddress: "http://habit.example", dayPath: "/day/2026-10-25"))
        XCTAssertNil(PanelAPIClient.dayPageURL(serverAddress: "https://habit.example", dayPath: "day/2026-10-25"))
    }
}

// MARK: - Outbox of timer intervals

@MainActor
final class ManualIntervalOutboxTests: XCTestCase {
    private struct Down: Error {}

    private var directory: URL!
    private var file: URL { directory.appendingPathComponent("manual-intervals.json") }

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("outbox-\(UUID().uuidString)", isDirectory: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: directory)
    }

    private func interval(_ offset: TimeInterval = 0) -> ManualInterval {
        let start = Date(timeIntervalSince1970: 1_800_000_000 + offset)
        return ManualInterval(startedAt: start, endedAt: start.addingTimeInterval(600), task: TimedTask(id: UUID(), title: "t"))
    }

    func testAnIntervalIsOnDiskBeforeAnythingIsSent() throws {
        let outbox = ManualIntervalOutbox(fileURL: file) { _ in }
        let queued = interval()
        outbox.enqueue(queued)

        let reborn = ManualIntervalOutbox(fileURL: file) { _ in }
        XCTAssertEqual(reborn.pending, [queued], "survives the death of the process")
    }

    func testAConfirmedIntervalLeavesTheQueueAndTheFile() async {
        var sent: [ManualInterval] = []
        let outbox = ManualIntervalOutbox(fileURL: file) { sent.append($0) }
        outbox.enqueue(interval(0))
        outbox.enqueue(interval(1000))

        await outbox.flush()

        XCTAssertEqual(sent.count, 2)
        XCTAssertEqual(sent, sent.sorted { $0.startedAt < $1.startedAt }, "oldest first")
        XCTAssertTrue(outbox.pending.isEmpty)
        XCTAssertTrue(ManualIntervalOutbox(fileURL: file) { _ in }.pending.isEmpty)
    }

    func testAFailedSendKeepsTheIntervalAndRetriesItUnderTheSameKeyAfterTheBackoff() async {
        var clock = Date(timeIntervalSince1970: 1_800_001_000)
        var attempts: [UUID] = []
        var online = false
        let outbox = ManualIntervalOutbox(fileURL: file, now: { clock }) { interval in
            attempts.append(interval.key)
            if !online { throw Down() }
        }
        let queued = interval()
        outbox.enqueue(queued)

        await outbox.flush()
        XCTAssertEqual(outbox.pending, [queued])
        XCTAssertFalse(outbox.isDue, "the backoff has not run out")
        await outbox.flush()
        XCTAssertEqual(attempts.count, 1, "no second attempt inside the backoff")

        clock = clock.addingTimeInterval(31)
        XCTAssertTrue(outbox.isDue)
        online = true
        await outbox.flush()

        XCTAssertEqual(attempts, [queued.key, queued.key])
        XCTAssertTrue(outbox.pending.isEmpty)
    }

    func testWhatTheServerRefusesForGoodIsDroppedAndDoesNotBlockTheNext() async {
        var sent: [ManualInterval] = []
        let refused = interval(0)
        let outbox = ManualIntervalOutbox(fileURL: file) { interval in
            if interval.key == refused.key { throw PanelAPIError.rejected(status: 422) }
            sent.append(interval)
        }
        let next = interval(1000)
        outbox.enqueue(refused)
        outbox.enqueue(next)

        await outbox.flush()

        XCTAssertEqual(sent, [next])
        XCTAssertEqual(outbox.droppedCount, 1)
        XCTAssertTrue(outbox.pending.isEmpty)
    }

    func testA401Or404LeavesTheIntervalOnDiskInsteadOfDroppingIt() async {
        for status in [401, 404] {
            let outbox = ManualIntervalOutbox(fileURL: file) { _ in throw PanelAPIError.http(status: status) }
            let queued = interval()
            outbox.enqueue(queued)

            await outbox.flush()

            XCTAssertEqual(outbox.pending, [queued], "status \(status) must retry, not drop")
            XCTAssertEqual(outbox.droppedCount, 0)
            XCTAssertEqual(ManualIntervalOutbox(fileURL: file) { _ in }.pending, [queued], "survives on disk too")
            try? FileManager.default.removeItem(at: file)
        }
    }

    func testAnUnreadableFileIsSetAsideNotOverwritten() throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try Data("not json".utf8).write(to: file)

        let outbox = ManualIntervalOutbox(fileURL: file) { _ in }
        outbox.enqueue(interval())

        XCTAssertTrue(FileManager.default.fileExists(atPath: file.appendingPathExtension("unreadable").path))
        XCTAssertEqual(outbox.pending.count, 1)
    }

    func testTheFileLivesUnderTheAgentsFolderInApplicationSupport() {
        let path = ManualIntervalOutbox.defaultFileURL().path
        XCTAssertTrue(path.contains("/Library/Application Support/com.talvior.habitagent/"), path)
    }
}

// MARK: - The window's model

@MainActor
final class PanelModelTests: XCTestCase {
    private struct Outage: Error {}

    @MainActor private final class World {
        var now = Date(timeIntervalSince1970: 1_800_000_000)
        var lastInput = Date(timeIntervalSince1970: 1_800_000_000)
        var config: Result<PollResponse<PanelConfig>, Error> = .success(.modified(PanelConfig(currentTask: nil, dayPath: "/day/2026-10-25", date: "2026-10-25"), etag: nil))
        var opened: [URL] = []
        var emitted: [ManualInterval] = []
        var address: String? = "https://habit.example"
        var model: PanelModel!

        init() {
            let poller = ConditionalPoller<PanelConfig>(interval: 30, staleAfter: 120, maxRetryDelay: 60, now: { [unowned self] in now }, sleep: { _ in }) { [unowned self] _ in
                try config.get()
            }
            model = PanelModel(
                config: poller,
                timer: TaskTimer(
                    emit: { [unowned self] in emitted.append($0) },
                    now: { [unowned self] in now },
                    secondsSinceLastInput: { [unowned self] in now.timeIntervalSince(lastInput) }
                ),
                serverAddress: { [unowned self] in address },
                openURL: { [unowned self] in opened.append($0) },
                now: { [unowned self] in now }
            )
        }

        func advance(_ seconds: TimeInterval, typing: Bool = true) {
            now = now.addingTimeInterval(seconds)
            if typing { lastInput = now }
            model.tick()
        }
    }

    private func taskConfig(_ title: String, id: UUID = UUID()) -> PollResponse<PanelConfig> {
        let task = PanelConfig.Task(id: id, title: title, startsAt: Date(timeIntervalSince1970: 1_800_000_000), endsAt: Date(timeIntervalSince1970: 1_800_003_600))
        return .modified(PanelConfig(currentTask: task, dayPath: "/day/2026-10-25", date: "2026-10-25"), etag: nil)
    }

    func testTheButtonOpensTheDayPageOfTheDateTheWindowShows() async {
        let world = World()
        await world.model.config.pollOnce()

        world.model.openDayInBrowser()

        XCTAssertEqual(world.model.dateLabel, "25 октября")
        let opened = try? XCTUnwrap(world.opened.first)
        XCTAssertEqual(opened?.absoluteString, "https://habit.example/day/2026-10-25")
        XCTAssertEqual(opened?.lastPathComponent, world.model.config.value?.date)
    }

    func testWithoutAConfigOrAnAddressTheButtonOpensNothing() async {
        let world = World()
        world.model.openDayInBrowser()
        XCTAssertTrue(world.opened.isEmpty)
        XCTAssertFalse(world.model.canOpenDay)

        await world.model.config.pollOnce()
        world.address = nil
        world.model.openDayInBrowser()
        XCTAssertTrue(world.opened.isEmpty)
    }

    func testTheTimerIsBoundToTheTaskItStartedOn() async {
        let world = World()
        let first = UUID()
        world.config = .success(taskConfig("Первая", id: first))
        await world.model.config.pollOnce()

        world.model.toggleTimer()
        world.config = .success(taskConfig("Вторая"))
        await world.model.config.pollOnce()
        for _ in 0..<4 { world.advance(30) }
        world.model.toggleTimer()

        XCTAssertEqual(world.emitted.count, 1)
        XCTAssertEqual(world.emitted[0].taskID, first)
        XCTAssertEqual(world.model.currentTask?.title, "Вторая")
    }

    /// The acceptance case «Tailscale is off for ten minutes».
    func testAnOutageKeepsTheTaskAndTheTimerAndTheMarkClearsWhenTheNetworkReturns() async {
        let world = World()
        world.config = .success(taskConfig("Сдать отчёт"))
        await world.model.config.pollOnce()
        world.model.toggleTimer()
        world.advance(30)
        XCTAssertFalse(world.model.configIsStale)

        world.config = .failure(Outage())
        for _ in 0..<10 {
            world.advance(60)
            await world.model.config.pollOnce()
        }

        XCTAssertEqual(world.model.currentTask?.title, "Сдать отчёт", "the last known task stays")
        XCTAssertTrue(world.model.configIsStale, "and says that it is old")
        XCTAssertTrue(world.model.timer.isRunning, "the timer does not depend on the network")
        XCTAssertEqual(world.model.timer.elapsed, 630)

        world.config = .success(taskConfig("Сдать отчёт"))
        await world.model.config.pollOnce()
        world.advance(1)

        XCTAssertFalse(world.model.configIsStale, "the mark goes away by itself")
        XCTAssertTrue(world.model.timer.isRunning)
    }

    func testAMissingAddressIsShownAsSetupNotAsAnOutage() async {
        let world = World()
        world.config = .failure(PanelAPIError.notConfigured)
        await world.model.config.pollOnce()
        XCTAssertTrue(world.model.needsSetup)
    }
}

// MARK: - The window itself

@MainActor
final class FloatingPanelTests: XCTestCase {
    private var names: [String] = []
    private var suites: [String] = []

    override func tearDown() {
        for name in names { UserDefaults.standard.removeObject(forKey: "NSWindow Frame \(name)") }
        for suite in suites { UserDefaults().removePersistentDomain(forName: suite) }
        names = []
        suites = []
        super.tearDown()
    }

    private func makeModel() -> PanelModel {
        let poller = ConditionalPoller<PanelConfig>(interval: 30, staleAfter: 120, maxRetryDelay: 60, sleep: { _ in }) { _ in .notModified }
        return PanelModel(config: poller, timer: TaskTimer(emit: { _ in }), serverAddress: { nil }, openURL: { _ in })
    }

    private func makeController(name: String? = nil, model: PanelModel? = nil) -> FloatingPanelController {
        let autosave = name ?? "HabitAgentTest-\(UUID().uuidString)"
        names.append(autosave)
        let suite = "HabitAgentTestDefaults-\(UUID().uuidString)"
        suites.append(suite)
        return FloatingPanelController(model: model ?? makeModel(), autosaveName: autosave, defaults: UserDefaults(suiteName: suite)!)
    }

    /// What makes a click on the panel leave the app in front alone. A synthetic
    /// click cannot show it: AppKit does not activate an accessory app for one
    /// even with an ordinary panel, so the cause is checked, not the effect.
    func testThePanelFloatsOverFullScreenAppsFollowsTheSpacesAndTakesNoFocus() {
        let panel = makeController().panel

        XCTAssertTrue(panel.styleMask.contains(.nonactivatingPanel))
        XCTAssertTrue(panel.becomesKeyOnlyIfNeeded)
        XCTAssertEqual(panel.level, .floating)
        XCTAssertTrue(panel.collectionBehavior.contains(.canJoinAllSpaces))
        XCTAssertTrue(panel.collectionBehavior.contains(.fullScreenAuxiliary))
        XCTAssertFalse(panel.canBecomeKey)
        XCTAssertFalse(panel.canBecomeMain)
        XCTAssertFalse(panel.hidesOnDeactivate)
        XCTAssertTrue(panel.isMovableByWindowBackground)
    }

    func testTheFrameComesBackToThePixelAfterARestart() throws {
        guard let screen = NSScreen.main else { throw XCTSkip("needs a display") }
        let name = "HabitAgentTest-\(UUID().uuidString)"
        var first: FloatingPanelController? = makeController(name: name)
        let target = NSPoint(x: screen.visibleFrame.minX + 123, y: screen.visibleFrame.minY + 211)
        first?.panel.setFrameOrigin(target)
        let saved = try XCTUnwrap(first?.panel.frame)
        first?.panel.setFrameAutosaveName("")
        first = nil

        let second = makeController(name: name)

        XCTAssertEqual(second.panel.frame, saved)
        XCTAssertEqual(second.panel.frame.origin, target)
    }

    func testAFirstLaunchPutsThePanelInsideTheScreen() throws {
        guard let screen = NSScreen.main else { throw XCTSkip("needs a display") }
        let controller = makeController()
        XCTAssertTrue(screen.visibleFrame.contains(controller.panel.frame))
    }

    func testAWindowFromAnOlderVersionGrowsDownFromItsTopLeftCorner() throws {
        guard let screen = NSScreen.main else { throw XCTSkip("needs a display") }
        let name = "HabitAgentTest-\(UUID().uuidString)"
        let old = NSRect(x: screen.visibleFrame.minX + 50, y: screen.visibleFrame.minY + 400, width: 200, height: 100)
        let holder = NSWindow(contentRect: old, styleMask: .borderless, backing: .buffered, defer: true)
        holder.saveFrame(usingName: name)
        names.append(name)

        let panel = makeController(name: name).panel

        XCTAssertEqual(panel.frame.minX, old.minX)
        XCTAssertEqual(panel.frame.maxY, old.maxY)
        XCTAssertEqual(panel.frame.size, FloatingPanelController.contentSize)
    }

    func testMinimizingToTheMenuBarAndBackKeepsThePositionAndTheTimer() throws {
        let model = makeModel()
        model.timer.start(task: TimedTask(id: UUID(), title: "t"))
        let controller = makeController(model: model)
        controller.show()
        let frame = controller.panel.frame

        controller.hide()
        XCTAssertFalse(controller.isVisible)
        XCTAssertFalse(controller.wasVisibleLastTime)
        controller.show()
        defer { controller.hide() }

        XCTAssertTrue(controller.isVisible)
        XCTAssertEqual(controller.panel.frame, frame)
        XCTAssertTrue(model.timer.isRunning)
    }
}
