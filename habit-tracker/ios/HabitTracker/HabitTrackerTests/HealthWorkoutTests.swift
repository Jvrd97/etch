// [review:need-review] PHASE-02/70
// summary: workouts through the pump and the mapper — HKWorkout to its record (UUID, type, interval, active time) and the record to the DTO (UTC instants, the offset at the start, snake_case type name, numbers left out when HealthKit holds none, the body keys the server expects), a workout asked in the same sheet and read for the same window, packed as one unit with the quantity records, a launch run that reads it only once the sheet was answered for it, a denied workout type an empty list not a failed run, a workout across midnight kept whole, and the workout type among the types a background observer registers on
import HealthKit
import XCTest
@testable import HabitTracker

final class HealthWorkoutMappingTests: XCTestCase {
    private let berlin = TimeZone(identifier: "Europe/Berlin")!
    private let runUUID = UUID(uuidString: "5F1E0C2A-0000-4000-8000-000000000001")!

    private static func instant(_ text: String) -> Date {
        ISO8601DateFormatter().date(from: text)!
    }

    private func record(
        start: String = "2026-10-20T16:00:00Z", end: String = "2026-10-20T16:45:00Z",
        type: HKWorkoutActivityType = .running, zone: String? = nil
    ) -> HealthWorkoutRecord {
        HealthWorkoutRecord(
            uuid: runUUID, activityType: type, start: Self.instant(start), end: Self.instant(end),
            duration: 2700, energyKcal: 410.5, distanceM: 7200, avgHeartRate: 152, maxHeartRate: 178,
            timeZoneName: zone
        )
    }

    func testAnHKWorkoutBecomesARecordWithItsTypeAndInterval() {
        let workout = HKWorkout(
            activityType: .cycling,
            start: Self.instant("2026-10-20T16:00:00Z"), end: Self.instant("2026-10-20T17:00:00Z")
        )

        let record = HealthWorkoutRecord(workout)

        XCTAssertEqual(record.uuid, workout.uuid)
        XCTAssertEqual(record.activityType, .cycling)
        XCTAssertEqual(record.start, workout.startDate)
        XCTAssertEqual(record.end, workout.endDate)
        XCTAssertEqual(record.duration, 3600, accuracy: 0.001)
        // A workout without statistics has no numbers, not zeros.
        XCTAssertNil(record.energyKcal)
        XCTAssertNil(record.distanceM)
        XCTAssertNil(record.avgHeartRate)
        XCTAssertNil(record.maxHeartRate)
    }

    func testTheRecordMapsToTheWireShapeWithTheOffsetAtItsStart() {
        let dto = HealthSampleMapper(timeZone: berlin).dto(record())

        XCTAssertEqual(dto.uuid, "5F1E0C2A-0000-4000-8000-000000000001")
        XCTAssertEqual(dto.activityType, "running")
        XCTAssertEqual(dto.start, "2026-10-20T16:00:00.000Z")
        XCTAssertEqual(dto.end, "2026-10-20T16:45:00.000Z")
        XCTAssertEqual(dto.utcOffsetMinutes, 120)
        XCTAssertEqual(dto.durationSeconds, 2700)
        XCTAssertEqual(dto.energyKcal, 410.5)
        XCTAssertEqual(dto.distanceM, 7200)
        XCTAssertEqual(dto.avgHeartRate, 152)
        XCTAssertEqual(dto.maxHeartRate, 178)
    }

    func testTheOffsetIsTheOneAtTheStartAcrossTheDSTChange() {
        // Berlin leaves summer time at 03:00 on 2026-10-25: a night run starting at 00:30
        // (UTC+2, 22:30Z the day before) and ending after the change keeps its start's offset.
        let dto = HealthSampleMapper(timeZone: berlin).dto(
            record(start: "2026-10-24T22:30:00Z", end: "2026-10-25T02:30:00Z")
        )
        XCTAssertEqual(dto.utcOffsetMinutes, 120)
    }

    func testTheZoneTheWorkoutRecordedWinsOverTheDeviceZone() {
        let dto = HealthSampleMapper(timeZone: berlin).dto(record(zone: "Asia/Tokyo"))
        XCTAssertEqual(dto.utcOffsetMinutes, 540)
    }

    func testAnUnnamedActivityTypeGoesAsOther() {
        XCTAssertEqual(HealthWorkoutActivity.name(of: .running), "running")
        XCTAssertEqual(HealthWorkoutActivity.name(of: .cardioDance), "dance")
        XCTAssertEqual(HealthWorkoutActivity.name(of: .archery), HealthWorkoutActivity.other)
    }

