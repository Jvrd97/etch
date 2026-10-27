// [review:need-review] PHASE-03/131
// summary: HealthPump on a fake HKHealthStore and a fake API — read-only request, the 7-day window, whole metrics per chunk, retry of transient failures only, an identical body on re-send, one run for concurrent callers, a launch run that never shows the permission sheet
import HealthKit
import XCTest
@testable import HabitTracker

@MainActor
final class HealthPumpTests: XCTestCase {
    private let berlin = TimeZone(identifier: "Europe/Berlin")!
    private var store: FakeHealthStore!
    private var api: FakeHealthAPI!
    private var pauses: [Int] = []

    /// Tuesday 2026-10-20, 14:00 in Berlin (UTC+2).
    private static let now = instant("2026-10-20T12:00:00Z")
    /// Midnight in Berlin six days earlier: the window holds seven calendar days.
    private static let windowStart = instant("2026-10-13T22:00:00Z")
    private static let accepted = HealthSamplesResponseDTO(samplesReceived: 3, bucketsWritten: 3)

    override func setUp() async throws {
        store = FakeHealthStore()
        api = FakeHealthAPI()
        pauses = []
    }

    private static func instant(_ text: String) -> Date {
        ISO8601DateFormatter().date(from: text)!
    }

    private func makePump(chunkLimit: Int = HealthPump.maxSamplesPerChunk, configured: Bool = true) -> HealthPump {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = berlin
        let api = self.api!
        return HealthPump(
            store: store,
            api: { configured ? api : nil },
            mapper: HealthSampleMapper(timeZone: berlin),
            calendar: calendar,
            now: { Self.now },
            chunkLimit: chunkLimit,
            pause: { [weak self] attempt in self?.pauses.append(attempt) }
        )
    }

    private func fillWeek() {
        store.samples[.stepCount] = [
            FakeHealthStore.sample(.stepCount, 1200, .count(), "2026-10-19T06:50:00Z", "2026-10-19T07:30:00Z"),
            FakeHealthStore.sample(.stepCount, 800, .count(), "2026-10-20T06:00:00Z", "2026-10-20T06:20:00Z"),
        ]
        store.samples[.restingHeartRate] = [
            FakeHealthStore.sample(.restingHeartRate, 54, HKUnit(from: "count/min"), "2026-10-20T03:00:00Z"),
        ]
    }

    private var stepsAndRestingHeartRate: Set<String> {
        [HKQuantityTypeIdentifier.stepCount.rawValue, HKQuantityTypeIdentifier.restingHeartRate.rawValue]
    }

    func testManualSyncAsksReadOnlyAccessThenSendsTheWeekAsOneChunk() async {
        fillWeek()
        api.script = [.success(Self.accepted)]

        let outcome = await makePump().sync()

        XCTAssertEqual(outcome, .sent([Self.accepted]))
        XCTAssertEqual(store.authorizationRequests, [stepsAndRestingHeartRate])
        XCTAssertEqual(store.queries.map(\.type), [
            HKQuantityTypeIdentifier.stepCount.rawValue,
            HKQuantityTypeIdentifier.restingHeartRate.rawValue,
        ])
        XCTAssertTrue(store.queries.allSatisfy { $0.from == Self.windowStart && $0.to == Self.now })
        XCTAssertEqual(api.posted.count, 1)
        XCTAssertEqual(api.posted.first?.samples.map(\.identifier), [
            HKQuantityTypeIdentifier.stepCount.rawValue,
            HKQuantityTypeIdentifier.stepCount.rawValue,
            HKQuantityTypeIdentifier.restingHeartRate.rawValue,
        ])
        XCTAssertEqual(api.posted.first?.samples.first?.utcOffsetMinutes, 120)
    }

    func testEmptyWeekSendsNothingAndSaysSo() async {
        let outcome = await makePump().sync()

        XCTAssertEqual(outcome, .nothingToSend)
        XCTAssertTrue(api.posted.isEmpty)
    }

