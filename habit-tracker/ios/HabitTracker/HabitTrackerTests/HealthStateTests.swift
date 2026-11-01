// [review:need-review] PHASE-03/305
// summary: tests of the «Состояние сегодня» read — the dashboard summary parsed by its contract (extra blocks ignored, null index under three days), the request path and window, and the tab's model: the card appears when the server answers, is absent while the endpoint is missing or the read fails, the workouts block asks 30 days
// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 — the read asks for the health blocks alone
import XCTest
@testable import HabitTracker

final class HealthStateWireTests: XCTestCase {
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

    func testTheSummaryIsReadByItsContractAndTheRestOfItIsIgnored() async throws {
        let api = client(responding: """
        {"period": "week", "from": "2026-10-25", "to": "2026-10-31", "today": "2026-10-31",
         "scores": {"health": {"value": 78, "label": "good", "basis_days": 7},
                    "habits": {"value": 64, "done": 45, "total": 70}, "challenges": {"done": 3, "total": 5}},
         "streaks": [], "health": [], "bests": [], "workouts": {"weeks": [], "total": 5, "delta_vs_previous": 1}, "insight": null}
        """)
        let state = try await api.fetchHealthState()
        XCTAssertEqual(captured?.url?.path, "/api/v1/dashboard/summary")
        let query = URLComponents(url: captured!.url!, resolvingAgainstBaseURL: false)?.queryItems ?? []
        XCTAssertEqual(query.first { $0.name == "period" }?.value, "week")
        // Only the health blocks: the server skips the streaks and the rest (#309); an older server ignores it.
        XCTAssertEqual(query.first { $0.name == "parts" }?.value, "health")
        XCTAssertEqual(state.scores.health, HealthScoreDTO(value: 78, label: "good", basisDays: 7))
    }

    func testTooLittleDataArrivesAsANullIndexNotAZero() async throws {
        let api = client(responding: #"{"scores": {"health": {"value": null, "label": null, "basis_days": 2}}}"#)
        let health = try await api.fetchHealthState().scores.health
        XCTAssertNil(health?.value)
        XCTAssertNil(health?.label)
        XCTAssertEqual(health?.basisDays, 2)
    }

    func testTheCacheKeepsTheScoreAsItWasRead() throws {
        let score = HealthScoreDTO(value: 61, label: "fair", basisDays: 5)
        let data = try APIJSONCoding.makeEncoder().encode(HealthStateResponseDTO(scores: .init(health: score)))
        let back = try APIJSONCoding.makeDecoder().decode(HealthStateResponseDTO.self, from: data)
        XCTAssertEqual(back.scores.health, score)
    }
}

private final class MockHealthStateAPI: HealthStateAPI {
    var handler: () async throws -> HealthStateResponseDTO
    init(_ handler: @escaping () async throws -> HealthStateResponseDTO) { self.handler = handler }
    func fetchHealthState() async throws -> HealthStateResponseDTO { try await handler() }
}

private final class AskedCounter {
    private(set) var provided = 0
    func provide() -> HealthStateAPI? {
        provided += 1
        return nil
    }
}

@MainActor
final class HealthStateModelTests: XCTestCase {
    /// 2026-10-29 12:00 UTC.
    private let moment = Date(timeIntervalSince1970: 1_793_275_200)
    private var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar
    }

    private func make(_ api: MockHealthMetricsAPI, state: HealthStateAPI?) -> HealthMetricsViewModel {
        HealthMetricsViewModel(
            apiProvider: { api }, stateAPIProvider: { state }, cacheStore: InMemoryCacheStore(), now: { self.moment }, calendar: calendar
        )
    }

    private func answer(_ score: HealthScoreDTO?) -> HealthStateResponseDTO {
        HealthStateResponseDTO(scores: .init(health: score))
    }

    func testTheCardCarriesTheServersIndex() async {
        let score = HealthScoreDTO(value: 78, label: "good", basisDays: 7)
        let model = make(MockHealthMetricsAPI(), state: MockHealthStateAPI { self.answer(score) })
        await model.load()
        XCTAssertEqual(model.healthState, score)
    }

    func testWhileTheEndpointIsMissingTheCardIsAbsentAndTheScreenStillLoads() async {
        let model = make(MockHealthMetricsAPI(), state: MockHealthStateAPI { throw APIClientError.unexpectedStatus(404) })
        await model.load()
        XCTAssertEqual(model.state, .loaded)
        XCTAssertNil(model.healthState)
    }

    func testACachedIndexCarriesItsMomentAndAFreshOneDoesNot() async {
        let store = InMemoryCacheStore()
        let score = HealthScoreDTO(value: 70, label: "good", basisDays: 7)
        let online = HealthMetricsViewModel(
            apiProvider: { MockHealthMetricsAPI() }, stateAPIProvider: { MockHealthStateAPI { self.answer(score) } },
            cacheStore: store, now: { self.moment }, calendar: calendar
        )
        await online.load()
        XCTAssertNil(online.healthStateAsOf)

        let later = moment.addingTimeInterval(3600)
        let offline = HealthMetricsViewModel(
            apiProvider: { MockHealthMetricsAPI() },
            stateAPIProvider: { MockHealthStateAPI { throw APIClientError.transport(code: -1009) } },
            cacheStore: store, now: { later }, calendar: calendar
        )
        await offline.load()
        XCTAssertEqual(offline.healthState, score)
        XCTAssertEqual(offline.healthStateAsOf, moment, "shown as of the moment it was read, not as today's")
    }

    func testWithoutAStateSourceNothingIsAsked() async {
        let asked = AskedCounter()
        let model = HealthMetricsViewModel(
            apiProvider: { MockHealthMetricsAPI() }, stateAPIProvider: { asked.provide() },
            cacheStore: InMemoryCacheStore(), now: { self.moment }, calendar: calendar
        )
        await model.load()
        XCTAssertEqual(asked.provided, 1)
        XCTAssertNil(model.healthState)
        XCTAssertNil(model.healthStateAsOf)
    }

    func testWithoutAStateSourceTheCardIsAbsent() async {
        let model = make(MockHealthMetricsAPI(), state: nil)
        await model.load()
        XCTAssertEqual(model.state, .loaded)
        XCTAssertNil(model.healthState)
    }

    func testTheWorkoutsBlockAsksThirtyDaysAndNightsStayAWeek() async {
        let api = MockHealthMetricsAPI()
        let model = make(api, state: nil)
        await model.load()
        XCTAssertTrue(api.calls.contains("workouts 2026-09-30...2026-10-29"))
        XCTAssertTrue(api.calls.contains("sleep 2026-10-23...2026-10-29"))
    }
}
