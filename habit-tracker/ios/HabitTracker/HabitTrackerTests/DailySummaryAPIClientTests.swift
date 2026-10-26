// [review:need-review] PHASE-01/213
// summary: wire-format tests for the day-summary endpoints — draft body and decoded plan (metric, tick, unresolved, journal with its mode), apply body carrying only the chosen operations under an Idempotency-Key, snake_case keys, error statuses surface as typed errors
import XCTest
@testable import HabitTracker

final class DailySummaryAPIClientTests: XCTestCase {
    private var client: APIClient!

    override func setUp() {
        super.setUp()
        client = APIClient(
            baseURL: URL(string: "http://localhost:8813")!,
            apiKeyProvider: { "secret" },
            session: MockURLProtocol.makeSession()
        )
    }

    override func tearDown() {
        MockURLProtocol.requestHandler = nil
        client = nil
        super.tearDown()
    }

    private static func reply(
        _ request: URLRequest, status: Int = 200, body: String
    ) -> (HTTPURLResponse, Data) {
        let response = HTTPURLResponse(
            url: request.url!, statusCode: status, httpVersion: nil,
            headerFields: ["Content-Type": "application/json"]
        )!
        return (response, Data(body.utf8))
    }

    private static func json(_ request: URLRequest) throws -> [String: Any] {
        let data = try XCTUnwrap(TodayScreenAPITests.bodyData(of: request))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    func testDraftPostsTheRetellingWithItsDayAndDecodesThePlan() async throws {
        var captured: URLRequest?
        MockURLProtocol.requestHandler = { request in
            captured = request
            return Self.reply(request, status: 200, body: """
            {"metrics": [{"op": "log_metric", "category_id": 4, "field_id": 9, "value": 30,
                          "source_text": "отжался 30 раз", "uncertain": false,
                          "implausible": false, "estimated": true}],
             "checklist": [{"op": "check", "category_id": 7, "field_id": 21,
                            "source_text": "выпил витамины", "uncertain": true}],
             "unresolved": [{"text": "прошёл 12 тысяч шагов", "reason": null}],
             "journal": {"op": "write_journal", "title": null, "content": "Хороший день",
                         "mood": "calm", "tags": null, "mode": "append",
                         "existing_entry_id": 55}}
            """)
        }

        let plan = try await client.draftDailySummary(
            DailySummaryDraftRequestDTO(transcript: "отжался 30 раз", entryDate: "2026-10-26")
        )

        let request = try XCTUnwrap(captured)
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.url?.path, "/api/v1/daily-summary/draft")
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-API-Key"), "secret")
        let body = try Self.json(request)
        XCTAssertEqual(body["transcript"] as? String, "отжался 30 раз")
        XCTAssertEqual(body["entry_date"] as? String, "2026-10-26")

        XCTAssertEqual(plan.metrics.first?.fieldId, 9)
        XCTAssertEqual(plan.metrics.first?.estimated, true)
        XCTAssertEqual(plan.checklist.first?.uncertain, true)
        XCTAssertEqual(plan.unresolved.first?.text, "прошёл 12 тысяч шагов")
        XCTAssertEqual(plan.journal?.mode, JournalOpDTO.Mode.append)
        XCTAssertEqual(plan.journal?.existingEntryId, 55)
    }

    func testApplySendsOnlyTheChosenOperationsUnderTheIdempotencyKey() async throws {
        var captured: URLRequest?
        MockURLProtocol.requestHandler = { request in
            captured = request
            return Self.reply(request, status: 201, body: #"{"entry_ids": [11, 12], "journal_entry_id": 55}"#)
        }
        let metric = LogMetricOpDTO(
            categoryId: 4, fieldId: 9, value: 30, sourceText: "отжался 30 раз",
            uncertain: false, implausible: false, estimated: false
        )
        let journal = JournalOpDTO(
            title: nil, content: "Хороший день", mood: nil, tags: nil,
            mode: JournalOpDTO.Mode.create, existingEntryId: nil
        )

        let answer = try await client.applyDailySummary(
            DailySummaryApplyRequestDTO(
                entryDate: "2026-10-26", metrics: [metric], checklist: [], journal: journal
            ),
            idempotencyKey: "plan-key-1"
        )

        let request = try XCTUnwrap(captured)
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.url?.path, "/api/v1/daily-summary/apply")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Idempotency-Key"), "plan-key-1")
        let body = try Self.json(request)
        XCTAssertEqual(body["entry_date"] as? String, "2026-10-26")
        XCTAssertEqual((body["checklist"] as? [Any])?.count, 0)
        let sentMetric = try XCTUnwrap((body["metrics"] as? [[String: Any]])?.first)
        XCTAssertEqual(sentMetric["op"] as? String, "log_metric")
        XCTAssertEqual(sentMetric["category_id"] as? Int, 4)
        XCTAssertEqual(sentMetric["source_text"] as? String, "отжался 30 раз")
        XCTAssertEqual(sentMetric["value"] as? Double, 30)
        let sentJournal = try XCTUnwrap(body["journal"] as? [String: Any])
        XCTAssertEqual(sentJournal["op"] as? String, "write_journal")
        XCTAssertEqual(sentJournal["mode"] as? String, "create")
        XCTAssertEqual(answer.entryIds, [11, 12])
        XCTAssertEqual(answer.journalEntryId, 55)
    }

    func testApplyWithoutJournalOmitsTheKey() async throws {
        var captured: URLRequest?
        MockURLProtocol.requestHandler = { request in
            captured = request
            return Self.reply(request, status: 201, body: #"{"entry_ids": [11], "journal_entry_id": null}"#)
        }
        let check = CheckOpDTO(categoryId: 7, fieldId: 21, sourceText: "витамины", uncertain: false)

        _ = try await client.applyDailySummary(
            DailySummaryApplyRequestDTO(entryDate: "2026-10-26", metrics: [], checklist: [check], journal: nil),
            idempotencyKey: "k"
        )

        let body = try Self.json(try XCTUnwrap(captured))
        XCTAssertNil(body["journal"])
        XCTAssertEqual((body["checklist"] as? [[String: Any]])?.first?["op"] as? String, "check")
    }

    func testDraftStatusIsATypedError() async {
        MockURLProtocol.requestHandler = { request in
            Self.reply(request, status: 503, body: #"{"detail": "disabled"}"#)
        }
        do {
            _ = try await client.draftDailySummary(
                DailySummaryDraftRequestDTO(transcript: "x", entryDate: "2026-10-26")
            )
            XCTFail("expected an error")
        } catch {
            XCTAssertEqual(error as? APIClientError, .unexpectedStatus(503))
        }
    }
}
