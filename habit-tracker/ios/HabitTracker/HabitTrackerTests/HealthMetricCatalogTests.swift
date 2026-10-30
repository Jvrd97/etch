// [review:need-review] PHASE-03/272
// summary: the whole-catalogue contract on the phone — no cycle-tracking type in the catalogue or in either permission sheet (pump, Health screen), every type asked in one sheet, a type without read access skipped while the others still go (pump and latest values), an hourly category type clipped to the window and a night not, an hourly interval ending at the window start not sent, a metric too large for a chunk journaled while steps and sleep go, a launch after the catalogue grew sending the types already allowed
import HealthKit
import XCTest
@testable import HabitTracker

@MainActor
final class HealthMetricCatalogTests: XCTestCase {
    /// The Cycle Tracking section, which the owner excluded (#272). The server pins the
    /// same list in `test_health_catalog_all_types.py`.
    private static let cycleTracking: Set<String> = [
        "HKCategoryTypeIdentifierMenstrualFlow",
        "HKCategoryTypeIdentifierIntermenstrualBleeding",
        "HKCategoryTypeIdentifierInfrequentMenstrualCycles",
        "HKCategoryTypeIdentifierIrregularMenstrualCycles",
        "HKCategoryTypeIdentifierPersistentIntermenstrualBleeding",
        "HKCategoryTypeIdentifierProlongedMenstrualPeriods",
        "HKCategoryTypeIdentifierOvulationTestResult",
        "HKCategoryTypeIdentifierCervicalMucusQuality",
        "HKCategoryTypeIdentifierProgesteroneTestResult",
        "HKCategoryTypeIdentifierPregnancyTestResult",
        "HKCategoryTypeIdentifierPregnancy",
        "HKCategoryTypeIdentifierLactation",
        "HKCategoryTypeIdentifierContraceptive",
        "HKCategoryTypeIdentifierSexualActivity",
        "HKCategoryTypeIdentifierBleedingDuringPregnancy",
        "HKCategoryTypeIdentifierBleedingAfterPregnancy",
        // Filed under reproductive health; the Health app shows it in Cycle Tracking.
        "HKQuantityTypeIdentifierBasalBodyTemperature",
    ]

    private static var catalogue: Set<String> {
        Set(HealthMetricCatalog.metrics.map(\.identifier) + HealthCategoryCatalog.categories.map(\.identifier))
    }

    /// Tuesday 2026-10-20, 14:00 in Berlin; the window opens at local midnight six days earlier.
    private static let now = instant("2026-10-20T12:00:00Z")
    private static let windowStart = instant("2026-10-13T22:00:00Z")
    private let berlin = TimeZone(identifier: "Europe/Berlin")!

    private static func instant(_ text: String) -> Date {
        ISO8601DateFormatter().date(from: text)!
    }

    private func makePump(
        store: FakeHealthStore, api: FakeHealthAPI,
        log: HealthSyncLog? = nil,
        chunkLimit: Int = HealthPump.maxSamplesPerChunk
    ) -> HealthPump {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = berlin
        return HealthPump(
            store: store,
            api: { api },
            syncLog: log ?? HealthSyncLog(store: InMemoryHealthSyncLogStore()),
            mapper: HealthSampleMapper(timeZone: berlin),
            calendar: calendar,
            now: { Self.now },
            pendingFailures: InMemoryPendingFailures(),
            chunkLimit: chunkLimit,
            pause: { _ in }
        )
    }

    func testNoCycleTrackingTypeIsInTheCatalogue() {
        XCTAssertTrue(Self.catalogue.isDisjoint(with: Self.cycleTracking))
        XCTAssertEqual(Self.catalogue.count, HealthMetricCatalog.metrics.count + HealthCategoryCatalog.categories.count)
    }

    func testThePumpAsksTheWholeCatalogueInOneSheetAndNoCycleTrackingType() async {
        let store = FakeHealthStore()

        _ = await makePump(store: store, api: FakeHealthAPI()).sync()

        XCTAssertEqual(store.authorizationRequests, [Self.catalogue])
        XCTAssertTrue(store.authorizationRequests.allSatisfy { $0.isDisjoint(with: Self.cycleTracking) })
    }

    func testTheHealthScreenAsksNoCycleTrackingType() async throws {
        let store = FakeHealthStore()
        let viewModel = HealthSyncViewModel(
            reader: HealthKitDataReader(store: store), syncer: makePump(store: store, api: FakeHealthAPI())
        )

        await viewModel.enterSection()

        XCTAssertEqual(store.authorizationRequests, [Self.catalogue])
        let reader = HealthKitDataReader(store: store)
        do {
            try await reader.requestReadAuthorization(for: ["HKCategoryTypeIdentifierMenstrualFlow"])
            XCTFail("a cycle-tracking type is not in the catalogue, so it cannot be asked")
        } catch HealthDataReaderError.unknownIdentifiers {
            XCTAssertEqual(store.authorizationRequests.count, 1)
        }
    }