    func testNumbersHealthKitDoesNotHoldAreLeftOutOfTheBodyNotSentAsZero() throws {
        let bare = HealthWorkoutRecord(
            uuid: runUUID, activityType: .yoga, start: Self.instant("2026-10-20T16:00:00Z"),
            end: Self.instant("2026-10-20T16:30:00Z"), duration: 1800
        )
        let dto = HealthSampleMapper(timeZone: berlin).dto(bare)
        let request = HealthSamplesRequestDTO(samples: [], workouts: [dto])

        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let body = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: encoder.encode(request)) as? [String: Any]
        )
        let workout = try XCTUnwrap((body["workouts"] as? [[String: Any]])?.first)

        XCTAssertEqual(
            Set(workout.keys),
            ["uuid", "activity_type", "start", "end", "utc_offset_minutes", "duration_seconds"]
        )
    }

    func testTheFullBodyUsesTheKeysTheServerExpects() throws {
        let dto = HealthSampleMapper(timeZone: berlin).dto(record())
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let json = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: encoder.encode(dto)) as? [String: Any]
        )
        XCTAssertEqual(
            Set(json.keys),
            [
                "uuid", "activity_type", "start", "end", "utc_offset_minutes", "duration_seconds",
                "energy_kcal", "distance_m", "avg_heart_rate", "max_heart_rate",
            ]
        )
    }
}

@MainActor
final class HealthWorkoutPumpTests: XCTestCase {
    private let berlin = TimeZone(identifier: "Europe/Berlin")!
    private var store: FakeHealthStore!
    private var api: FakeHealthAPI!

    /// Tuesday 2026-10-20, 14:00 in Berlin (UTC+2).
    private static let now = ISO8601DateFormatter().date(from: "2026-10-20T12:00:00Z")!
    private static let windowStart = ISO8601DateFormatter().date(from: "2026-10-13T22:00:00Z")!

    override func setUp() async throws {
        store = FakeHealthStore()
        api = FakeHealthAPI()
    }

    private func makePump(metrics: [HealthMetricDefinition] = []) -> HealthPump {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = berlin
        return HealthPump(
            store: store,
            api: { [api] in api },
            syncLog: HealthSyncLog(store: InMemoryHealthSyncLogStore()),
            metrics: metrics,
            categories: [],
            mapper: HealthSampleMapper(timeZone: berlin),
            calendar: calendar,
            now: { Self.now },
            deviceId: { "device" },
            makeRunId: { UUID() },
            pendingFailures: InMemoryPendingFailures(),
            pause: { _ in }
        )
    }

    private func workout(
        _ uuid: String, start: String, end: String, type: HKWorkoutActivityType = .running
    ) -> HealthWorkoutRecord {
        let formatter = ISO8601DateFormatter()
        let from = formatter.date(from: start)!
        let to = formatter.date(from: end)!
        return HealthWorkoutRecord(
            uuid: UUID(uuidString: uuid)!, activityType: type, start: from, end: to,
            duration: to.timeIntervalSince(from), energyKcal: 300
        )
    }

    func testAManualRunAsksForWorkoutsInTheSameSheet() async {
        _ = await makePump().sync()
        XCTAssertEqual(store.authorizationRequests, [[HealthWorkoutCatalog.identifier]])
    }

    func testWorkoutsOfTheWindowGoToTheServerAsEvents() async {
        store.workoutRecords = [
            workout("5F1E0C2A-0000-4000-8000-000000000001", start: "2026-10-19T16:00:00Z", end: "2026-10-19T16:45:00Z"),
            workout(
                "5F1E0C2A-0000-4000-8000-000000000002", start: "2026-10-20T05:00:00Z", end: "2026-10-20T06:00:00Z",
                type: .swimming
            ),
        ]

        let outcome = await makePump().sync()

        XCTAssertEqual(outcome, .sent([FakeHealthAPI.defaultReply]))
        XCTAssertEqual(api.posted.count, 1)
        XCTAssertEqual(api.posted[0].workouts.map(\.activityType), ["running", "swimming"])
        XCTAssertTrue(api.posted[0].samples.isEmpty)
        XCTAssertEqual(store.workoutQueries.count, 1)
        XCTAssertEqual(store.workoutQueries[0].from, Self.windowStart)
        XCTAssertEqual(store.workoutQueries[0].to, Self.now)
    }

