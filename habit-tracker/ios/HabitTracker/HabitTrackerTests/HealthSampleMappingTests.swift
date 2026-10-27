// [review:need-review] PHASE-03/131
// summary: HKQuantitySample → HealthSampleDTO mapping (units, UTC instants, the device offset at the sample moment, the sample's own time zone first), the six-field wire shape with no aggregate, and the body the server fixture expects
import HealthKit
import XCTest
@testable import HabitTracker

final class HealthSampleMappingTests: XCTestCase {
    private let berlin = TimeZone(identifier: "Europe/Berlin")!
    private let steps = HealthPump.pumpedMetrics[0]
    private let restingHeartRate = HealthPump.pumpedMetrics[1]

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

    func testPumpedMetricsAreStepsAndRestingHeartRateInServerUnits() {
        XCTAssertEqual(HealthPump.pumpedMetrics.map(\.identifier), [
            "HKQuantityTypeIdentifierStepCount",
            "HKQuantityTypeIdentifierRestingHeartRate",
        ])
        // Strings the server's unit table knows (`app/health/aggregate.py`, `_UNITS`).
        XCTAssertEqual(HealthPump.pumpedMetrics.map(\.unit), ["count", "count/min"])
    }

    func testCumulativeSampleKeepsItsIntervalAndValue() {
        let mapper = HealthSampleMapper(timeZone: berlin)
        let walk = Self.sample(
            .stepCount, 1200, .count(),
            start: "2026-10-20T06:50:00.000Z", end: "2026-10-20T07:30:00.000Z"
        )

        let dto = mapper.dto(walk, metric: steps)

        XCTAssertEqual(dto, HealthSampleDTO(
            identifier: "HKQuantityTypeIdentifierStepCount",
            value: 1200,
            unit: "count",
            start: "2026-10-20T06:50:00.000Z",
            end: "2026-10-20T07:30:00.000Z",
            utcOffsetMinutes: 120
        ))
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
        let request = HealthSamplesRequestDTO(samples: [
            mapper.dto(Self.sample(
                .stepCount, 1200, .count(),
                start: "2026-10-20T06:50:00.000Z", end: "2026-10-20T07:30:00.000Z"
            ), metric: steps),
            mapper.dto(
                Self.sample(.restingHeartRate, 54, HKUnit(from: "count/min"), start: "2026-10-20T03:00:00.250Z"),
                metric: restingHeartRate
            ),
        ])

        let data = try APIJSONCoding.makeEncoder().encode(request)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let samples = try XCTUnwrap(json["samples"] as? [[String: Any]])

        XCTAssertEqual(samples.count, 2)
        XCTAssertEqual(samples[0]["identifier"] as? String, "HKQuantityTypeIdentifierStepCount")
        XCTAssertEqual(samples[0]["value"] as? Double, 1200)
        XCTAssertEqual(samples[0]["unit"] as? String, "count")
        XCTAssertEqual(samples[0]["start"] as? String, "2026-10-20T06:50:00.000Z")
        XCTAssertEqual(samples[0]["end"] as? String, "2026-10-20T07:30:00.000Z")
        XCTAssertEqual(samples[0]["utc_offset_minutes"] as? Int, 120)
        XCTAssertEqual(samples[1]["unit"] as? String, "count/min")
        XCTAssertEqual(samples[1]["value"] as? Double, 54)
        XCTAssertEqual(samples[1]["start"] as? String, "2026-10-20T03:00:00.250Z")
    }
}
