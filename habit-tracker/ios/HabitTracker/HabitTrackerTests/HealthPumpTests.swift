// [review:need-review] PHASE-03/131, PHASE-03/234, PHASE-03/233, PHASE-03/254, PHASE-03/132
// summary: HealthPump on a fake HKHealthStore (raw samples and HealthKit hourly sums) and a fake API — read-only request, cumulative metrics as deduplicated hourly sums anchored at local midnight, discrete as samples, empty hours dropped, whole metrics per chunk, retry of transient failures only (never of an encoding failure), authorization failures named, one run for concurrent callers, a launch run that never shows the permission sheet, the sync-run bookkeeping on every chunk (one run id, kind, device id, position) and a dead run reported by class without inventing a success
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
    private static let deviceId = "device-under-test"
    private static let runId = UUID(uuidString: "3F6C1C52-0000-4000-8000-000000000001")!
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
            deviceId: { Self.deviceId },
            makeRunId: { Self.runId },
            chunkLimit: chunkLimit,
            pause: { [weak self] attempt in self?.pauses.append(attempt) }
        )
    }

    private func fillWeek() {
        store.hourSums[.stepCount] = [
            FakeHealthStore.hour(1200, "2026-10-19T06:00:00Z"),
            FakeHealthStore.hour(800, "2026-10-20T06:00:00Z"),
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
        XCTAssertEqual(store.sumQueries.map(\.type), [HKQuantityTypeIdentifier.stepCount.rawValue])
        XCTAssertEqual(store.queries.map(\.type), [HKQuantityTypeIdentifier.restingHeartRate.rawValue])
        XCTAssertTrue((store.queries + store.sumQueries).allSatisfy { $0.from == Self.windowStart && $0.to == Self.now })
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
        XCTAssertTrue(store.sumQueries.isEmpty)
        XCTAssertTrue(api.posted.isEmpty)
    }

    func testLaunchRunBeforeAnyRequestNeitherAsksNorReads() async {
        fillWeek()
        store.requestStatus = .shouldRequest

        let outcome = await makePump().syncIfAuthorized()

        XCTAssertEqual(outcome, .skipped)
        XCTAssertTrue(store.authorizationRequests.isEmpty)
        XCTAssertTrue(store.queries.isEmpty)
        XCTAssertTrue(store.sumQueries.isEmpty)
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

    func testEveryChunkCarriesTheRunItBelongsTo() async {
        fillWeek()

        _ = await makePump(chunkLimit: 2).sync()

        XCTAssertEqual(api.posted.map(\.syncRunId), Array(repeating: Self.runId.uuidString, count: 2))
        XCTAssertEqual(api.posted.map(\.chunkIndex), [0, 1])
        XCTAssertEqual(api.posted.map(\.chunksTotal), [2, 2])
        XCTAssertEqual(api.posted.map(\.deviceId), Array(repeating: Self.deviceId, count: 2))
        XCTAssertEqual(api.posted.map(\.kind), Array(repeating: .manual, count: 2))
    }

    func testLaunchRunIsRolling() async {
        fillWeek()
        store.requestStatus = .unnecessary

        _ = await makePump().syncIfAuthorized()

        XCTAssertEqual(api.posted.map(\.kind), [.rolling])
    }

    func testDeadNetworkRunIsReportedByClassAndStaysFailed() async {
        fillWeek()
        api.script = Array(repeating: .failure(APIClientError.timeout), count: HealthPump.maxAttempts)

        let outcome = await makePump().sync()

        XCTAssertEqual(outcome, .failed(.network))
        XCTAssertEqual(api.failureReports.map(\.runId), [Self.runId.uuidString])
        XCTAssertEqual(api.failureReports.map(\.report.failureKind), [.network])
        XCTAssertEqual(api.failureReports.map(\.report.kind), [.manual])
    }

    func testFailedReportOfADeadRunChangesNothing() async {
        fillWeek()
        api.script = Array(repeating: .failure(APIClientError.timeout), count: HealthPump.maxAttempts)
        api.failureReportError = APIClientError.timeout

        let outcome = await makePump().sync()

        XCTAssertEqual(outcome, .failed(.network))
        XCTAssertEqual(api.failureReports.count, 1)
    }

    func testSuccessAndServerSideRefusalsSendNoFailureReport() async {
        fillWeek()
        api.script = [.success(Self.accepted)]
        _ = await makePump().sync()

        api.script = [.failure(APIClientError.unexpectedStatus(422))]
        _ = await makePump().sync()

        XCTAssertTrue(api.failureReports.isEmpty)
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

    func testStepsGoOnlyThroughHourlySumsAsOneRecordEvenWhenPhoneAndWatchBothCounted() async {
        // Both devices recorded the same 1000 steps; HealthKit's statistics keep one
        // source per moment by priority, as the Health app does. Raw samples are not read.
        store.samples[.stepCount] = [
            FakeHealthStore.sample(.stepCount, 1000, .count(), "2026-10-20T06:00:00Z", "2026-10-20T06:40:00Z"),
            FakeHealthStore.sample(.stepCount, 1000, .count(), "2026-10-20T06:05:00Z", "2026-10-20T06:45:00Z"),
        ]
        store.hourSums[.stepCount] = [FakeHealthStore.hour(1000, "2026-10-20T06:00:00Z")]

        _ = await makePump().sync()

        let steps = api.posted.first?.samples.filter { $0.identifier == HKQuantityTypeIdentifier.stepCount.rawValue }
        XCTAssertEqual(steps?.map(\.value), [1000])
        XCTAssertEqual(steps?.first?.start, "2026-10-20T06:00:00.000Z")
        XCTAssertEqual(steps?.first?.end, "2026-10-20T07:00:00.000Z")
        XCTAssertFalse(store.queries.contains { $0.type == HKQuantityTypeIdentifier.stepCount.rawValue })
    }

    func testEmptyHoursOfTheWindowAreNotSent() async {
        store.hourSums[.stepCount] = [
            FakeHealthStore.hour(nil, "2026-10-20T05:00:00Z"),
            FakeHealthStore.hour(800, "2026-10-20T06:00:00Z"),
            FakeHealthStore.hour(nil, "2026-10-20T07:00:00Z"),
        ]

        _ = await makePump().sync()

        XCTAssertEqual(api.posted.first?.samples.map(\.start), ["2026-10-20T06:00:00.000Z"])
    }

    func testWindowOfOnlyEmptyHoursSendsNothing() async {
        store.hourSums[.stepCount] = [FakeHealthStore.hour(nil, "2026-10-20T06:00:00Z")]

        let outcome = await makePump().sync()

        XCTAssertEqual(outcome, .nothingToSend)
        XCTAssertTrue(api.posted.isEmpty)
    }

    func testEncodingFailureIsNotANetworkFailureAndIsNotRetried() async {
        fillWeek()
        let context = EncodingError.Context(codingPath: [], debugDescription: "non-finite value")
        api.script = [.failure(EncodingError.invalidValue(Double.nan, context))]

        let outcome = await makePump().sync()

        XCTAssertEqual(outcome, .failed(.encodingFailed))
        XCTAssertEqual(api.posted.count, 1)
        XCTAssertTrue(pauses.isEmpty)
    }

    func testFailedPermissionRequestIsNamedAndNotPassedOffAsMissingHealthData() async {
        fillWeek()
        store.authorizationError = HKError(.errorAuthorizationDenied)

        let manual = await makePump().sync()
        let launch = await makePump().syncIfAuthorized()

        XCTAssertEqual(manual, .failed(.authorizationFailed))
        XCTAssertEqual(launch, .failed(.authorizationFailed))
        XCTAssertTrue(api.posted.isEmpty)
    }

    func testHealthKitReportingNoHealthDataDuringTheRequestStaysUnavailable() async {
        store.authorizationError = HKError(.errorHealthDataUnavailable)

        let outcome = await makePump().sync()

        XCTAssertEqual(outcome, .failed(.healthDataUnavailable))
    }

    func testNoDataErrorOnTheStepWindowIsAnEmptyWeekNotAReadFailure() async {
        store.sumError = HKError(.errorNoData)
        store.samples[.restingHeartRate] = [
            FakeHealthStore.sample(.restingHeartRate, 54, HKUnit(from: "count/min"), "2026-10-20T03:00:00Z"),
        ]

        let withHeartRate = await makePump().sync()
        store.samples = [:]
        let withNothing = await makePump().sync()

        guard case .sent = withHeartRate else {
            return XCTFail("a window without steps must still send the heart rate, got \(withHeartRate)")
        }
        XCTAssertEqual(
            api.posted.first?.samples.map(\.identifier), ["HKQuantityTypeIdentifierRestingHeartRate"]
        )
        XCTAssertEqual(withNothing, .nothingToSend)
    }

    func testAnyOtherErrorOfTheStepWindowIsAReadFailure() async {
        store.sumError = HKError(.errorDatabaseInaccessible)

        let outcome = await makePump().sync()

        XCTAssertEqual(outcome, .failed(.readFailed))
        XCTAssertTrue(api.posted.isEmpty)
    }

    func testPumpBuiltWithoutZoneArgumentsFollowsTheDeviceZoneLive() {
        let pump = HealthPump(store: store, api: { nil })

        XCTAssertEqual(pump.calendar, Calendar.autoupdatingCurrent)
        XCTAssertNotEqual(pump.calendar, Calendar.current)
        XCTAssertEqual(pump.mapper.timeZone, TimeZone.autoupdatingCurrent)
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
///
/// `@unchecked Sendable`: the protocol is `Sendable` because the pump reads off the main
/// actor. The fake is built and scripted before a run, mutated by one run at a time, and
/// read by assertions after it ends; no test touches it from two tasks at once.
final class FakeHealthStore: HealthStoreQuerying, @unchecked Sendable {
    var available = true
    var requestStatus: HKAuthorizationRequestStatus = .unnecessary
    var samples: [HKQuantityTypeIdentifier: [HKQuantitySample]] = [:]
    /// What HKStatisticsCollectionQuery would hand back: already deduplicated across sources.
    var hourSums: [HKQuantityTypeIdentifier: [HealthHourSum]] = [:]
    var latest: [HKQuantityTypeIdentifier: HKQuantitySample] = [:]
    var readError: Error?
    /// Fails only the hourly-sum query; samples and the latest reading are unaffected.
    var sumError: Error?
    var authorizationError: Error?
    /// Yields inside every read so a second caller gets a turn mid-run.
    var suspendReads = false

    private(set) var authorizationRequests: [Set<String>] = []
    private(set) var statusChecks: [Set<String>] = []
    private(set) var queries: [(type: String, from: Date, to: Date)] = []
    private(set) var sumQueries: [(type: String, from: Date, to: Date)] = []

    var healthDataAvailable: Bool { available }

    func readAuthorizationRequestStatus(for types: Set<HKQuantityType>) async throws -> HKAuthorizationRequestStatus {
        statusChecks.append(Set(types.map(\.identifier)))
        if let authorizationError {
            throw authorizationError
        }
        return requestStatus
    }

    func requestReadAuthorization(for types: Set<HKQuantityType>) async throws {
        authorizationRequests.append(Set(types.map(\.identifier)))
        if let authorizationError {
            throw authorizationError
        }
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

    func hourlySums(of type: HKQuantityType, from: Date, to: Date) async throws -> [HealthHourSum] {
        sumQueries.append((type.identifier, from, to))
        if suspendReads {
            await Task.yield()
        }
        if let failure = sumError ?? readError {
            throw failure
        }
        return hourSums[HKQuantityTypeIdentifier(rawValue: type.identifier)] ?? []
    }

    func latestSample(of type: HKQuantityType) async throws -> HKQuantitySample? {
        if let readError {
            throw readError
        }
        return latest[HKQuantityTypeIdentifier(rawValue: type.identifier)]
    }

    private static let secondsPerHour: TimeInterval = 3600

    /// One hour of steps beginning at `start`; nil is an hour HealthKit has no data for.
    static func hour(_ steps: Double?, _ start: String) -> HealthHourSum {
        let begin = ISO8601DateFormatter().date(from: start)!
        return HealthHourSum(
            start: begin,
            end: begin.addingTimeInterval(secondsPerHour),
            sum: steps.map { HKQuantity(unit: .count(), doubleValue: $0) }
        )
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
    private(set) var failureReports: [(runId: String, report: HealthSyncFailureDTO)] = []
    var failureReportError: Error?

    func postHealthSamples(_ request: HealthSamplesRequestDTO) async throws -> HealthSamplesResponseDTO {
        posted.append(request)
        guard !script.isEmpty else {
            return Self.defaultReply
        }
        return try script.removeFirst().get()
    }

    func postHealthSyncFailure(runId: String, _ report: HealthSyncFailureDTO) async throws -> HealthSyncRunAckDTO {
        failureReports.append((runId, report))
        if let failureReportError {
            throw failureReportError
        }
        return HealthSyncRunAckDTO(status: "failed")
    }
}
