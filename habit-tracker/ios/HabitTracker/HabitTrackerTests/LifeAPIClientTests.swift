// [review:need-review] PHASE-01/265
// summary: wire tests of the Life endpoints — GET /day-mode and GET /days?from&to as the server shapes them (three verdict states, snake_case keys), and the cache round trip of the snapshot
import XCTest
@testable import HabitTracker

final class LifeAPIClientTests: XCTestCase {
    private var client: APIClient!
    private var captured: URLRequest?

    override func setUp() {
        super.setUp()
        client = APIClient(
            baseURL: URL(string: "http://localhost:8879")!,
            apiKeyProvider: { "secret" },
            session: MockURLProtocol.makeSession()
        )
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

    func testServerDayReadsDayModeWithoutADate() async throws {
        respond(#"{"date": "2026-10-29", "kind": "work", "nocode": false, "source": "schedule"}"#)
        let day = try await client.fetchServerDay()
        XCTAssertEqual(day.date, "2026-10-29")
        XCTAssertEqual(captured?.url?.path, "/api/v1/day-mode")
    }

    func testDaysAskTheRangeAndDecodeAllThreeVerdictStates() async throws {
        respond("""
        [
          {"date": "2026-10-27", "title": "Релиз", "verdict": "won", "verdict_origin": "computed", "done": 3, "total": 3},
          {"date": "2026-10-28", "title": "", "verdict": "lost", "verdict_origin": "migrated_prose", "done": 1, "total": 3},
          {"date": "2026-10-29", "title": "Сегодня", "verdict": null, "verdict_origin": "none", "done": 0, "total": 2}
        ]
        """)
        let days = try await client.fetchDays(from: "2023-01-01", to: "2026-12-31")
        XCTAssertEqual(days.map(\.verdict), ["won", "lost", nil])
        XCTAssertEqual(days[1].verdictOrigin, "migrated_prose")
        XCTAssertEqual(days[0].done, 3)
        let query = URLComponents(url: captured!.url!, resolvingAgainstBaseURL: false)?.queryItems ?? []
        XCTAssertEqual(captured?.url?.path, "/api/v1/days")
        XCTAssertEqual(query.first { $0.name == "from" }?.value, "2023-01-01")
        XCTAssertEqual(query.first { $0.name == "to" }?.value, "2026-12-31")
    }

    func testSnapshotSurvivesTheCache() {
        let store = InMemoryCacheStore()
        let snapshot = LifeSnapshotDTO(
            today: "2026-10-29",
            days: [LifeDayDTO(date: "2026-10-28", title: "x", verdict: nil, verdictOrigin: "none", done: 0, total: 1)]
        )
        store.save(snapshot, forKey: "life.days", updatedAt: Date(timeIntervalSince1970: 1))
        XCTAssertEqual(store.load(LifeSnapshotDTO.self, forKey: "life.days")?.value, snapshot)
    }
}