    func testATypeWithoutReadAccessIsSkippedAndTheOthersStillGo() async {
        let store = FakeHealthStore()
        let api = FakeHealthAPI()
        store.hourSums[.stepCount] = [FakeHealthStore.hour(1200, "2026-10-19T06:00:00Z")]
        store.samples[.restingHeartRate] = [
            FakeHealthStore.sample(.restingHeartRate, 54, HKUnit(from: "count/min"), "2026-10-20T03:00:00Z"),
        ]
        store.typeErrors[HKQuantityTypeIdentifier.heartRate.rawValue] = HKError(.errorAuthorizationDenied)
        store.typeErrors[HKQuantityTypeIdentifier.activeEnergyBurned.rawValue] = HKError(.errorAuthorizationDenied)
        store.typeErrors[HKCategoryTypeIdentifier.sleepAnalysis.rawValue] = HKError(.errorAuthorizationNotDetermined)

        let outcome = await makePump(store: store, api: api).sync()

        XCTAssertEqual(outcome, .sent([FakeHealthAPI.defaultReply]))
        XCTAssertEqual(api.posted.flatMap(\.samples).map(\.identifier), [
            HKQuantityTypeIdentifier.stepCount.rawValue,
            HKQuantityTypeIdentifier.restingHeartRate.rawValue,
        ])
        // Every type was still tried: the refused ones did not end the run early.
        XCTAssertEqual(
            Set((store.queries + store.sumQueries + store.categoryQueries).map(\.type)),
            Self.catalogue
        )
    }

    func testABrokenReadOfOneTypeStillFailsTheRun() async {
        let store = FakeHealthStore()
        let api = FakeHealthAPI()
        store.hourSums[.stepCount] = [FakeHealthStore.hour(1200, "2026-10-19T06:00:00Z")]
        store.typeErrors[HKQuantityTypeIdentifier.heartRate.rawValue] = HKError(.errorDatabaseInaccessible)

        let outcome = await makePump(store: store, api: api).sync()

        XCTAssertEqual(outcome, .failed(.readFailed))
        XCTAssertTrue(api.posted.isEmpty)
    }

    func testLatestValuesSkipATypeWithoutReadAccess() async throws {
        let store = FakeHealthStore()
        store.latest[.restingHeartRate] = FakeHealthStore.sample(
            .restingHeartRate, 54, HKUnit(from: "count/min"), "2026-10-20T03:00:00Z"
        )
        store.typeErrors[HKQuantityTypeIdentifier.heartRate.rawValue] = HKError(.errorAuthorizationDenied)

        let values = try await HealthKitDataReader(store: store).readLatestValues(for: HealthMetricCatalog.metrics)

        XCTAssertEqual(values, [HKQuantityTypeIdentifier.restingHeartRate.rawValue: 54])
    }

    func testAnHourlyCategoryIsClippedToTheWindowAndANightIsNot() async throws {
        let store = FakeHealthStore()
        let api = FakeHealthAPI()
        let formatter = ISO8601DateFormatter()
        // A session from 23:50 the evening before the window to 00:20 inside it.
        store.categories[.mindfulSession] = [
            HKCategorySample(
                type: HKCategoryType(.mindfulSession), value: HKCategoryValue.notApplicable.rawValue,
                start: formatter.date(from: "2026-10-13T21:50:00Z")!, end: formatter.date(from: "2026-10-13T22:20:00Z")!
            ),
        ]
        // A nap from 17:00 to 19:00 the evening before: it belongs to the window's first night.
        store.categories[.sleepAnalysis] = [
            FakeHealthStore.sleep(.asleepCore, "2026-10-13T15:00:00Z", "2026-10-13T17:00:00Z"),
        ]

        _ = await makePump(store: store, api: api).sync()

        let sent = api.posted.flatMap(\.categorySamples)
        let session = try XCTUnwrap(sent.first { $0.identifier == HKCategoryTypeIdentifier.mindfulSession.rawValue })
        XCTAssertEqual(session.start, "2026-10-13T22:00:00.000Z")
        XCTAssertEqual(session.end, "2026-10-13T22:20:00.000Z")
        let nap = try XCTUnwrap(sent.first { $0.identifier == HKCategoryTypeIdentifier.sleepAnalysis.rawValue })
        XCTAssertEqual(nap.start, "2026-10-13T15:00:00.000Z")
        XCTAssertEqual(
            store.categoryQueries.first { $0.type == HKCategoryTypeIdentifier.mindfulSession.rawValue }?.from,
            Self.windowStart
        )
    }

