// [review:need-review] PHASE-01/268
// summary: wire tests of the Health read side — the path and range of each GET, snake_case keys as the server shapes them (baseline, hours, sleep nights, workouts with null numbers, sync status), and the cache round trip of the catalogue
import XCTest
@testable import HabitTracker

final class HealthMetricsAPIClientTests: XCTestCase {
    private var client: APIClient!
    private var captured: URLRequest?

    override func setUp() {
        super.setUp()
        client = APIClient(baseURL: URL(string: "http://localhost:8879")!, apiKeyProvider: { "secret" }, session: MockURLProtocol.makeSession())
        captured = nil
    }

    override func tearDown() {
        MockURLProtocol.requestHandler = nil
        client = nil
        super.tearDown()
    }

    private func respond(_ body: String) {
        MockURLProtocol.requestHandler = { [unowned self] request in
            self.captured = request
            let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (response, Data(body.utf8))
        }
    }

    private func query(_ name: String) -> String? {
        URLComponents(url: captured!.url!, resolvingAgainstBaseURL: false)?.queryItems?.first { $0.name == name }?.value
    }

    func testMetricsAskTheRangeAndDecodeTheBaseline() async throws {
        respond("""
        {"metrics": [{"identifier": "HKQuantityTypeIdentifierBodyMass", "display_name": "Вес", "group": "body", "kind": "discrete",
          "canonical_unit": "kg", "days": [{"date": "2026-10-29", "value": 68.4}],
          "baseline": {"mean": 68.0, "stddev": 0.5, "days": 20, "day": "2026-10-29", "deviation": 0.4, "outside_typical": false}},
         {"identifier": "HKQuantityTypeIdentifierStepCount", "display_name": "Шаги", "group": "movement", "kind": "cumulative",
          "canonical_unit": "count", "days": [], "baseline": null}]}
        """)
        let response = try await client.fetchHealthMetrics(dateFrom: "2026-09-30", dateTo: "2026-10-29")
        XCTAssertEqual(captured?.url?.path, "/api/v1/health/metrics")
        XCTAssertEqual(query("date_from"), "2026-09-30")
        XCTAssertEqual(query("date_to"), "2026-10-29")
        XCTAssertEqual(response.metrics[0].baseline?.deviation, 0.4)
        XCTAssertEqual(response.metrics[0].canonicalUnit, "kg")
        XCTAssertNil(response.metrics[1].baseline)
        XCTAssertTrue(response.metrics[1].days.isEmpty)
    }

    func testDaysAndHoursOfOneMetric() async throws {
        respond(#"{"identifier": "x", "display_name": "X", "kind": "cumulative", "canonical_unit": "count", "days": [{"date": "2026-10-28", "value": 1}]}"#)
        let days = try await client.fetchHealthMetricDays(identifier: "HKQuantityTypeIdentifierStepCount", dateFrom: "2026-10-01", dateTo: "2026-10-29")
        XCTAssertEqual(captured?.url?.path, "/api/v1/health/metrics/HKQuantityTypeIdentifierStepCount/days")
        XCTAssertEqual(days.days.count, 1)

        respond(#"{"identifier": "x", "display_name": "X", "kind": "discrete", "canonical_unit": "count/min", "date": "2026-10-28", "hours": [{"hour": 8, "value": 56, "min": 54, "max": 58, "sample_count": 3}]}"#)
        let hours = try await client.fetchHealthMetricHours(identifier: "HKQuantityTypeIdentifierHeartRate", date: "2026-10-28")
        XCTAssertEqual(captured?.url?.path, "/api/v1/health/metrics/HKQuantityTypeIdentifierHeartRate/hours")
        XCTAssertEqual(query("date"), "2026-10-28")
        XCTAssertEqual(hours.hours.first?.sampleCount, 3)
    }

    func testSleepWorkoutsAndSyncStatus() async throws {
        respond("""
        {"nights": [{"date": "2026-10-29", "bedtime": "2026-10-29T00:10:00+03:00", "wake_time": "2026-10-29T07:20:00+03:00",
          "in_bed_min": 460, "asleep_min": 430, "awake_min": 30, "core_min": 250, "deep_min": 90, "rem_min": 90, "unspecified_min": 0}]}
        """)
        let sleep = try await client.fetchHealthSleep(dateFrom: "2026-10-23", dateTo: "2026-10-29")
        XCTAssertEqual(captured?.url?.path, "/api/v1/health/sleep")
        XCTAssertEqual(sleep.nights[0].wakeTime, "2026-10-29T07:20:00+03:00")
        XCTAssertEqual(sleep.nights[0].deepMin, 90)

        respond("""
        {"workouts": [{"id": "6f1c0a52-0000-4000-8000-000000000001", "activity_type": "running", "activity_label": "Бег", "date": "2026-10-29",
          "start": "2026-10-29T18:00:00+03:00", "end": "2026-10-29T18:40:00+03:00", "duration_min": 40, "energy_kcal": null,
          "distance_m": 7200, "avg_heart_rate": null, "max_heart_rate": 171}]}
        """)
        let workouts = try await client.fetchHealthWorkouts(dateFrom: "2026-10-23", dateTo: "2026-10-29")
        XCTAssertEqual(captured?.url?.path, "/api/v1/health/workouts")
        XCTAssertNil(workouts.workouts[0].energyKcal)
        XCTAssertEqual(workouts.workouts[0].distanceM, 7200)

        respond("""
        {"last_runs": [{"sync_run_id": "6f1c0a52-0000-4000-8000-000000000002", "kind": "rolling", "status": "failed", "interrupted": false,
          "failure_kind": "network", "device_id": null, "started_at": "2026-10-29T10:00:00Z", "finished_at": "2026-10-29T10:01:00Z",
          "range_from": null, "range_to": null, "samples_received": 0, "buckets_written": 0, "chunks_done": 0, "chunks_total": null}],
         "last_success_at": null, "lag_hours": null, "interrupted": false}
        """)
        let status = try await client.fetchHealthSyncStatus()
        XCTAssertEqual(captured?.url?.path, "/api/v1/health/sync-status")
        XCTAssertNil(status.lagHours)
        XCTAssertEqual(status.lastRuns.first?.failureKind, "network")
    }

    func testCatalogueSurvivesTheCache() {
        let store = InMemoryCacheStore()
        let value = HealthMetricsResponseDTO(metrics: [HealthMetricsFixtures.steps(days: [("2026-10-29", 5)])])
        store.save(value, forKey: "k", updatedAt: Date(timeIntervalSince1970: 1))
        XCTAssertEqual(store.load(HealthMetricsResponseDTO.self, forKey: "k")?.value, value)
    }
}
