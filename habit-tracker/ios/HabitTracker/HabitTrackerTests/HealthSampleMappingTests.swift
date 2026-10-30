// [review:need-review] PHASE-03/131, PHASE-03/234, PHASE-03/233, PHASE-03/254, PHASE-03/238, PHASE-03/272
// summary: the pump sends the whole catalogue, every type read in a unit HealthKit accepts for it, the catalogue equal to the server fixture (keys, kinds, units, category kind and unit); HKCategorySample (sleep) → HealthCategorySampleDTO with the raw stage, UTC instants and the offset at its end, the five-field shape and the sleep body the server fixture expects; HKQuantitySample and HealthKit hourly sums → HealthSampleDTO (HealthKit unit vs wire unit with % sent as fraction, UTC instants, the device offset per hour across midnight and DST, empty hours dropped), the six-field wire shape and the body the server fixture expects
import HealthKit
import XCTest
@testable import HabitTracker

final class HealthSampleMappingTests: XCTestCase {
    private let berlin = TimeZone(identifier: "Europe/Berlin")!
    private let steps = HealthSampleMappingTests.catalog(.stepCount)
    private let restingHeartRate = HealthSampleMappingTests.catalog(.restingHeartRate)

    private static func instant(_ text: String) -> Date {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: text)!
    }

    private static func sample(
        _ type: HKQuantityTypeIdentifier, _ value: Double, _ unit: HKUnit,
        start: String, end: String? = nil, metadata: [String: Any]? = nil
    ) -> HKQuantitySample {
        HKQuantitySample(
            type: HKQuantityType(type),
            quantity: HKQuantity(unit: unit, doubleValue: value),
            start: instant(start),
            end: instant(end ?? start),
            metadata: metadata
        )
    }

    func testThePumpSendsTheWholeCatalogue() {
        XCTAssertEqual(HealthPump.pumpedMetrics, HealthMetricCatalog.metrics)
        XCTAssertEqual(HealthPump.pumpedCategories, HealthCategoryCatalog.categories)
    }

    private static func hour(_ start: String, _ end: String, _ steps: Double?) -> HealthHourSum {
        HealthHourSum(
            start: instant(start), end: instant(end),
            sum: steps.map { HKQuantity(unit: .count(), doubleValue: $0) }
        )
    }

    private static func catalog(_ identifier: HKQuantityTypeIdentifier) -> HealthMetricDefinition {
        HealthMetricCatalog.metrics.first { $0.typeIdentifier == identifier }!
    }

    func testCatalogKindIsHealthKitsOwnAggregationStyle() {
        // HKStatisticsCollectionQuery refuses `.cumulativeSum` on a discrete type,
        // and the server folds the day by the same kind (`app/health/catalog.py`).
        for metric in HealthMetricCatalog.metrics {
            let healthKitSaysCumulative = HKQuantityType(metric.typeIdentifier).aggregationStyle == .cumulative
            XCTAssertEqual(metric.kind == .cumulative, healthKitSaysCumulative, metric.identifier)
        }
    }

    func testEveryPercentIsReadAsPercentAndSentAsFraction() {
        // Wire units against the server's table: `testCatalogKindsAndUnitsMatchTheServerFixture`.
        XCTAssertFalse(HealthMetricCatalog.metrics.contains { $0.wireUnit == "%" })
        let percents = HealthMetricCatalog.metrics.filter { $0.unit == "%" }
        XCTAssertTrue(percents.contains { $0.typeIdentifier == .oxygenSaturation })
        XCTAssertTrue(percents.allSatisfy { $0.wireUnit == "fraction" })
    }

    func testEveryTypeIsReadInAUnitHealthKitAcceptsForIt() {
        for metric in HealthMetricCatalog.metrics {
            XCTAssertTrue(
                HKQuantityType(metric.typeIdentifier).is(compatibleWith: HKUnit(from: metric.unit)),
                metric.identifier
            )
        }
    }

    func testMapperFollowsTheDeviceZoneWithoutARestart() {
        XCTAssertEqual(HealthSampleMapper().timeZone, TimeZone.autoupdatingCurrent)
        XCTAssertNotEqual(HealthSampleMapper().timeZone, TimeZone.current)
    }

    /// Kinds and canonical units from `services/backend/tests/fixtures/health/metric_catalog.json`,
    /// which `test_health_catalog_fixture.py` keeps equal to the server catalogue.
    func testCatalogKindsAndUnitsMatchTheServerFixture() throws {
        struct Row: Decodable {
            let identifier: String
            let kind: String
            let canonicalUnit: String
        }
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("services/backend/tests/fixtures/health/metric_catalog.json")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let rows = try decoder.decode([Row].self, from: Data(contentsOf: url))

        let categories = HealthCategoryCatalog.categories
        let onThisDevice = Set(HealthMetricCatalog.metrics.map(\.identifier) + categories.map(\.identifier))
        if #available(iOS 26.2, *) {
            XCTAssertEqual(Set(rows.map(\.identifier)), onThisDevice)
        } else {
            // An older system lacks the newest types; it must still carry nothing the server lacks.
            XCTAssertTrue(onThisDevice.isSubset(of: Set(rows.map(\.identifier))))
        }
        for row in rows where onThisDevice.contains(row.identifier) {
            if let category = categories.first(where: { $0.identifier == row.identifier }) {
                // A category type is sent raw; the server's kind and unit decide how it folds.
                XCTAssertEqual(category.serverKind, row.kind, row.identifier)
                XCTAssertEqual(category.serverUnit, row.canonicalUnit, row.identifier)
                continue
            }
            let metric = try XCTUnwrap(HealthMetricCatalog.metrics.first { $0.identifier == row.identifier })
            XCTAssertEqual(metric.kind == .cumulative, row.kind == "cumulative", row.identifier)
            // A percentage is read as HealthKit's fraction and labelled `fraction`; the server converts it.
            let expectedWireUnit = row.canonicalUnit == "%" ? "fraction" : row.canonicalUnit
            XCTAssertEqual(metric.wireUnit, expectedWireUnit, row.identifier)
        }
    }

    func testPercentIsReadAsTheFractionHealthKitHoldsAndSentAsFraction() {
        let mapper = HealthSampleMapper(timeZone: berlin)
        let saturation = Self.catalog(.oxygenSaturation)
        let reading = HKQuantitySample(
            type: HKQuantityType(.oxygenSaturation),
            quantity: HKQuantity(unit: .percent(), doubleValue: 0.97),
            start: Self.instant("2026-10-20T03:00:00.000Z"),
            end: Self.instant("2026-10-20T03:00:00.000Z")
        )

        let dto = mapper.dto(reading, metric: saturation)

        XCTAssertEqual(dto.unit, "fraction")
        XCTAssertEqual(dto.value, 0.97, accuracy: 1e-9)
        XCTAssertEqual(Self.catalog(.bodyFatPercentage).wireUnit, "fraction")
    }

    func testHourSumBecomesOneRecordSpanningTheWholeHour() {
        let mapper = HealthSampleMapper(timeZone: berlin)

        let dto = mapper.dto(
            Self.hour("2026-10-20T06:00:00.000Z", "2026-10-20T07:00:00.000Z", 1500), metric: steps
        )

        XCTAssertEqual(dto, HealthSampleDTO(
            identifier: "HKQuantityTypeIdentifierStepCount",
            value: 1500,
            unit: "count",
            start: "2026-10-20T06:00:00.000Z",
            end: "2026-10-20T07:00:00.000Z",
            utcOffsetMinutes: 120
        ))
    }

    func testEmptyHourSendsNothingRatherThanZero() {
        let mapper = HealthSampleMapper(timeZone: berlin)

        XCTAssertNil(mapper.dto(
            Self.hour("2026-10-20T06:00:00.000Z", "2026-10-20T07:00:00.000Z", nil), metric: steps
        ))
    }

    func testHoursOnBothSidesOfLocalMidnightStayWholeInTheirOwnDays() {
        let mapper = HealthSampleMapper(timeZone: berlin)
        // A walk 23:30-00:30 in Berlin: HealthKit has already split it at midnight.
        let late = mapper.dto(Self.hour("2026-10-19T21:00:00.000Z", "2026-10-19T22:00:00.000Z", 300), metric: steps)
        let early = mapper.dto(Self.hour("2026-10-19T22:00:00.000Z", "2026-10-19T23:00:00.000Z", 400), metric: steps)

        XCTAssertEqual(late?.end, "2026-10-19T22:00:00.000Z")
        XCTAssertEqual(early?.start, "2026-10-19T22:00:00.000Z")
        XCTAssertEqual([late?.value, early?.value], [300, 400])
        XCTAssertEqual([late?.utcOffsetMinutes, early?.utcOffsetMinutes], [120, 120])
    }

    func testRepeatedHourOfTheAutumnClockChangeCarriesBothOffsets() {
        let mapper = HealthSampleMapper(timeZone: berlin)
        // 2026-10-25: 03:00 CEST becomes 02:00 CET, the local hour 02 is lived twice.
        let summerTime = mapper.dto(Self.hour("2026-10-25T00:00:00.000Z", "2026-10-25T01:00:00.000Z", 10), metric: steps)
        let winterTime = mapper.dto(Self.hour("2026-10-25T01:00:00.000Z", "2026-10-25T02:00:00.000Z", 20), metric: steps)

        XCTAssertEqual(summerTime?.utcOffsetMinutes, 120)
        XCTAssertEqual(winterTime?.utcOffsetMinutes, 60)
    }

    func testValueIsReadInTheCatalogUnitWhateverUnitItWasStoredIn() {
        let mapper = HealthSampleMapper(timeZone: berlin)
        let perSecond = HKUnit.count().unitDivided(by: .second())
        let reading = Self.sample(.restingHeartRate, 1, perSecond, start: "2026-10-20T03:00:00.250Z")

        let dto = mapper.dto(reading, metric: restingHeartRate)

        XCTAssertEqual(dto.value, 60, accuracy: 1e-9)
        XCTAssertEqual(dto.unit, "count/min")
        XCTAssertEqual(dto.start, "2026-10-20T03:00:00.250Z")
        XCTAssertEqual(dto.end, dto.start)
    }

    func testOffsetIsTheDeviceOffsetAtTheSampleMomentNotNow() {
        let mapper = HealthSampleMapper(timeZone: berlin)
        let summer = Self.sample(.stepCount, 10, .count(), start: "2026-07-01T10:00:00.000Z")
        let winter = Self.sample(.stepCount, 10, .count(), start: "2026-12-01T10:00:00.000Z")

        XCTAssertEqual(mapper.dto(summer, metric: steps).utcOffsetMinutes, 120)
        XCTAssertEqual(mapper.dto(winter, metric: steps).utcOffsetMinutes, 60)
    }

    func testSampleTimeZoneRecordedAbroadWinsOverTheDeviceZone() {
        let mapper = HealthSampleMapper(timeZone: berlin)
        let abroad = Self.sample(
            .stepCount, 10, .count(), start: "2026-07-01T10:00:00.000Z",
            metadata: [HKMetadataKeyTimeZone: "America/New_York"]
        )

        XCTAssertEqual(mapper.dto(abroad, metric: steps).utcOffsetMinutes, -240)
    }

    func testWireShapeIsExactlyTheSixRawFieldsAndNoAggregate() throws {
        let dto = HealthSampleDTO(
            identifier: "HKQuantityTypeIdentifierStepCount", value: 1, unit: "count",
            start: "2026-10-20T06:50:00.000Z", end: "2026-10-20T06:50:00.000Z",
            utcOffsetMinutes: 120
        )
        let rawFields: Set<String> = ["identifier", "value", "unit", "start", "end", "utc_offset_minutes"]

        let data = try APIJSONCoding.makeEncoder().encode(dto)
        let keys = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any]).keys

        XCTAssertEqual(Set(keys), rawFields)
        XCTAssertEqual(Mirror(reflecting: dto).children.count, rawFields.count)
    }

    /// Same values as `DEVICE_BODY` in `services/backend/tests/test_health_device_chunk.py`.
    func testEncodedChunkMatchesTheServerFixture() throws {
        let mapper = HealthSampleMapper(timeZone: berlin)
        let hours = [
            Self.hour("2026-10-20T06:00:00.000Z", "2026-10-20T07:00:00.000Z", 300),
            Self.hour("2026-10-20T07:00:00.000Z", "2026-10-20T08:00:00.000Z", 900),
        ]
        let request = HealthSamplesRequestDTO(samples: hours.compactMap { mapper.dto($0, metric: steps) } + [
            mapper.dto(
                Self.sample(.restingHeartRate, 54, HKUnit(from: "count/min"), start: "2026-10-20T03:00:00.250Z"),
                metric: restingHeartRate
            ),
        ])

        let data = try APIJSONCoding.makeEncoder().encode(request)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let samples = try XCTUnwrap(json["samples"] as? [[String: Any]])

        XCTAssertEqual(samples.count, 3)
        XCTAssertEqual(samples[0]["identifier"] as? String, "HKQuantityTypeIdentifierStepCount")
        XCTAssertEqual(samples[0]["value"] as? Double, 300)
        XCTAssertEqual(samples[0]["unit"] as? String, "count")
        XCTAssertEqual(samples[0]["start"] as? String, "2026-10-20T06:00:00.000Z")
        XCTAssertEqual(samples[0]["end"] as? String, "2026-10-20T07:00:00.000Z")
        XCTAssertEqual(samples[0]["utc_offset_minutes"] as? Int, 120)
        XCTAssertEqual(samples[1]["value"] as? Double, 900)
        XCTAssertEqual(samples[1]["start"] as? String, "2026-10-20T07:00:00.000Z")
        XCTAssertEqual(samples[1]["end"] as? String, "2026-10-20T08:00:00.000Z")
        XCTAssertEqual(samples[2]["unit"] as? String, "count/min")
        XCTAssertEqual(samples[2]["value"] as? Double, 54)
        XCTAssertEqual(samples[2]["start"] as? String, "2026-10-20T03:00:00.250Z")
    }

    // MARK: - Sleep

    private static func sleep(
        _ stage: HKCategoryValueSleepAnalysis, start: String, end: String, metadata: [String: Any]? = nil
    ) -> HKCategorySample {
        HKCategorySample(
            type: HKCategoryType(.sleepAnalysis), value: stage.rawValue,
            start: instant(start), end: instant(end), metadata: metadata
        )
    }

    func testSleepIntervalBecomesItsRawStageAndUTCInstants() {
        let mapper = HealthSampleMapper(timeZone: berlin)

        let dto = mapper.dto(
            Self.sleep(.asleepREM, start: "2026-10-20T01:00:00.000Z", end: "2026-10-20T02:00:00.000Z"),
            category: HealthCategoryCatalog.sleep
        )

        XCTAssertEqual(dto, HealthCategorySampleDTO(
            identifier: "HKCategoryTypeIdentifierSleepAnalysis", value: 5,
            start: "2026-10-20T01:00:00.000Z", end: "2026-10-20T02:00:00.000Z", utcOffsetMinutes: 120
        ))
    }

    func testSleepOffsetIsTheOneAtWakeTimeAcrossTheClockChange() {
        // Berlin leaves summer time at 03:00 on 2026-10-25: in bed at +2, awake at +1.
        let mapper = HealthSampleMapper(timeZone: berlin)

        let dto = mapper.dto(
            Self.sleep(.asleepCore, start: "2026-10-24T21:00:00.000Z", end: "2026-10-25T05:00:00.000Z"),
            category: HealthCategoryCatalog.sleep
        )

        XCTAssertEqual(dto.utcOffsetMinutes, 60)
    }

    func testSleepRecordedInAnotherZoneKeepsThatZone() {
        let mapper = HealthSampleMapper(timeZone: berlin)

        let dto = mapper.dto(
            Self.sleep(
                .asleepCore, start: "2026-10-20T04:30:00.000Z", end: "2026-10-20T11:30:00.000Z",
                metadata: [HKMetadataKeyTimeZone: "America/New_York"]
            ),
            category: HealthCategoryCatalog.sleep
        )

        XCTAssertEqual(dto.utcOffsetMinutes, -240)
    }

    func testCategorySampleIsExactlyTheFiveServerFields() throws {
        let dto = HealthCategorySampleDTO(
            identifier: "HKCategoryTypeIdentifierSleepAnalysis", value: 3,
            start: "2026-10-20T01:00:00.000Z", end: "2026-10-20T02:00:00.000Z", utcOffsetMinutes: 120
        )
        let fields: Set<String> = ["identifier", "value", "start", "end", "utc_offset_minutes"]

        let data = try APIJSONCoding.makeEncoder().encode(dto)
        let keys = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any]).keys

        XCTAssertEqual(Set(keys), fields)
        XCTAssertEqual(Mirror(reflecting: dto).children.count, fields.count)
    }

    /// Same values as `DEVICE_SLEEP_BODY` in `services/backend/tests/test_health_sleep_api.py`.
    func testEncodedSleepChunkMatchesTheServerFixture() throws {
        let mapper = HealthSampleMapper(timeZone: berlin)
        let request = HealthSamplesRequestDTO(
            samples: [],
            categorySamples: [
                Self.sleep(.asleepCore, start: "2026-10-19T21:30:00.000Z", end: "2026-10-20T01:00:00.000Z"),
                Self.sleep(.asleepDeep, start: "2026-10-20T01:00:00.000Z", end: "2026-10-20T02:00:00.000Z"),
            ].map { mapper.dto($0, category: HealthCategoryCatalog.sleep) }
        )

        let data = try APIJSONCoding.makeEncoder().encode(request)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let samples = try XCTUnwrap(json["category_samples"] as? [[String: Any]])

        XCTAssertEqual((json["samples"] as? [Any])?.count, 0)
        XCTAssertEqual(samples.count, 2)
        XCTAssertEqual(samples[0]["identifier"] as? String, "HKCategoryTypeIdentifierSleepAnalysis")
        XCTAssertEqual(samples[0]["value"] as? Int, 3)
        XCTAssertEqual(samples[0]["start"] as? String, "2026-10-19T21:30:00.000Z")
        XCTAssertEqual(samples[0]["end"] as? String, "2026-10-20T01:00:00.000Z")
        XCTAssertEqual(samples[0]["utc_offset_minutes"] as? Int, 120)
        XCTAssertEqual(samples[1]["value"] as? Int, 4)
        XCTAssertEqual(samples[1]["start"] as? String, "2026-10-20T01:00:00.000Z")
        XCTAssertEqual(samples[1]["end"] as? String, "2026-10-20T02:00:00.000Z")
    }
}
