// [review:need-review] PHASE-03/163, PHASE-03/217, PHASE-03/235
// summary: the disk queue and its flusher — survives a kill, cuts batches at 500, keeps intervals through network errors and resends the same batch, backs off up to a ceiling, drops by retention with a code, writes only under its own directory, keeps a tally per error code, loses at most a checkpoint to a kill and flushes when a new interface joins
import XCTest
@testable import HabitAgent

@MainActor
private final class Gate {
    private var waiters: [CheckedContinuation<Void, Never>] = []
    private var isOpen = false

    func wait() async {
        guard !isOpen else { return }
        await withCheckedContinuation { waiters.append($0) }
    }

    func open() {
        isOpen = true
        waiters.forEach { $0.resume() }
        waiters = []
    }
}

/// A server that is not there: answers every request the way the test says, or drops the connection.
private final class StubServer: URLProtocol {
    nonisolated(unsafe) static var handler: ((URLRequest, Data) throws -> Int)?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() {}

    override func startLoading() {
        do {
            let status = try Self.handler?(request, Self.body(of: request)) ?? 500
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data("{}".utf8))
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    private static func body(of request: URLRequest) -> Data {
        guard let stream = request.httpBodyStream else { return request.httpBody ?? Data() }
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let read = stream.read(&buffer, maxLength: buffer.count)
            guard read > 0 else { break }
            data.append(buffer, count: read)
        }
        return data
    }
}

@MainActor
final class QueueTests: XCTestCase {
    private let start = Date(timeIntervalSince1970: 1_800_000_000)
    /// Private to one test: nothing else ever writes here, so the tests may list it and run in parallel.
    private var root: URL!
    private var directory: URL!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("habit-agent-queue-test-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        directory = root.appendingPathComponent("queue", isDirectory: true)
    }

    override func tearDownWithError() throws {
        StubServer.handler = nil
        try? FileManager.default.removeItem(at: root)
    }

    private func intervals(_ count: Int, bundleID: String = "com.example.editor", from offset: Int = 0) -> [ActivityInterval] {
        (offset..<offset + count).map { index in
            ActivityInterval(
                bundleID: bundleID,
                startedAt: start.addingTimeInterval(TimeInterval(index * 10)),
                endedAt: start.addingTimeInterval(TimeInterval(index * 10 + 5)),
                localDate: "2027-01-15",
                utcOffsetMinutes: 0,
                switchCount: 0
            )
        }
    }

    private func makeStore(excluding bundles: Set<String> = []) throws -> OutboxStore {
        try OutboxStore(directory: directory, excluding: bundles)
    }

    private func makeFlusher(_ store: OutboxStore, send: @escaping Flusher.Sender) -> Flusher {
        Flusher(store: store, sender: { send })
    }

    // MARK: Backoff

    func testBackoffDoublesFromTheInitialDelayAndStopsAtTheCeiling() {
        var backoff = Backoff()
        let delays = (0..<9).map { _ in backoff.recordFailure() }
        XCTAssertEqual(delays, [30, 60, 120, 240, 480, 600, 600, 600, 600])
    }

    func testBackoffStartsOverAfterASuccess() {
        var backoff = Backoff()
        _ = backoff.recordFailure()
        _ = backoff.recordFailure()
        backoff.reset()
        XCTAssertEqual(backoff.recordFailure(), Backoff.initialDelay)
    }

    func testBackoffTakesItsOwnDelays() {
        var backoff = Backoff(initialDelay: 1, maxDelay: 5)
        XCTAssertEqual((0..<5).map { _ in backoff.recordFailure() }, [1, 2, 4, 5, 5])
    }

    func testErrorCodeForTheLogCarriesNoDescriptionOrUserInfo() {
        let error = NSError(
            domain: "Test", code: 7,
            userInfo: [NSLocalizedDescriptionKey: "Quarterly-report.xlsx", NSFilePathErrorKey: "/Users/someone/Quarterly-report.xlsx"]
        )
        XCTAssertEqual(AgentLog.code(of: error), "Test 7")
        XCTAssertEqual(AgentLog.code(of: URLError(.cannotConnectToHost)), "NSURLErrorDomain -1004")
    }

    // MARK: Store

