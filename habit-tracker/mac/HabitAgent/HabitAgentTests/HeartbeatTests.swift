// [review:need-review] PHASE-03/164
// summary: verifies the heartbeat the agent sends — the body's snake_case keys and ISO dates, the error codes matching the server's closed vocabulary, what a flush summary says as a code, unknown flags written as null, a titles poll that carries the last ETag and treats 304 as «unchanged», a report built from live state, a lost send that costs nothing, a request for a beat during a send that is answered with fresh state, and the minute timer that starts at once and stops
import XCTest
@testable import HabitAgent

@MainActor
final class HeartbeatTests: XCTestCase {
    private let moment = Date(timeIntervalSince1970: 1_800_000_000)

    // MARK: body and codes

    func testBodyUsesTheServersKeysAndIsoDates() throws {
        let beat = Heartbeat(
            agentID: "mac-1", agentVersion: "1.0", accessibilityGranted: false, titlesEnabled: true,
            samplingSeconds: 5, queueDepth: 7, lastFlushAt: moment, lastError: .network
        )
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: encoder.encode(beat)) as? [String: Any]
        )

        XCTAssertEqual(object["agent_id"] as? String, "mac-1")
        XCTAssertEqual(object["agent_version"] as? String, "1.0")
        XCTAssertEqual(object["accessibility_granted"] as? Bool, false)
        XCTAssertEqual(object["titles_enabled"] as? Bool, true)
        XCTAssertEqual(object["sampling_seconds"] as? Int, 5)
        XCTAssertEqual(object["queue_depth"] as? Int, 7)
        XCTAssertEqual(object["last_flush_at"] as? String, "2027-01-15T08:00:00Z")
        XCTAssertEqual(object["last_error"] as? String, "network")
    }

    func testAnUnknownFlagIsWrittenAsNullNotLeftOut() throws {
        let beat = Heartbeat(
            agentID: "mac-1", agentVersion: "1.0", accessibilityGranted: nil, titlesEnabled: nil,
            samplingSeconds: 5, queueDepth: 0, lastFlushAt: nil, lastError: nil
        )
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(beat)) as? [String: Any]
        )

        // The server refuses a body that leaves the keys out, and reads null as «unknown».
        XCTAssertTrue(object["accessibility_granted"] is NSNull)
        XCTAssertTrue(object["titles_enabled"] is NSNull)
    }

    func testErrorCodesAreExactlyTheServersVocabulary() {
        // Mirrors `AgentErrorCode` in backend/app/schemas/agent_heartbeat.py: the
        // server turns any other word down, so a new case here without a new
        // member there is a heartbeat that never lands.
        XCTAssertEqual(
            Set(HeartbeatErrorCode.allCases.map(\.rawValue)),
            ["expired", "unknown_app", "invalid_batch", "network", "queue_unavailable", "claude_format"]
        )
    }

    func testAFlushSaysItsOutcomeAsACodeAndACleanOneSaysNothing() {
        XCTAssertNil(HeartbeatErrorCode(summary: FlushSummary(sent: 12)))
        XCTAssertEqual(HeartbeatErrorCode(summary: FlushSummary(failed: true)), .network)
        XCTAssertEqual(HeartbeatErrorCode(summary: FlushSummary(failed: true, serverRefuses: true)), .invalidBatch)
        XCTAssertEqual(HeartbeatErrorCode(summary: FlushSummary(droppedBundles: ["com.example.app"])), .unknownApp)
        XCTAssertEqual(HeartbeatErrorCode(summary: FlushSummary(droppedInvalid: 1)), .invalidBatch)
        XCTAssertEqual(HeartbeatErrorCode(summary: FlushSummary(expired: 3)), .expired)
    }

    func testTheCodeNeverCarriesAPathOrTitle() {
        for code in HeartbeatErrorCode.allCases {
            XCTAssertNil(code.rawValue.rangeOfCharacter(from: CharacterSet(charactersIn: "/ .:")))
        }
    }

    // MARK: request

    func testRequestGoesToTheHeartbeatEndpointWithTheKey() throws {
        let beat = Heartbeat(
            agentID: "mac-1", agentVersion: "1.0", accessibilityGranted: true, titlesEnabled: true,
            samplingSeconds: 5, queueDepth: 0, lastFlushAt: nil, lastError: nil
        )
        let request = try XCTUnwrap(
            HeartbeatClient.request(for: beat, serverAddress: "https://habit.example", apiKey: "secret")
        )

        XCTAssertEqual(request.url, URL(string: "https://habit.example/api/v1/agent/heartbeat"))
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-API-Key"), "secret")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "application/json")
        XCTAssertNotNil(request.httpBody)
    }

    func testRequestToAPlainHttpRemoteServerIsRefusedLikeEveryOtherCall() {
        let beat = Heartbeat(
            agentID: "mac-1", agentVersion: "1.0", accessibilityGranted: true, titlesEnabled: true,
            samplingSeconds: 5, queueDepth: 0, lastFlushAt: nil, lastError: nil
        )
        XCTAssertNil(HeartbeatClient.request(for: beat, serverAddress: "http://habit.example", apiKey: "k"))
    }

    // MARK: reporter

    private final class Recorder {
        var sent: [Heartbeat] = []
        var failNext = false
    }

    private func reporter(
        _ recorder: Recorder,
        state: @escaping @MainActor () -> HeartbeatState,
        accessibility: @escaping @MainActor () -> Bool? = { true },
        interval: TimeInterval = 60,
        titles: @escaping @MainActor (String?) async -> TitlesAnswer? = { _ in .value(false, etag: nil) },
        gate: (@MainActor () async -> Void)? = nil
    ) -> HeartbeatReporter {
        HeartbeatReporter(
            agentID: "mac-1", agentVersion: "1.0", samplingSeconds: 5, interval: interval,
            state: state,
            accessibilityGranted: accessibility,
            titles: titles,
            send: { beat in
                if let gate { await gate() }
                if recorder.failNext {
                    recorder.failNext = false
                    throw URLError(.notConnectedToInternet)
                }
                recorder.sent.append(beat)
            }
        )
    }

    func testABeatReportsTheStateAsItIsNow() async {
        let recorder = Recorder()
        var depth = 9
        let heartbeat = reporter(
            recorder,
            state: { HeartbeatState(queueDepth: depth, lastFlushAt: self.moment, lastError: .expired) },
            accessibility: { false }
        )

        await heartbeat.beat()
        depth = 0
        await heartbeat.beat()

        XCTAssertEqual(recorder.sent.map(\.queueDepth), [9, 0])
        XCTAssertEqual(recorder.sent.first?.accessibilityGranted, false)
        XCTAssertEqual(recorder.sent.first?.titlesEnabled, false)
        XCTAssertEqual(recorder.sent.first?.lastFlushAt, moment)
        XCTAssertEqual(recorder.sent.first?.lastError, .expired)
        XCTAssertEqual(recorder.sent.first?.agentID, "mac-1")
        XCTAssertEqual(recorder.sent.first?.samplingSeconds, 5)
    }

    func testWhenTheServerCannotBeAskedTheLastKnownSwitchStands() async {
        let recorder = Recorder()
        var answer: TitlesAnswer? = .value(true, etag: nil)
        let heartbeat = reporter(recorder, state: { HeartbeatState() }, titles: { _ in answer })

        await heartbeat.beat()
        answer = nil
        await heartbeat.beat()

        XCTAssertEqual(recorder.sent.map(\.titlesEnabled), [true, true])
    }

    func testTheSwitchIsNullUntilTheServerHasAnswered() async {
        let recorder = Recorder()
        var answer: TitlesAnswer? = nil
        let heartbeat = reporter(recorder, state: { HeartbeatState() }, titles: { _ in answer })

        await heartbeat.beat()
        answer = .value(false, etag: nil)
        await heartbeat.beat()

        XCTAssertEqual(recorder.sent.map(\.titlesEnabled), [nil, false])
    }

    func testTheLastETagGoesBackAndA304KeepsTheKnownSwitch() async {
        let recorder = Recorder()
        var sentETags: [String?] = []
        var answers: [TitlesAnswer?] = [.value(true, etag: "\"v1\""), .notModified, .value(false, etag: "\"v2\"")]
        let heartbeat = reporter(recorder, state: { HeartbeatState() }, titles: { etag in
            sentETags.append(etag)
            return answers.removeFirst()
        })

        await heartbeat.beat()
        await heartbeat.beat()
        await heartbeat.beat()

        XCTAssertEqual(sentETags, [nil, "\"v1\"", "\"v1\""])
        XCTAssertEqual(recorder.sent.map(\.titlesEnabled), [true, true, false])
    }

    func testAnUnknownAccessibilityIsReportedAsNil() async {
        let recorder = Recorder()
        let heartbeat = reporter(recorder, state: { HeartbeatState() }, accessibility: { nil })

        await heartbeat.beat()

        XCTAssertNil(recorder.sent.first?.accessibilityGranted)
    }

    func testTheLoopEndsWhenTheReporterIsGone() async throws {
        let recorder = Recorder()
        weak var weakReporter: HeartbeatReporter?
        do {
            let heartbeat = reporter(recorder, state: { HeartbeatState() }, interval: 0.05)
            weakReporter = heartbeat
            heartbeat.start()
            try await Task.sleep(for: .milliseconds(120))
        }
        try await Task.sleep(for: .milliseconds(200))
        let afterRelease = recorder.sent.count
        try await Task.sleep(for: .milliseconds(200))

        XCTAssertNil(weakReporter)
        XCTAssertEqual(recorder.sent.count, afterRelease)
    }

    func testALostSendCostsNothingAndTheNextBeatGoesThrough() async {
        let recorder = Recorder()
        let heartbeat = reporter(recorder, state: { HeartbeatState() })
        recorder.failNext = true

        await heartbeat.beat()
        XCTAssertTrue(recorder.sent.isEmpty)

        await heartbeat.beat()
        XCTAssertEqual(recorder.sent.count, 1)
    }

    func testABeatAskedForDuringASendIsSentAgainWithTheFreshState() async {
        let recorder = Recorder()
        var depth = 5
        var release: CheckedContinuation<Void, Never>?
        let heartbeat = reporter(
            recorder,
            state: { HeartbeatState(queueDepth: depth) },
            gate: {
                if recorder.sent.isEmpty {
                    await withCheckedContinuation { release = $0 }
                }
            }
        )

        let first = Task { await heartbeat.beat() }
        while release == nil { await Task.yield() }
        depth = 0
        await heartbeat.beat()
        release?.resume()
        await first.value

        XCTAssertEqual(recorder.sent.map(\.queueDepth), [5, 0])
    }

    func testStartBeatsAtOnceThenOnTheIntervalAndStopEndsIt() async throws {
        let recorder = Recorder()
        let heartbeat = reporter(recorder, state: { HeartbeatState() }, interval: 0.05)

        heartbeat.start()
        try await Task.sleep(for: .milliseconds(300))
        heartbeat.stop()
        let afterStop = recorder.sent.count
        try await Task.sleep(for: .milliseconds(200))

        XCTAssertGreaterThanOrEqual(afterStop, 2)
        XCTAssertEqual(recorder.sent.count, afterStop)
    }
}