    func testAWorkoutBeforeTheWindowIsNotRead() async {
        store.workoutRecords = [
            workout("5F1E0C2A-0000-4000-8000-000000000003", start: "2026-10-01T16:00:00Z", end: "2026-10-01T17:00:00Z"),
        ]

        let outcome = await makePump().sync()

        XCTAssertEqual(outcome, .nothingToSend)
        XCTAssertTrue(api.posted.isEmpty)
    }

    func testAWorkoutAcrossMidnightGoesOnceUnderItsStartOffset() async {
        // 23:30 to 00:30 in Berlin: one entry, not two halves.
        store.workoutRecords = [
            workout("5F1E0C2A-0000-4000-8000-000000000004", start: "2026-10-19T21:30:00Z", end: "2026-10-19T22:30:00Z"),
        ]

        _ = await makePump().sync()

        let sent = api.posted.flatMap(\.workouts)
        XCTAssertEqual(sent.count, 1)
        XCTAssertEqual(sent[0].start, "2026-10-19T21:30:00.000Z")
        XCTAssertEqual(sent[0].end, "2026-10-19T22:30:00.000Z")
        XCTAssertEqual(sent[0].utcOffsetMinutes, 120)
    }

    func testTheSameWindowSentTwiceCarriesTheSameUUIDs() async {
        store.workoutRecords = [
            workout("5F1E0C2A-0000-4000-8000-000000000005", start: "2026-10-19T16:00:00Z", end: "2026-10-19T16:45:00Z"),
        ]
        let pump = makePump()

        _ = await pump.sync()
        _ = await pump.sync()

        XCTAssertEqual(api.posted.count, 2)
        XCTAssertEqual(api.posted[0].workouts, api.posted[1].workouts)
    }

    func testALaunchBeforeTheSheetWasAnsweredForWorkoutsDoesNotReadThem() async {
        store.answered = [HKQuantityTypeIdentifier.stepCount.rawValue]
        store.hourSums[.stepCount] = [FakeHealthStore.hour(1200, "2026-10-19T06:00:00Z")]
        store.workoutRecords = [
            workout("5F1E0C2A-0000-4000-8000-000000000006", start: "2026-10-19T16:00:00Z", end: "2026-10-19T16:45:00Z"),
        ]
        let steps = HealthMetricCatalog.metrics.filter { $0.typeIdentifier == .stepCount }
        let pump = makePump(metrics: steps)

        _ = await pump.syncIfAuthorized()

        XCTAssertTrue(store.workoutQueries.isEmpty)
        XCTAssertTrue(store.authorizationRequests.isEmpty)
    }

    func testALaunchAfterTheSheetWasAnsweredForWorkoutsReadsThem() async {
        store.answered = [HealthWorkoutCatalog.identifier]
        store.workoutRecords = [
            workout("5F1E0C2A-0000-4000-8000-000000000007", start: "2026-10-19T16:00:00Z", end: "2026-10-19T16:45:00Z"),
        ]

        let outcome = await makePump().syncIfAuthorized()

        XCTAssertEqual(outcome, .sent([FakeHealthAPI.defaultReply]))
        XCTAssertEqual(api.posted.flatMap(\.workouts).count, 1)
        XCTAssertTrue(store.authorizationRequests.isEmpty)
    }

    func testADeniedWorkoutTypeIsAnEmptyListNotAFailedRun() async {
        store.typeErrors[HealthWorkoutCatalog.identifier] = HKError(.errorAuthorizationDenied)

        let outcome = await makePump().sync()

        XCTAssertEqual(outcome, .nothingToSend)
    }

    func testWorkoutsRideInTheSameChunkAsQuantityRecords() async {
        store.hourSums[.stepCount] = [FakeHealthStore.hour(1200, "2026-10-19T06:00:00Z")]
        store.workoutRecords = [
            workout("5F1E0C2A-0000-4000-8000-000000000008", start: "2026-10-19T16:00:00Z", end: "2026-10-19T16:45:00Z"),
        ]
        let steps = HealthMetricCatalog.metrics.filter { $0.typeIdentifier == .stepCount }
        let pump = makePump(metrics: steps)

        _ = await pump.sync()

        XCTAssertEqual(api.posted.count, 1)
        XCTAssertEqual(api.posted[0].samples.count, 1)
        XCTAssertEqual(api.posted[0].workouts.count, 1)
    }

    func testTheWorkoutTypeIsAmongTheTypesABackgroundObserverRegistersOn() {
        XCTAssertTrue(HealthPump.pumpedObjectTypes.contains(HealthWorkoutCatalog.objectType))
        XCTAssertEqual(
            HealthPump.pumpedObjectTypes.count,
            HealthPump.pumpedMetrics.count + HealthPump.pumpedCategories.count + 1
        )
    }
}
