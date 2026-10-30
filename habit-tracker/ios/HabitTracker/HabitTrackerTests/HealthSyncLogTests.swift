// [review:need-review] PHASE-03/273
// summary: the sync journal — ring buffer that survives a restart and evicts the oldest, arrival intervals and day/week summary with pauses, no metric value in the stored file, a background-wake source that can be written, and the pump recording its end for success and refusal
import HealthKit
import XCTest
@testable import HabitTracker

@MainActor
final class HealthSyncLogTests: XCTestCase {
    private var dir: URL!
    private var url: URL { dir.appendingPathComponent("log.json") }
    private static let t0 = Date(timeIntervalSince1970: 1_800_000_000)

    override func setUp() {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: dir)
    }

    private func entry(
        _ minutes: Double, _ outcome: HealthSyncLogOutcome = .ok, source: HealthSyncSource = .appLaunch
    ) -> HealthSyncLogEntry {
        HealthSyncLogEntry(
            id: UUID(), at: Self.t0.addingTimeInterval(minutes * 60), source: source,
            kind: .rolling, samples: 5, chunks: 1, outcome: outcome
        )
    }

    private func makeLog(capacity: Int = HealthSyncLog.capacity) -> HealthSyncLog {
        HealthSyncLog(store: FileHealthSyncLogStore(url: url), capacity: capacity)
    }

    func testEntriesSurviveARestart() {
        let first = makeLog()
        first.append(entry(0))
        first.append(entry(10, .failed(.network), source: .manual))

        let reopened = makeLog()

        XCTAssertEqual(reopened.entries, first.entries)
        XCTAssertEqual(reopened.entries.count, 2)
    }

    func testTheOldestEntriesAreEvictedAtCapacity() {
        let log = makeLog(capacity: 3)
        let all = (0..<5).map { entry(Double($0)) }
        all.forEach(log.append)

        XCTAssertEqual(log.entries, Array(all.suffix(3)))
        XCTAssertEqual(makeLog(capacity: 3).entries, Array(all.suffix(3)))
    }

    func testTheDefaultBufferHoldsFiveHundred() {
        XCTAssertEqual(HealthSyncLog.capacity, 500)
    }

    func testIntervalsCountOnlyArrivalsAndShowPauses() {
        let entries = [
            entry(0), entry(10, .failed(.network)), entry(30, .skipped), entry(60), entry(65, .nothingToSend), entry(180),
        ]

        XCTAssertEqual(HealthSyncLogMath.intervals(entries), [3600, 7200])
        let gaps = HealthSyncLogMath.gapsBeforeArrivals(entries)
        XCTAssertNil(gaps[entries[0].id])
        XCTAssertEqual(gaps[entries[3].id], 3600)
        XCTAssertEqual(gaps[entries[5].id], 7200)
    }

    func testSummaryHasMedianLongestAndLastArrivalInTheWindow() {
        let now = Self.t0.addingTimeInterval(10 * 24 * 3600)
        let hoursAgo: (Double) -> HealthSyncLogEntry = { h in
            HealthSyncLogEntry(
                id: UUID(), at: now.addingTimeInterval(-h * 3600), source: .appLaunch,
                kind: .rolling, samples: 1, chunks: 1, outcome: .ok
            )
        }
        let entries = [hoursAgo(100), hoursAgo(20), hoursAgo(19), hoursAgo(15), hoursAgo(2)]

        let day = HealthSyncLogMath.summary(entries, window: HealthSyncLogMath.day, now: now)
        XCTAssertEqual(day.arrivals, 4)
        XCTAssertEqual(day.medianInterval, 4 * 3600)
        XCTAssertEqual(day.longestInterval, 80 * 3600, "the pause across the window edge counts")
        XCTAssertEqual(day.lastArrival, entries.last?.at)
        XCTAssertEqual(day.openInterval, 2 * 3600)

        let week = HealthSyncLogMath.summary(entries, window: HealthSyncLogMath.week, now: now)
        XCTAssertEqual(week.arrivals, 5)
        XCTAssertEqual(week.longestInterval, 80 * 3600)
    }

    func testSummaryWithoutArrivalsIsHonestlyEmpty() {
        let summary = HealthSyncLogMath.summary([entry(0, .skipped)], window: HealthSyncLogMath.day, now: Self.t0)

        XCTAssertEqual(summary, HealthSyncLogSummary(arrivals: 0, medianInterval: nil, longestInterval: nil, lastArrival: nil, openInterval: nil))
    }

    func testTwoDaysWithoutDataShowUpAsTheLongestPause() {
        let now = Self.t0.addingTimeInterval(72 * 3600)
        let hourly = (0..<24).map { entry(Double($0) * 60) }

        let day = HealthSyncLogMath.summary(hourly, window: HealthSyncLogMath.day, now: now)

        XCTAssertEqual(day.arrivals, 0)
        XCTAssertEqual(day.openInterval, 49 * 3600)
        XCTAssertEqual(day.longestInterval, 49 * 3600)
        let week = HealthSyncLogMath.summary(hourly, window: HealthSyncLogMath.week, now: now)
        XCTAssertEqual(week.longestInterval, 49 * 3600)
        XCTAssertEqual(week.arrivals, 24)
    }

    func testABrokenEntryIsSkippedAndTheFileIsBackedUp() throws {
        let log = makeLog()
        log.append(entry(0))
        log.append(entry(10))
        var items = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [[String: Any]])
        items.insert(["junk": 1], at: 1)
        try JSONSerialization.data(withJSONObject: items).write(to: url)

        XCTAssertEqual(makeLog().entries.count, 2)
        XCTAssertTrue(FileManager.default.fileExists(atPath: url.appendingPathExtension("bak").path))
    }

    func testAnUnreadableFileIsBackedUpNotErased() throws {
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try Data("not json".utf8).write(to: url)
        let log = makeLog()

        XCTAssertTrue(log.entries.isEmpty)
        log.append(entry(0))

        XCTAssertEqual(try Data(contentsOf: url.appendingPathExtension("bak")), Data("not json".utf8))
        XCTAssertEqual(makeLog().entries.count, 1)
    }

    func testAMissingFileIsAnEmptyJournalWithoutBackup() {
        XCTAssertTrue(makeLog().entries.isEmpty)
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.appendingPathExtension("bak").path))
    }

    func testTheFileIsWrittenWithTheBackgroundFriendlyProtection() {
        XCTAssertTrue(FileHealthSyncLogStore.writeOptions.contains(.completeFileProtectionUntilFirstUserAuthentication))
        XCTAssertTrue(FileHealthSyncLogStore.writeOptions.contains(.atomic))
    }

    func testTheStoredFileHoldsNoMetricValue() throws {
        let log = makeLog()
        log.record(.sent([HealthSamplesResponseDTO(samplesReceived: 42, bucketsWritten: 7)]), source: .manual, kind: .manual, at: Self.t0)
        log.record(.failed(.readFailed), source: .appLaunch, kind: .rolling, at: Self.t0)

        let json = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [[String: Any]]
        let allowed: Set<String> = ["id", "at", "source", "kind", "samples", "chunks", "outcome"]
        XCTAssertEqual(json?.count, 2)
        for item in json ?? [] {
            XCTAssertTrue(Set(item.keys).isSubset(of: allowed), "\(item.keys)")
        }
        XCTAssertEqual(log.entries[0].samples, 42)
        XCTAssertEqual(log.entries[0].chunks, 1)
        XCTAssertEqual(log.entries[0].kind, .manual)
    }

    func testABackgroundWakeCanBeWritten() {
        let log = makeLog()
        log.record(.sent([HealthSamplesResponseDTO(samplesReceived: 1, bucketsWritten: 1)]), source: .backgroundWake, kind: .rolling, at: Self.t0)

        XCTAssertEqual(makeLog().entries.first?.source, .backgroundWake)
        XCTAssertEqual(makeLog().entries.first?.kind, .rolling)
    }

    // MARK: - The pump writes its end into the journal

    func testThePumpRecordsASuccessAndARefusal() async {
        let store = FakeHealthStore()
        let api = FakeHealthAPI()
        store.hourSums[.stepCount] = [FakeHealthStore.hour(1200, "2026-10-19T06:00:00Z")]
        api.script = [.success(HealthSamplesResponseDTO(samplesReceived: 1, bucketsWritten: 1)), .failure(APIClientError.unauthorized)]
        let log = HealthSyncLog(store: InMemoryHealthSyncLogStore())
        let pump = HealthPump(store: store, api: { api }, syncLog: log, pendingFailures: InMemoryPendingFailures())

        _ = await pump.sync()
        _ = await pump.syncIfAuthorized()

        XCTAssertEqual(log.entries.map(\.outcome), [.ok, .failed(.unauthorized)])
        XCTAssertEqual(log.entries.map(\.source), [.manual, .appLaunch])
        XCTAssertEqual(log.entries.map(\.kind), [.manual, .rolling])
    }

    func testTheSourceOfALaunchRunReachesTheJournal() async {
        let store = FakeHealthStore()
        let log = HealthSyncLog(store: InMemoryHealthSyncLogStore())
        let pump = HealthPump(store: store, api: { FakeHealthAPI() }, syncLog: log, pendingFailures: InMemoryPendingFailures())

        _ = await pump.syncIfAuthorized(source: .backgroundWake)

        XCTAssertEqual(log.entries.map(\.source), [.backgroundWake])
        XCTAssertEqual(log.entries.map(\.kind), [.rolling])
    }
}

final class InMemoryHealthSyncLogStore: HealthSyncLogStoring {
    private var stored: [HealthSyncLogEntry] = []
    func load() -> [HealthSyncLogEntry] { stored }
    func save(_ entries: [HealthSyncLogEntry]) { stored = entries }
}