    func testIntervalsCommittedBeforeAKillAreThereAfterTheRestart() async throws {
        let store = try makeStore()
        store.enqueue(intervals(7))

        // A kill leaves the files as they are at that moment: copy them while the
        // store is still open and never closed, then start a new process on the copy.
        let afterKill = root.appendingPathComponent("after-kill", isDirectory: true)
        try FileManager.default.copyItem(at: directory, to: afterKill)

        let restarted = try OutboxStore(directory: afterKill)
        XCTAssertEqual(restarted.count, 7)
        var sent: [ActivityInterval] = []
        await makeFlusher(restarted) { sent += $0 }.flush(now: start)
        XCTAssertEqual(sent, intervals(7))
        XCTAssertEqual(restarted.count, 0)
    }

    func testStoreReopenedAfterACleanCloseKeepsIntervalsInOrder() throws {
        var store: OutboxStore? = try makeStore()
        store?.enqueue(intervals(3, from: 5) + intervals(3))
        store = nil
        let reopened = try makeStore()
        XCTAssertEqual(reopened.nextBatch()?.intervals, intervals(3) + intervals(3, from: 5))
    }

    func testInMemoryStoresShareNothing() throws {
        var first: OutboxStore? = try OutboxStore(directory: nil)
        first?.enqueue(intervals(2))
        XCTAssertEqual(first?.count, 2)
        first = nil
        XCTAssertEqual(try OutboxStore(directory: nil).count, 0)
    }

    func testUnwritableDirectoryFallsBackToAnInMemoryQueue() throws {
        let locked = directory.appendingPathComponent("locked", isDirectory: true)
        try FileManager.default.createDirectory(at: locked, withIntermediateDirectories: true)
        try FileManager.default.setAttributes([.posixPermissions: 0o500], ofItemAtPath: locked.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: locked.path) }
        let target = locked.appendingPathComponent("agent", isDirectory: true)