    func testNoServerAddressNeitherReadsNorSends() async {
        fillWeek()

        let outcome = await makePump(configured: false).sync()

        XCTAssertEqual(outcome, .notConfigured)
        XCTAssertTrue(store.queries.isEmpty)
        XCTAssertTrue(api.posted.isEmpty)
    }

    func testLaunchRunBeforeAnyRequestNeitherAsksNorReads() async {
        fillWeek()
        store.requestStatus = .shouldRequest

        let outcome = await makePump().syncIfAuthorized()

        XCTAssertEqual(outcome, .skipped)
        XCTAssertTrue(store.authorizationRequests.isEmpty)
        XCTAssertTrue(store.queries.isEmpty)
        XCTAssertTrue(api.posted.isEmpty)
    }

    func testLaunchRunAfterTheRequestSendsWithoutAsking() async {
        fillWeek()
        store.requestStatus = .unnecessary
        api.script = [.success(Self.accepted)]

        let outcome = await makePump().syncIfAuthorized()

        XCTAssertEqual(outcome, .sent([Self.accepted]))
        XCTAssertTrue(store.authorizationRequests.isEmpty)
        XCTAssertEqual(store.statusChecks, [stepsAndRestingHeartRate])
        XCTAssertEqual(api.posted.count, 1)
    }

    func testDeviceWithoutHealthDataFailsManualRunAndSkipsLaunchRun() async {
        store.available = false

        let manual = await makePump().sync()
        let launch = await makePump().syncIfAuthorized()

        XCTAssertEqual(manual, .failed(.healthDataUnavailable))
        XCTAssertEqual(launch, .skipped)
        XCTAssertTrue(store.authorizationRequests.isEmpty)
    }

    func testReadFailureStopsBeforeSending() async {
        fillWeek()
        store.readError = HKError(.errorDatabaseInaccessible)

        let outcome = await makePump().sync()

        XCTAssertEqual(outcome, .failed(.readFailed))
        XCTAssertTrue(api.posted.isEmpty)
    }

    func testMetricsArePackedWholeAndNeverSplitAcrossChunks() async {
        fillWeek()

        let outcome = await makePump(chunkLimit: 2).sync()

        XCTAssertEqual(outcome, .sent([FakeHealthAPI.defaultReply, FakeHealthAPI.defaultReply]))
        XCTAssertEqual(api.posted.map { $0.samples.map(\.identifier) }, [
            [HKQuantityTypeIdentifier.stepCount.rawValue, HKQuantityTypeIdentifier.stepCount.rawValue],
            [HKQuantityTypeIdentifier.restingHeartRate.rawValue],
        ])
    }

    func testMetricLargerThanAChunkFailsWithoutSendingAPart() async {
        fillWeek()

        let outcome = await makePump(chunkLimit: 1).sync()

        XCTAssertEqual(outcome, .failed(.chunkTooLarge))
        XCTAssertTrue(api.posted.isEmpty)
    }

    func testTransientFailuresAreRetriedWithTheSameChunk() async {
        fillWeek()
        api.script = [
            .failure(APIClientError.transport(code: NSURLErrorNetworkConnectionLost)),
            .failure(APIClientError.unexpectedStatus(503)),
            .success(Self.accepted),
        ]

        let outcome = await makePump().sync()

        XCTAssertEqual(outcome, .sent([Self.accepted]))
        XCTAssertEqual(api.posted.count, 3)
        XCTAssertEqual(Set(api.posted).count, 1)
        XCTAssertEqual(pauses, [1, 2])
    }

    func testRetriesStopAtTheBudget() async {
        fillWeek()
        api.script = Array(repeating: .failure(APIClientError.timeout), count: HealthPump.maxAttempts + 1)

        let outcome = await makePump().sync()

        XCTAssertEqual(outcome, .failed(.network))
        XCTAssertEqual(api.posted.count, HealthPump.maxAttempts)
    }

