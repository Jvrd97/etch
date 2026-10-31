// [review:need-review] PHASE-03/304
// summary: tests of the dashboard read — the request path and period, the full answer parsed by its contract (nulls kept as nil, the server's direction of «better», the day strips with gaps), the empty answer, and the cache round trip
import XCTest
@testable import HabitTracker

final class DashboardWireTests: XCTestCase {
    private var captured: URLRequest?

    override func tearDown() {
        MockURLProtocol.requestHandler = nil
        super.tearDown()
    }

    private func client(responding body: String) -> APIClient {
        MockURLProtocol.requestHandler = { [unowned self] request in
            self.captured = request
            let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            return (response, Data(body.utf8))
        }
        return APIClient(baseURL: URL(string: "http://localhost:8879")!, apiKeyProvider: { "secret" }, session: MockURLProtocol.makeSession())
    }

    private func period(of request: URLRequest?) -> String? {
        request?.url.flatMap { URLComponents(url: $0, resolvingAgainstBaseURL: false) }?.queryItems?.first { $0.name == "period" }?.value
    }

    func testTheRequestAsksTheSummaryOfTheChosenPeriod() async throws {
        let api = client(responding: DashboardFixtures.weekJSON)
        _ = try await api.fetchDashboardSummary(period: .week)
        XCTAssertEqual(captured?.url?.path, "/api/v1/dashboard/summary")
        XCTAssertEqual(period(of: captured), "week")
        _ = try await api.fetchDashboardSummary(period: .month)
        XCTAssertEqual(period(of: captured), "month")
    }

    func testTheFullAnswerIsReadByItsContract() throws {
        let summary = try DashboardFixtures.week()
        XCTAssertEqual(summary.today, "2026-10-31")
        XCTAssertEqual(summary.scores.health, HealthScoreDTO(value: 78, label: "good", basisDays: 7))
        XCTAssertEqual(summary.scores.habits, .init(value: 64, done: 45, total: 70))
        XCTAssertEqual(summary.scores.challenges, .init(done: 3, total: 5))
        XCTAssertEqual(summary.streaks[0].days, [true, true, false, nil, true, true, true])
        XCTAssertTrue(summary.streaks[1].isAvoid)
        XCTAssertFalse(summary.streaks[0].isAvoid)
        XCTAssertEqual(summary.health[0].higherIsBetter, false)
        XCTAssertNil(summary.health[2].baselineDelta)
        XCTAssertTrue(summary.bests[0].isRecord)
        XCTAssertEqual(summary.workouts.weeks.map(\.weekStart), ["2026-10-19", "2026-10-26"])
        XCTAssertEqual(summary.workouts.deltaVsPrevious, 1)
        XCTAssertEqual(summary.insight?.generatedAt, "2026-10-31T09:00:00+03:00")
    }

    func testAnEmptyAnswerKeepsNullsAsNilAndNotAsZeros() throws {
        let summary = try DashboardFixtures.empty()
        XCTAssertNil(summary.scores.health.value)
        XCTAssertEqual(summary.scores.health.basisDays, 2)
        XCTAssertNil(summary.scores.habits.total)
        XCTAssertNil(summary.scores.challenges.total)
        XCTAssertTrue(summary.streaks.isEmpty)
        XCTAssertNil(summary.workouts.total)
        XCTAssertNil(summary.insight)
    }

    func testTheCacheKeepsTheSummaryAsItWasRead() throws {
        let summary = try DashboardFixtures.week()
        let data = try APIJSONCoding.makeEncoder().encode(summary)
        let back = try APIJSONCoding.makeDecoder().decode(DashboardSummaryDTO.self, from: data)
        XCTAssertEqual(back, summary)
    }
}
