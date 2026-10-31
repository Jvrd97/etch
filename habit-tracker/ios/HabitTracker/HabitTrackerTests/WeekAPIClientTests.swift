// [review:need-review] PHASE-03/229, PHASE-03/244
// summary: wire tests of the Week endpoints — the server-shaped answer decodes (nulls stay nil, sleep is "not connected"), the bare and the named path, the POST of the narrative without a body, its 422/502/503 as statuses, and the cache round trip that keeps the answer whole
import XCTest
@testable import HabitTracker

final class WeekAPIClientTests: XCTestCase {
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

    private func respond(_ body: String, status: Int = 200) {
        MockURLProtocol.requestHandler = { [unowned self] request in
            self.captured = request
            let response = HTTPURLResponse(
                url: request.url!, statusCode: status, httpVersion: nil,
                headerFields: ["Content-Type": "application/json"]
            )!
            return (response, Data(body.utf8))
        }
    }

    func testServerWeekDecodesWindowTotalsDaysAndHealth() throws {
        let week = try WeekFixtures.review()

        XCTAssertEqual(week.window.isoCode, "2026-W35")
        XCTAssertEqual(week.window.previousIsoCode, "2026-W34")
        XCTAssertTrue(week.window.isComplete)
        XCTAssertEqual(week.totals.planPct, 67)
        XCTAssertEqual(week.totals.workMinutes, 1200)
        XCTAssertEqual(week.delta.planPct, 29)
        XCTAssertEqual(week.isWon, false)
        XCTAssertEqual(week.days.count, 7)
        XCTAssertEqual(week.days[0].verdict, "won")
        XCTAssertNil(week.days[3].verdict)
        XCTAssertNil(week.days[3].planPct)
        XCTAssertEqual(week.bestDay, "2026-08-24")
        XCTAssertEqual(week.worstDay, "2026-08-25")
        XCTAssertEqual(week.roles.first?.title, "Тимлид")
        XCTAssertNil(week.roles.last?.targetSharePct)
        XCTAssertEqual(week.habitStreaks.first?.relapses, 1)
    }

    func testSleepIsNotConnectedAndDailyKeepsItsGaps() throws {
        let week = try WeekFixtures.review()

        let sleep = try XCTUnwrap(week.health.first { $0.key == "sleep" })
        XCTAssertFalse(sleep.available)
        XCTAssertNil(sleep.unit)
        XCTAssertNil(sleep.avgPerDay)
        let steps = try XCTUnwrap(week.health.first { $0.key == "steps" })
        XCTAssertEqual(steps.daily.count, 7)
        XCTAssertEqual(steps.daily[0], 8000)
        XCTAssertNil(steps.daily[2])
        XCTAssertEqual(steps.deltaAvgPerDay, 3000)
    }

    func testRunningWeekHasNoVerdictYet() throws {
        let week = try WeekFixtures.runningWeek()

        XCTAssertFalse(week.window.isComplete)
        XCTAssertEqual(week.window.countedDays, 3)
        XCTAssertNil(week.isWon)
    }

    func testBarePathAsksForTheRunningWeek() async throws {
        respond(WeekFixtures.reviewJSON)

        let week = try await client.fetchWeekReview(iso: nil)

        let request = try XCTUnwrap(captured)
        XCTAssertEqual(request.httpMethod, "GET")
        XCTAssertEqual(request.url?.path, "/api/v1/week-review")
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-API-Key"), "secret")
        XCTAssertEqual(week.window.isoCode, "2026-W35")
    }

    func testNamedWeekGoesInThePath() async throws {
        respond(WeekFixtures.reviewJSON)

        _ = try await client.fetchWeekReview(iso: "2026-W34")

        XCTAssertEqual(captured?.url?.path, "/api/v1/week-review/2026-W34")
    }

    func testNarrativeIsAPostWithoutABody() async throws {
        respond(#"{"iso_code": "2026-W35", "text": "Неделя прошла ровно.", "model": "claude-x"}"#)

        let narrative = try await client.writeWeekNarrative(iso: "2026-W35")

        let request = try XCTUnwrap(captured)
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.url?.path, "/api/v1/week-review/2026-W35/narrative")
        XCTAssertNil(request.httpBody)
        XCTAssertEqual(narrative.text, "Неделя прошла ровно.")
        XCTAssertEqual(narrative.model, "claude-x")
    }

    func testNarrativeRefusalsComeAsStatuses() async {
        for status in [422, 502, 503] {
            respond(#"{"detail": "нет"}"#, status: status)
            do {
                _ = try await client.writeWeekNarrative(iso: "2026-W35")
                XCTFail("status \(status) must throw")
            } catch {
                XCTAssertEqual(error as? APIClientError, .unexpectedStatus(status))
            }
        }
    }

    func testAnUnreadableAnswerIsAnInvalidResponse() async {
        respond(#"{"window": 1}"#)

        do {
            _ = try await client.fetchWeekReview(iso: nil)
            XCTFail("must throw")
        } catch {
            XCTAssertEqual(error as? APIClientError, .invalidResponse)
        }
    }

    func testTheReadCacheKeepsTheWholeAnswer() throws {
        let week = try WeekFixtures.review()
        let store = InMemoryCacheStore()

        store.save(week, forKey: "week", updatedAt: Date(timeIntervalSince1970: 0))

        XCTAssertEqual(store.load(WeekReviewDTO.self, forKey: "week")?.value, week)
    }

    func testTheAdviceIsAPostWithTheWindowOfSevenDays() async throws {
        respond(WeekFixtures.adviceJSON)

        let advice = try await client.writeHealthAdvice()

        XCTAssertEqual(captured?.httpMethod, "POST")
        XCTAssertEqual(captured?.url?.path, "/api/v1/health-advice")
        let body = try XCTUnwrap(captured?.httpBody ?? captured?.httpBodyStream.map(Self.read))
        XCTAssertEqual(try JSONSerialization.jsonObject(with: body) as? [String: Int], ["days": 7])
        XCTAssertEqual(advice.days, 7)
        XCTAssertEqual(advice.startsOn, "2026-10-24")
        XCTAssertTrue(advice.text.hasSuffix("Это не медицинская рекомендация."))
    }

    func testTheAdviceRefusalsArriveAsStatuses() async {
        for status in [422, 502, 503] {
            respond(#"{"detail": "x"}"#, status: status)
            do {
                _ = try await client.writeHealthAdvice()
                XCTFail("status \(status) must throw")
            } catch let error as APIClientError {
                XCTAssertEqual(error, .unexpectedStatus(status))
            } catch {
                XCTFail("unexpected \(error)")
            }
        }
    }

    /// `httpBody` is moved into `httpBodyStream` by URLSession before a URLProtocol sees it.
    private static func read(_ stream: InputStream) -> Data {
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 1024)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count <= 0 { break }
            data.append(buffer, count: count)
        }
        return data
    }
}