    func testRefusedChunkAndRejectedKeyAreNotRetried() async {
        fillWeek()
        api.script = [.failure(APIClientError.unexpectedStatus(422))]
        let refused = await makePump().sync()

        api.script = [.failure(APIClientError.unauthorized)]
        let rejectedKey = await makePump().sync()

        XCTAssertEqual(refused, .failed(.rejected))
        XCTAssertEqual(rejectedKey, .failed(.unauthorized))
        XCTAssertEqual(api.posted.count, 2)
        XCTAssertTrue(pauses.isEmpty)
    }

    func testResyncOfTheSameWeekSendsTheSameBody() async {
        fillWeek()
        let pump = makePump()

        _ = await pump.sync()
        _ = await pump.sync()

        XCTAssertEqual(api.posted.count, 2)
        XCTAssertEqual(api.posted[0], api.posted[1])
    }

    func testConcurrentCallersShareOneRun() async {
        fillWeek()
        store.suspendReads = true
        let pump = makePump()

        async let launch = pump.syncIfAuthorized()
        async let manual = pump.sync()
        let outcomes = await [launch, manual]

        XCTAssertEqual(outcomes[0], outcomes[1])
        XCTAssertEqual(api.posted.count, 1)
    }
}

// MARK: - Fakes

/// Stands in for `HKHealthStore`: scripted availability, request status and samples.
final class FakeHealthStore: HealthStoreQuerying {
    var available = true
    var requestStatus: HKAuthorizationRequestStatus = .unnecessary
    var samples: [HKQuantityTypeIdentifier: [HKQuantitySample]] = [:]
    var readError: Error?
    /// Yields inside every read so a second caller gets a turn mid-run.
    var suspendReads = false

    private(set) var authorizationRequests: [Set<String>] = []
    private(set) var statusChecks: [Set<String>] = []
    private(set) var queries: [(type: String, from: Date, to: Date)] = []

    var healthDataAvailable: Bool { available }

    func readAuthorizationRequestStatus(for types: Set<HKQuantityType>) async throws -> HKAuthorizationRequestStatus {
        statusChecks.append(Set(types.map(\.identifier)))
        return requestStatus
    }

    func requestReadAuthorization(for types: Set<HKQuantityType>) async throws {
        authorizationRequests.append(Set(types.map(\.identifier)))
    }

    func quantitySamples(of type: HKQuantityType, from: Date, to: Date) async throws -> [HKQuantitySample] {
        queries.append((type.identifier, from, to))
        if suspendReads {
            await Task.yield()
        }
        if let readError {
            throw readError
        }
        return samples[HKQuantityTypeIdentifier(rawValue: type.identifier)] ?? []
    }

    static func sample(
        _ type: HKQuantityTypeIdentifier, _ value: Double, _ unit: HKUnit, _ start: String, _ end: String? = nil
    ) -> HKQuantitySample {
        let formatter = ISO8601DateFormatter()
        return HKQuantitySample(
            type: HKQuantityType(type),
            quantity: HKQuantity(unit: unit, doubleValue: value),
            start: formatter.date(from: start)!,
            end: formatter.date(from: end ?? start)!
        )
    }
}

/// Records every posted chunk and answers from a script; an empty script accepts.
final class FakeHealthAPI: HealthSamplesAPI {
    static let defaultReply = HealthSamplesResponseDTO(samplesReceived: 0, bucketsWritten: 0)

    var script: [Result<HealthSamplesResponseDTO, Error>] = []
    private(set) var posted: [HealthSamplesRequestDTO] = []

    func postHealthSamples(_ request: HealthSamplesRequestDTO) async throws -> HealthSamplesResponseDTO {
        posted.append(request)
        guard !script.isEmpty else {
            return Self.defaultReply
        }
        return try script.removeFirst().get()
    }
}