        XCTAssertThrowsError(try OutboxStore(directory: target))
        let store = try OutboxStore.openWithFallback(directory: target)
        XCTAssertFalse(store.isOnDisk)
        store.enqueue(intervals(2))
        XCTAssertEqual(store.count, 2)
        XCTAssertFalse(FileManager.default.fileExists(atPath: target.path))
    }

    func testExcludedBundleNeverEntersTheQueue() throws {
        let own = "com.talvior.HabitAgent"
        let store = try makeStore(excluding: [own])
        store.enqueue(intervals(1, bundleID: own) + intervals(1, from: 1))
        XCTAssertEqual(store.nextBatch()?.intervals.map(\.bundleID), ["com.example.editor"])
    }

    func testIntervalOlderThanTwoWeeksIsDroppedWithItsCodeAndTheCodeSurvivesARestart() throws {
        var store: OutboxStore? = try makeStore()
        let now = start.addingTimeInterval(OutboxStore.retention)
        // Ends one second past the limit; the neighbour ends exactly on it and stays.
        let tooOld = ActivityInterval(
            bundleID: "com.example.editor", startedAt: start.addingTimeInterval(-60), endedAt: start.addingTimeInterval(-1),
            localDate: "2027-01-15", utcOffsetMinutes: 0, switchCount: 0
        )
        let onTheLimit = ActivityInterval(
            bundleID: "com.example.editor", startedAt: start.addingTimeInterval(-60), endedAt: start,
            localDate: "2027-01-15", utcOffsetMinutes: 0, switchCount: 0
        )
        store?.enqueue([tooOld, onTheLimit])
        XCTAssertNil(store?.lastError)

        XCTAssertEqual(store?.dropExpired(now: now), 1)
        XCTAssertEqual(store?.count, 1)
        XCTAssertEqual(store?.lastError, QueueError(code: .expired, count: 1, at: now))

        store = nil
        XCTAssertEqual(try makeStore().lastError?.code, .expired)
    }

    func testDroppingNothingLeavesThePreviousCodeAlone() throws {
        let store = try makeStore()
        store.enqueue(intervals(1))
        XCTAssertEqual(store.dropExpired(now: start), 0)
        XCTAssertNil(store.lastError)
    }

    func testEveryPathTheAgentBuildsLivesUnderItsOwnApplicationSupportDirectory() throws {
        let applicationSupport = try XCTUnwrap(
            FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
        )
        let own = applicationSupport.appendingPathComponent("com.talvior.habitagent", isDirectory: true)
        XCTAssertEqual(AgentPaths.directory.standardizedFileURL.path, own.standardizedFileURL.path)
        XCTAssertEqual(AgentPaths.queueStore.deletingLastPathComponent().standardizedFileURL.path, own.standardizedFileURL.path)
        XCTAssertFalse(AgentPaths.queueStore.path.contains("/Documents/"))
    }

    func testTheStoreWritesNothingOutsideTheDirectoryItWasGiven() throws {
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: root.path), [])
        let store = try makeStore()
        store.enqueue(intervals(3))
        _ = store.nextBatch()
        // The root belongs to this test alone, so anything next to the given directory came from the store.
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: root.path), [directory.lastPathComponent])
        XCTAssertFalse(try FileManager.default.contentsOfDirectory(atPath: directory.path).isEmpty)
        XCTAssertTrue(store.isOnDisk)
        let permissions = try FileManager.default.attributesOfItem(atPath: directory.path)[.posixPermissions] as? Int
        XCTAssertEqual(permissions, AgentPaths.directoryPermissions)
    }

    // MARK: Flusher

    func testBatchesAreCutAtFiveHundredSoTwelveHundredGoInThree() async throws {
        let store = try makeStore()
        store.enqueue(intervals(1200))
        var sizes: [Int] = []
        let summary = await makeFlusher(store) { sizes.append($0.count) }.flush(now: start)
        XCTAssertEqual(sizes, [500, 500, 200])
        XCTAssertEqual(summary?.sent, 1200)
        XCTAssertEqual(store.count, 0)
    }

    func testNetworkErrorKeepsTheIntervalsAndTheRetryResendsTheSameBatch() async throws {
        let store = try makeStore()
        store.enqueue(intervals(5))
        var batches: [[ActivityInterval]] = []
        var reachable = false
        let flusher = makeFlusher(store) { batch in
            batches.append(batch)
            if !reachable { throw URLError(.networkConnectionLost) }
        }

        let failed = await flusher.flush(now: start)
        XCTAssertEqual(failed?.failed, true)
        XCTAssertEqual(store.count, 5)

        reachable = true
        let sent = await flusher.flush(now: flusher.retryNotBefore)
        XCTAssertEqual(sent?.sent, 5)
        XCTAssertEqual(batches.count, 2)
        XCTAssertEqual(batches[0], batches[1])
        XCTAssertEqual(store.count, 0)
    }

    func testRegularFlushWaitsOutTheBackoffButAForcedOneDoesNot() async throws {
        let store = try makeStore()
        store.enqueue(intervals(2))
        var calls = 0
        var reachable = false
        let flusher = makeFlusher(store) { _ in
            calls += 1
            if !reachable { throw URLError(.cannotConnectToHost) }
        }

        await flusher.flush(now: start)
        let nextTick = await flusher.flush(now: start.addingTimeInterval(Backoff.initialDelay - 1))
        XCTAssertNil(nextTick)
        XCTAssertEqual(calls, 1)

        reachable = true
        let forced = await flusher.flush(force: true, now: start.addingTimeInterval(1))
        XCTAssertEqual(forced?.sent, 2)
        XCTAssertEqual(calls, 2)
    }

    func testTheGapBetweenAttemptsGrowsToTheCeilingWhileTheServerIsDown() async throws {
        let store = try makeStore()
        store.enqueue(intervals(1))
        let flusher = makeFlusher(store) { _ in throw URLError(.cannotConnectToHost) }

        // Thirty minutes of a dead server, attempt after attempt at the earliest moment allowed.
        var now = start
        var gaps: [TimeInterval] = []
        var attempts = 0
        while now.timeIntervalSince(start) < 30 * 60 {
            await flusher.flush(now: now)
            attempts += 1
            gaps.append(flusher.retryNotBefore.timeIntervalSince(now))
            now = flusher.retryNotBefore
        }
        XCTAssertEqual(gaps.prefix(7), [30, 60, 120, 240, 480, 600, 600])
        XCTAssertEqual(gaps.max(), Backoff.maxDelay)
        // Every second would be 1800 attempts; with the ceiling it is a handful.
        XCTAssertLessThan(attempts, 10)
        XCTAssertEqual(store.count, 1)
    }

    func testRestoredNetworkFlushesAtOnceInsteadOfWaitingForTheBackoff() async throws {
        let store = try makeStore()
        store.enqueue(intervals(4))
        var calls = 0
        var reachable = false
        let flusher = makeFlusher(store) { _ in
            calls += 1
            if !reachable { throw URLError(.notConnectedToInternet) }
        }

        await flusher.flush(now: start)
        XCTAssertEqual(calls, 1)

        // While the path is down nothing is attempted and the backoff does not grow.
        await flusher.networkChanged(available: false)
        let whileDown = await flusher.flush(force: true, now: start.addingTimeInterval(5))
        XCTAssertNil(whileDown)
        XCTAssertEqual(calls, 1)

        reachable = true
        await flusher.networkChanged(available: true)
        XCTAssertEqual(calls, 2)
        XCTAssertEqual(store.count, 0)
    }

    // MARK: Error history

    func testEveryDropCodeKeepsItsOwnTallyNotJustTheLastOne() throws {
        var store: OutboxStore? = try makeStore()
        store?.enqueue(intervals(2, bundleID: "com.example.unknown"))
        store?.drop(bundleID: "com.example.unknown", at: start)
        store?.enqueue([ActivityInterval(
            bundleID: "com.example.editor", startedAt: start.addingTimeInterval(-60), endedAt: start.addingTimeInterval(-1),
            localDate: "2027-01-15", utcOffsetMinutes: 0, switchCount: 0
        )])
        let later = start.addingTimeInterval(OutboxStore.retention)
        XCTAssertEqual(store?.dropExpired(now: later), 1)
        // A second unknown app after an expiry must not erase the expiry from the history.
        store?.enqueue(intervals(3, bundleID: "com.example.other"))
        let latest = later.addingTimeInterval(60)
        store?.drop(bundleID: "com.example.other", at: latest)

        let expected = [
            QueueErrorTally(code: .expired, events: 1, intervals: 1, lastAt: later),
            QueueErrorTally(code: .unknownApp, events: 2, intervals: 5, lastAt: latest),
        ]
        XCTAssertEqual(store?.errorHistory, expected)
        XCTAssertEqual(store?.lastError, QueueError(code: .unknownApp, count: 3, at: latest))

        store = nil
        XCTAssertEqual(try makeStore().errorHistory, expected)
    }

    func testNoDropsMeansNoHistory() throws {
        XCTAssertTrue(try makeStore().errorHistory.isEmpty)
    }

    // MARK: Checkpoint and kill

    func testKillAfterAnHourInOneAppLosesLessThanTheCheckpointInterval() throws {
        var store: OutboxStore? = try makeStore()
        var builder: IntervalBuilder? = IntervalBuilder()
        let editor = "com.example.editor"
        var lastSighting = start
        for second in stride(from: 0.0, through: 3600, by: Self.samplingStep) {
            lastSighting = start.addingTimeInterval(second)
            let closed = builder!.record(AppSighting(bundleID: editor, date: lastSighting)) + builder!.checkpoint()
            store?.enqueue(closed)
        }
        // kill -9: neither the builder nor the store gets to finish anything.
        builder = nil
        store = nil

        let survivors = try makeStore().nextBatch()?.intervals ?? []
        let covered = try XCTUnwrap(survivors.map(\.endedAt).max())
        XCTAssertLessThan(lastSighting.timeIntervalSince(covered), IntervalBuilder.checkpointInterval)
        XCTAssertGreaterThan(covered.timeIntervalSince(start), 3600 - IntervalBuilder.checkpointInterval)
    }

    private static let samplingStep: TimeInterval = 5

    // MARK: Interfaces

    func testAnInterfaceJoiningAnAlreadyUpNetworkCancelsTheBackoffAndFlushes() async throws {
        let store = try makeStore()
        store.enqueue(intervals(2))
        var calls = 0
        var reachable = false
        let flusher = makeFlusher(store) { _ in
            calls += 1
            if !reachable { throw URLError(.cannotConnectToHost) }
        }
        await flusher.networkChanged(available: true, interfaces: ["en0"])
        XCTAssertEqual(calls, 0, "the first path only sets the baseline")
        await flusher.flush(now: start)
        XCTAssertEqual(calls, 1)

        // Tailscale comes up while Wi-Fi never went down: the path is satisfied throughout.
        reachable = true
        await flusher.networkChanged(available: true, interfaces: ["en0", "utun4"])
        XCTAssertEqual(calls, 2)
        XCTAssertEqual(store.count, 0)
    }

    func testTheSameInterfacesAgainDoNotCancelTheBackoff() async throws {
        let store = try makeStore()
        store.enqueue(intervals(2))
        var calls = 0
        let flusher = makeFlusher(store) { _ in
            calls += 1
            throw URLError(.cannotConnectToHost)
        }
        await flusher.networkChanged(available: true, interfaces: ["en0", "utun4"])
        await flusher.flush(now: start)
        await flusher.networkChanged(available: true, interfaces: ["utun4", "en0"])
        await flusher.networkChanged(available: true, interfaces: ["en0"])
        XCTAssertEqual(calls, 1)
    }

    func testExpiredIntervalsAreDroppedBeforeAnyAttemptIsMade() async throws {
        let store = try makeStore()
        store.enqueue(intervals(1))
        var calls = 0
        let flusher = makeFlusher(store) { _ in
            calls += 1
            throw URLError(.cannotConnectToHost)
        }
        await flusher.flush(now: start)

        let later = start.addingTimeInterval(OutboxStore.retention + 60)
        let summary = await flusher.flush(now: later)
        XCTAssertEqual(summary?.expired, 1)
        XCTAssertEqual(store.count, 0)
        XCTAssertEqual(store.lastError?.code, .expired)
        XCTAssertEqual(calls, 1)
    }

    func testFlushWhileAnotherIsInFlightSendsNothingAndKeepsLaterIntervals() async throws {
        let store = try makeStore()
        let first = intervals(3)
        store.enqueue(first)
        let gate = Gate()
        var batches: [[ActivityInterval]] = []
        // Only the first send is held open; a second one would return at once
        // and break the assertions instead of hanging the suite.
        let flusher = makeFlusher(store) { batch in
            batches.append(batch)
            if batches.count == 1 { await gate.wait() }
        }

        let running = Task { await flusher.flush(now: start) }
        while batches.isEmpty { await Task.yield() }
        let later = intervals(2, from: 3)
        store.enqueue(later)
        let concurrent = await flusher.flush(now: start)
        XCTAssertNil(concurrent)
        XCTAssertEqual(batches.count, 1)

        gate.open()
        let summary = await running.value
        XCTAssertEqual(batches.first, first)
        // Every interval is confirmed exactly once — none lost, none twice.
        XCTAssertEqual(batches.flatMap { $0 }, first + later)
        XCTAssertEqual(summary?.sent, 5)
        XCTAssertEqual(store.count, 0)
    }

    func testForcedFlushWaitsForTheSendInFlightInsteadOfRunningBesideIt() async throws {
        let store = try makeStore()
        store.enqueue(intervals(3))
        let gate = Gate()
        var batches: [[ActivityInterval]] = []
        var running = 0
        var mostAtOnce = 0
        let flusher = makeFlusher(store) { batch in
            running += 1
            mostAtOnce = max(mostAtOnce, running)
            batches.append(batch)
            if batches.count == 1 { await gate.wait() }
            running -= 1
        }

        let regular = Task { await flusher.flush(now: start) }
        while batches.isEmpty { await Task.yield() }
        store.enqueue(intervals(1, from: 3))
        let forced = Task { await flusher.flush(force: true, now: start) }
        await Task.yield()
        XCTAssertEqual(batches.count, 1)

        gate.open()
        _ = await regular.value
        _ = await forced.value
        XCTAssertEqual(batches.flatMap { $0 }, intervals(4))
        XCTAssertEqual(mostAtOnce, 1)
        XCTAssertEqual(store.count, 0)
    }

    func testUnknownAppIsDroppedWithItsCodeAndTheRestIsResent() async throws {
        let store = try makeStore()
        let unknown = "com.apple.finder"
        store.enqueue(intervals(2) + intervals(1, bundleID: unknown, from: 2))
        var batches: [[ActivityInterval]] = []
        let summary = await makeFlusher(store) { batch in
            batches.append(batch)
            if batch.contains(where: { $0.bundleID == unknown }) {
                throw AgentAPIError.unknownApp(bundleID: unknown)
            }
        }.flush(now: start)
        XCTAssertEqual(summary?.droppedBundles, [unknown])
        XCTAssertEqual(summary?.sent, 2)
        XCTAssertEqual(batches.map(\.count), [3, 2])
        XCTAssertEqual(store.count, 0)
        XCTAssertEqual(store.lastError, QueueError(code: .unknownApp, count: 1, at: start))

        store.enqueue(intervals(1, bundleID: unknown, from: 3))
        XCTAssertEqual(store.count, 0)
    }

    func testOneRefusedIntervalAmongFiveHundredIsTheOnlyOneDropped() async throws {
        let store = try makeStore()
        let all = intervals(500)
        let bad = all[217]
        store.enqueue(all)
        var accepted: [ActivityInterval] = []
        var calls = 0
        let summary = await makeFlusher(store) { batch in
            calls += 1
            if batch.contains(bad) { throw AgentAPIError.invalidBatch }
            accepted += batch
        }.flush(now: start)

        XCTAssertEqual(summary?.droppedInvalid, 1)
        XCTAssertEqual(summary?.sent, 499)
        XCTAssertEqual(accepted.count, 499)
        XCTAssertEqual(Set(accepted.map(\.startedAt)), Set(all.filter { $0 != bad }.map(\.startedAt)))
        XCTAssertEqual(store.count, 0)
        XCTAssertEqual(store.lastError, QueueError(code: .invalidBatch, count: 1, at: start))
        // Halving finds the culprit in about two sends per level, not one per interval.
        XCTAssertLessThan(calls, 25)
    }

    func testRefusedIntervalsSeparatedByAcceptedOnesAreAllDropped() async throws {
        let store = try makeStore()
        let all = intervals(40)
        let bad = [all[3], all[20], all[37]]
        store.enqueue(all)
        var accepted: [ActivityInterval] = []
        let summary = await makeFlusher(store) { batch in
            if batch.contains(where: bad.contains) { throw AgentAPIError.invalidBatch }
            accepted += batch
        }.flush(now: start)

        XCTAssertEqual(summary?.droppedInvalid, 3)
        XCTAssertEqual(summary?.failed, false)
        XCTAssertEqual(accepted.count, 37)
        XCTAssertEqual(store.count, 0)
    }

    /// A server that takes any batch without a bad interval; returns what it accepted and how often it was asked.
    private final class PickyServer {
        let bad: [ActivityInterval]
        private(set) var accepted: [ActivityInterval] = []
        private(set) var requests = 0

        init(bad: [ActivityInterval]) {
            self.bad = bad
        }

        func receive(_ batch: [ActivityInterval]) throws {
            requests += 1
            if batch.contains(where: bad.contains) { throw AgentAPIError.invalidBatch }
            accepted += batch
        }
    }

    func testBadIntervalsAtTheHeadDoNotHoldBackTheGoodOnesBehindThem() async throws {
        let store = try makeStore()
        let all = intervals(20)
        let server = PickyServer(bad: Array(all[0..<3]))
        store.enqueue(all)
        let summary = await makeFlusher(store) { try server.receive($0) }.flush(now: start)

        XCTAssertEqual(summary?.failed, false)
        XCTAssertEqual(summary?.droppedInvalid, 3)
        XCTAssertEqual(Set(server.accepted.map(\.startedAt)), Set(all[3...].map(\.startedAt)))
        XCTAssertEqual(server.accepted.count, 17)
        XCTAssertEqual(summary?.sent, 17)
        XCTAssertEqual(store.count, 0)
        XCTAssertLessThan(server.requests, 60)
    }

    func testBadIntervalsInTheMiddleDoNotLeaveTheGoodOnesAfterThemStuck() async throws {
        let store = try makeStore()
        let all = intervals(20)
        let server = PickyServer(bad: Array(all[5..<8]))
        store.enqueue(all)
        let summary = await makeFlusher(store) { try server.receive($0) }.flush(now: start)

        XCTAssertEqual(summary?.failed, false)
        XCTAssertEqual(summary?.droppedInvalid, 3)
        XCTAssertEqual(server.accepted.count, 17)
        XCTAssertEqual(store.count, 0)
        XCTAssertEqual(store.lastError?.code, .invalidBatch)
    }

    func testBadIntervalsWithNothingAfterThemWaitForAcceptedOnesAndThenGoOn() async throws {
        let store = try makeStore()
        let all = intervals(3)
        let server = PickyServer(bad: all)
        store.enqueue(all)
        let flusher = makeFlusher(store) { try server.receive($0) }

        // Nothing else to ask the server with: it may be refusing everything, so the last one stays.
        let first = await flusher.flush(now: start)
        XCTAssertEqual(first?.failed, true)
        XCTAssertEqual(store.count, 1)

        let fresh = intervals(2, from: 10)
        store.enqueue(fresh)
        let second = await flusher.flush(now: flusher.retryNotBefore)
        XCTAssertEqual(second?.failed, false)
        XCTAssertEqual(second?.droppedInvalid, 1)
        // The newest goes first, as the probe.
        XCTAssertEqual(Set(server.accepted.map(\.startedAt)), Set(fresh.map(\.startedAt)))
        XCTAssertEqual(server.accepted.count, 2)
        XCTAssertEqual(store.count, 0)
    }

    func testServerRefusingEverythingCostsAtMostAFewIntervalsAndThenBacksOff() async throws {
        let store = try makeStore()
        store.enqueue(intervals(600))
        var calls = 0
        let flusher = makeFlusher(store) { _ in
            calls += 1
            throw AgentAPIError.invalidBatch
        }

        // Several passes, each at the earliest moment the backoff allows: a version
        // mismatch must not eat the queue one pass at a time.
        var now = start
        for _ in 0..<5 {
            let summary = await flusher.flush(now: now)
            XCTAssertEqual(summary?.failed, true)
            XCTAssertGreaterThan(flusher.retryNotBefore, now)
            now = flusher.retryNotBefore
        }
        let lost = 600 - store.count
        XCTAssertLessThanOrEqual(lost, Flusher.maxLoneRefusals)
        XCTAssertEqual(lost, Flusher.maxLoneRefusals - 1)
        XCTAssertEqual(store.lastError?.code, .invalidBatch)
        XCTAssertLessThan(calls, 100)
    }

    func testNothingIsAttemptedWithoutASender() async throws {
        let store = try makeStore()
        store.enqueue(intervals(2))
        let summary = await Flusher(store: store, sender: { nil }).flush(now: start)
        XCTAssertNil(summary)
        XCTAssertEqual(store.count, 2)
    }

    // MARK: Through the real client

    func testDroppedConnectionInTheMiddleOfABatchRepeatsThatBatchThroughTheRealClient() async throws {
        let store = try makeStore()
        store.enqueue(intervals(3))
        var bodies: [Data] = []
        var requests: [URLRequest] = []
        StubServer.handler = { request, body in
            requests.append(request)
            bodies.append(body)
            if bodies.count == 1 { throw URLError(.networkConnectionLost) }
            return 201
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubServer.self]
        let client = AgentAPIClient(
            serverAddress: "http://localhost:8000", apiKey: "test-key", session: URLSession(configuration: configuration)
        )
        let flusher = makeFlusher(store) { try await client.send($0) }

        let failed = await flusher.flush(now: start)
        XCTAssertEqual(failed?.failed, true)
        XCTAssertEqual(store.count, 3)

        let sent = await flusher.flush(now: flusher.retryNotBefore)
        XCTAssertEqual(sent?.sent, 3)
        XCTAssertEqual(bodies.count, 2)
        // The same batch, not merely the same size: JSON key order is not stable between encodes, the content is.
        let resent = try bodies.map { try JSONSerialization.jsonObject(with: $0) as? NSDictionary }
        XCTAssertNotNil(resent[0])
        XCTAssertEqual(resent[0], resent[1])
        XCTAssertEqual((resent[0]?["intervals"] as? [Any])?.count, 3)
        XCTAssertEqual(requests.last?.url?.path, "/api/v1/agent/activity")
        XCTAssertEqual(requests.last?.value(forHTTPHeaderField: "X-API-Key"), "test-key")
        XCTAssertEqual(store.count, 0)
    }
}