    func testAnHourlyIntervalEndingAtTheWindowStartIsNotSent() async {
        let store = FakeHealthStore()
        let api = FakeHealthAPI()
        let formatter = ISO8601DateFormatter()
        // HealthKit selects by overlap, so the stand hour 23:00-00:00 right before the window comes back.
        store.categories[.appleStandHour] = [
            HKCategorySample(
                type: HKCategoryType(.appleStandHour), value: HKCategoryValueAppleStandHour.stood.rawValue,
                start: formatter.date(from: "2026-10-13T21:00:00Z")!, end: formatter.date(from: "2026-10-13T22:00:00Z")!
            ),
            HKCategorySample(
                type: HKCategoryType(.appleStandHour), value: HKCategoryValueAppleStandHour.stood.rawValue,
                start: formatter.date(from: "2026-10-13T22:00:00Z")!, end: formatter.date(from: "2026-10-13T23:00:00Z")!
            ),
        ]

        _ = await makePump(store: store, api: api).sync()

        let stood = api.posted.flatMap(\.categorySamples)
            .filter { $0.identifier == HKCategoryTypeIdentifier.appleStandHour.rawValue }
        XCTAssertEqual(stood.map(\.start), ["2026-10-13T22:00:00.000Z"])
    }

    func testAMetricTooLargeForAChunkIsJournaledAndStepsAndSleepStillGo() async {
        let store = FakeHealthStore()
        let api = FakeHealthAPI()
        let log = HealthSyncLog(store: InMemoryHealthSyncLogStore())
        store.hourSums[.stepCount] = [FakeHealthStore.hour(1200, "2026-10-19T06:00:00Z")]
        store.categories[.sleepAnalysis] = [
            FakeHealthStore.sleep(.asleepCore, "2026-10-19T21:30:00Z", "2026-10-20T01:00:00Z"),
        ]
        store.samples[.heartRate] = (0..<3).map { second in
            FakeHealthStore.sample(.heartRate, 60, HKUnit(from: "count/min"), "2026-10-20T03:00:0\(second)Z")
        }

        let outcome = await makePump(store: store, api: api, log: log, chunkLimit: 2).sync()

        XCTAssertEqual(outcome, .sent([FakeHealthAPI.defaultReply]))
        XCTAssertEqual(api.posted.flatMap(\.samples).map(\.identifier), [HKQuantityTypeIdentifier.stepCount.rawValue])
        XCTAssertEqual(api.posted.flatMap(\.categorySamples).count, 1)
        let skipped = log.entries.filter { $0.metric != nil }
        XCTAssertEqual(skipped.map(\.metric), [HKQuantityTypeIdentifier.heartRate.rawValue])
        XCTAssertEqual(skipped.map(\.outcome), [.failed(.chunkTooLarge)])
        XCTAssertEqual(log.entries.last?.outcome, .ok)
    }

    func testALaunchAfterTheCatalogueGrewStillSendsTheTypesAlreadyAllowed() async {
        let store = FakeHealthStore()
        let api = FakeHealthAPI()
        // The sheet of the previous release: steps and sleep, nothing the catalogue gained since.
        store.answered = [HKQuantityTypeIdentifier.stepCount.rawValue, HKCategoryTypeIdentifier.sleepAnalysis.rawValue]
        store.hourSums[.stepCount] = [FakeHealthStore.hour(1200, "2026-10-19T06:00:00Z")]
        store.categories[.sleepAnalysis] = [
            FakeHealthStore.sleep(.asleepCore, "2026-10-19T21:30:00Z", "2026-10-20T01:00:00Z"),
        ]

        let outcome = await makePump(store: store, api: api).syncIfAuthorized()

        XCTAssertEqual(outcome, .sent([FakeHealthAPI.defaultReply]))
        XCTAssertTrue(store.authorizationRequests.isEmpty)
        XCTAssertEqual(api.posted.flatMap(\.samples).map(\.identifier), [HKQuantityTypeIdentifier.stepCount.rawValue])
        XCTAssertEqual(api.posted.flatMap(\.categorySamples).count, 1)
        // Only the allowed types were read; the new ones wait for the Health screen's sheet.
        XCTAssertEqual(
            Set((store.queries + store.sumQueries + store.categoryQueries).map(\.type)),
            [HKQuantityTypeIdentifier.stepCount.rawValue, HKCategoryTypeIdentifier.sleepAnalysis.rawValue]
        )
    }
}
