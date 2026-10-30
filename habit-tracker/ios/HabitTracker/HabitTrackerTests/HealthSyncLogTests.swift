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
        XCTAssertEqual(day.longestInterval, 13 * 3600)
        XCTAssertEqual(day.lastArrival, entries.last?.at)

        let week = HealthSyncLogMath.summary(entries, window: HealthSyncLogMath.week, now: now)
        XCTAssertEqual(week.arrivals, 5)
        XCTAssertEqual(week.longestInterval, 80 * 3600)
    }

    func testSummaryWithoutArrivalsIsHonestlyEmpty() {
        let summary = HealthSyncLogMath.summary([entry(0, .skipped)], window: HealthSyncLogMath.day, now: Self.t0)

        XCTAssertEqual(summary, HealthSyncLogSummary(arrivals: 0, medianInterval: nil, longestInterval: nil, lastArrival: nil))
    }

    func testTheStoredFileHoldsNoMetricValue() throws {
        let log = makeLog()
        log.record(.sent([HealthSamplesResponseDTO(samplesReceived: 42, bucketsWritten: 7)]), source: .manual, at: Self.t0)
        log.record(.failed(.readFailed), source: .appLaunch, at: Self.t0)

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
        log.record(.sent([HealthSamplesResponseDTO(samplesReceived: 1, bucketsWritten: 1)]), source: .backgroundWake, at: Self.t0)

        XCTAssertEqual(makeLog().entries.first?.source, .backgroundWake)
        XCTAssertEqual(makeLog().entries.first?.kind, .rolling)
    }

    // MARK: - The pump writes its end into the journal

    func testThePumpRecordsASuccessAndARefusal() async {
        let store = FakeHealthStore()
        let api = FakeHealthAPI()
        store.hourSums[.stepCount] = [FakeHealthStore.hour(1200, "2026-10-19T06:00:00Z")]
        api.script = [.success(HealthSamplesResponseDTO(samplesReceived: 1, bucketsWritten: 1)), .failure(APIClientError.unauthorized)]
        let log = makeLog()
        let pump = HealthPump(store: store, api: { api }, pendingFailures: InMemoryPendingFailures())
        pump.syncLog = log

        _ = await pump.sync()
        _ = await pump.syncIfAuthorized()

        XCTAssertEqual(log.entries.map(\.outcome), [.ok, .failed(.unauthorized)])
        XCTAssertEqual(log.entries.map(\.source), [.manual, .appLaunch])
    }
}
