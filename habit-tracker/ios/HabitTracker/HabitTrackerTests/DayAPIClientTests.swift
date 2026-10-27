// [review:need-review] PHASE-01/211, PHASE-03/226
// summary: wire tests of the Day endpoints — the server-shaped GET /day fixture decodes into plan tree/marks/facts/summary, and every write goes to the right path with the right method, snake_case body, Idempotency-Key and query
import XCTest
@testable import HabitTracker

final class DayAPIClientTests: XCTestCase {
    private var client: APIClient!
    private var captured: URLRequest?

    override func setUp() {
        super.setUp()
        client = APIClient(
            baseURL: URL(string: "http://localhost:8811")!,
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

    private func bodyJSON() throws -> [String: Any] {
        let request = try XCTUnwrap(captured)
        let data = try XCTUnwrap(request.httpBody ?? request.httpBodyStream.map(Self.read))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

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

    // MARK: Decoding

    func testARuleWithoutTimezoneStillDecodes() throws {
        let json = DayFixtures.dayJSON.replacingOccurrences(of: "\"timezone\": \"Europe/Berlin\",", with: "")
        let day = try APIJSONCoding.makeDecoder().decode(DayDetailDTO.self, from: Data(json.utf8))
        XCTAssertEqual(day.rule.maxWorkTasks, 3)
    }

    func testServerDayDecodesPlanTreeMarksFactsAndSummary() throws {
        let day = try DayFixtures.day()

        XCTAssertEqual(day.day.date, "2026-10-25")
        XCTAssertEqual(day.rule.maxWorkTasks, 3)
        let work = try XCTUnwrap(day.plan?.sections.first)
        XCTAssertEqual(work.items.first?.textPlain, "Релиз iOS")
        XCTAssertEqual(work.items.first?.children.first?.kind, "minimum")
        let pushups = try XCTUnwrap(day.plan?.sections.last?.items.first)
        XCTAssertEqual(pushups.categoryId, 7)
        XCTAssertEqual(pushups.targetValue, 300)
        XCTAssertEqual(day.marks.first?.state, "done")
        XCTAssertEqual(day.marks.first?.note, "ок")
        let facts = try XCTUnwrap(day.planFacts.first)
        XCTAssertEqual(facts.link.unit, "раз")
        XCTAssertEqual(facts.link.targetValue, 300)
        XCTAssertEqual(facts.total, 100)
        XCTAssertEqual(facts.entries.first?.values.first?.value, "100")
        XCTAssertEqual(day.taskCounts.done, 1)
        XCTAssertEqual(day.notebook, "Заметка дня")
        XCTAssertEqual(day.summary.stage, "open")
        XCTAssertNil(day.summary.verdict)
        XCTAssertEqual(day.summary.missingAnchors, ["Подъём"])
    }

    func testDayWithoutPlanDecodesAsNil() throws {
        let json = DayFixtures.dayJSON
            .replacingOccurrences(of: "\"has_plan\": true", with: "\"has_plan\": false")
            .replacingOccurrences(of: "\"notebook\": \"Заметка дня\"", with: "\"notebook\": null")
        let data = try JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any]
        var object = try XCTUnwrap(data)
        object["plan"] = NSNull()
        object["plan_facts"] = []
        let day = try APIJSONCoding.makeDecoder().decode(
            DayDetailDTO.self, from: JSONSerialization.data(withJSONObject: object)
        )
        XCTAssertNil(day.plan)
        XCTAssertFalse(day.hasPlan)
        XCTAssertNil(day.notebook)
    }

    // MARK: Reads

    func testFetchTodayHitsDayWithOpenedFlag() async throws {
        respond(DayFixtures.dayJSON)

        _ = try await client.fetchDay(date: nil)

        let url = try XCTUnwrap(captured?.url)
        XCTAssertEqual(url.path, "/api/v1/day")
        XCTAssertEqual(URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first?.name, "opened")
        XCTAssertEqual(captured?.value(forHTTPHeaderField: "X-API-Key"), "secret")
    }

    func testFetchNamedDayHitsDayDate() async throws {
        respond(DayFixtures.dayJSON)

        _ = try await client.fetchDay(date: "2026-10-24")

        XCTAssertEqual(captured?.url?.path, "/api/v1/day/2026-10-24")
    }

    // MARK: Writes

    func testSetMarkPutsStateAndNote() async throws {
        respond(#"{"item_id":"11111111-1111-4111-8111-111111111111","state":"failed","note":"ок","marked_at":null,"updated_at":null,"source":"web"}"#)

        let stored = try await client.setMark(
            date: "2026-10-25", itemID: DayFixtures.taskID, DayMarkRequestDTO(state: "failed", note: "ок")
        )

        XCTAssertEqual(captured?.httpMethod, "PUT")
        XCTAssertEqual(captured?.url?.path, "/api/v1/day/2026-10-25/marks/11111111-1111-4111-8111-111111111111")
        let body = try bodyJSON()
        XCTAssertEqual(body["state"] as? String, "failed")
        XCTAssertEqual(body["note"] as? String, "ок")
        XCTAssertEqual(stored.state, "failed")
    }

    func testRecordFactPostsTypedValueWithIdempotencyKey() async throws {
        respond(Self.factWriteJSON, status: 201)
        let body = PlanFactRequestDTO(
            values: [PlanFactValueRequestDTO(fieldId: 70, value: .number(200), unit: "раз")], mark: "done"
        )

        let written = try await client.recordFact(
            date: "2026-10-25", itemID: DayFixtures.pushupsID, body, idempotencyKey: "fact-1"
        )

        XCTAssertEqual(captured?.httpMethod, "POST")
        XCTAssertEqual(captured?.url?.path, "/api/v1/day/2026-10-25/plan/items/33333333-3333-4333-8333-333333333333/facts")
        XCTAssertEqual(captured?.value(forHTTPHeaderField: "Idempotency-Key"), "fact-1")
        let json = try bodyJSON()
        XCTAssertEqual(json["mark"] as? String, "done")
        let value = try XCTUnwrap((json["values"] as? [[String: Any]])?.first)
        XCTAssertEqual(value["field_id"] as? Int, 70)
        XCTAssertEqual(value["value"] as? Double, 200)
        XCTAssertEqual(value["unit"] as? String, "раз")
        XCTAssertEqual(written.entryId, 502)
        XCTAssertEqual(written.facts?.total, 300)
        XCTAssertEqual(written.mark.state, "done")
    }

    func testBooleanFactEncodesAsJSONBoolNotNumber() async throws {
        respond(Self.factWriteJSON, status: 201)
        let body = PlanFactRequestDTO(
            values: [PlanFactValueRequestDTO(fieldId: 80, value: .flag(true), unit: nil)], mark: nil
        )

        _ = try await client.recordFact(
            date: "2026-10-25", itemID: DayFixtures.readingID, body, idempotencyKey: "fact-2"
        )

        let value = try XCTUnwrap(((try bodyJSON())["values"] as? [[String: Any]])?.first)
        XCTAssertEqual(value["value"] as? Bool, true)
        // StrictBool on the server refuses 1; the wire must carry `true`.
        XCTAssertEqual(String(data: try XCTUnwrap(captured?.httpBody ?? captured?.httpBodyStream.map(Self.read)), encoding: .utf8)?.contains("\"value\":true"), true)
    }

    func testCorrectFactPutsToEntryPath() async throws {
        respond(Self.factWriteJSON)

        _ = try await client.correctFact(
            date: "2026-10-25", itemID: DayFixtures.pushupsID, entryID: 501,
            PlanFactRequestDTO(values: [PlanFactValueRequestDTO(fieldId: 70, value: .number(200), unit: "раз")], mark: "unmark")
        )

        XCTAssertEqual(captured?.httpMethod, "PUT")
        XCTAssertTrue(captured?.url?.path.hasSuffix("/facts/501") == true)
        XCTAssertEqual((try bodyJSON())["mark"] as? String, "unmark")
    }

    func testRemoveFactSendsUnmarkQueryOnlyWhenAsked() async throws {
        respond(Self.factWriteJSON)

        _ = try await client.removeFact(date: "2026-10-25", itemID: DayFixtures.pushupsID, entryID: 501, unmark: true)
        XCTAssertEqual(captured?.httpMethod, "DELETE")
        XCTAssertEqual(captured?.url?.query, "mark=unmark")

        _ = try await client.removeFact(date: "2026-10-25", itemID: DayFixtures.pushupsID, entryID: 501, unmark: false)
        XCTAssertNil(captured?.url?.query)
    }

    func testSaveNotebookPutsContent() async throws {
        respond(#"{"day_date":"2026-10-25","content":"Привет","updated_at":null}"#)

        try await client.saveNotebook(date: "2026-10-25", content: "Привет")

        XCTAssertEqual(captured?.httpMethod, "PUT")
        XCTAssertEqual(captured?.url?.path, "/api/v1/day/2026-10-25/notebook")
        XCTAssertEqual((try bodyJSON())["content"] as? String, "Привет")
    }

    func testClosingTouchesUseTheirOwnPathAndSendOnlyNamedFields() async throws {
        respond(Self.summaryJSON)
        let body = DayClosingRequestDTO(workMinutes: 420, bodyMd: nil)

        let review = try await client.reviewDay(date: "2026-10-25", body, idempotencyKey: "k1")
        XCTAssertEqual(captured?.url?.path, "/api/v1/day/2026-10-25/close/review")
        XCTAssertEqual(captured?.value(forHTTPHeaderField: "Idempotency-Key"), "k1")
        let json = try bodyJSON()
        XCTAssertEqual(json["work_minutes"] as? Int, 420)
        // The server reads null as "keep what is recorded"; an unnamed field is simply absent.
        XCTAssertNil(json["body_md"])
        XCTAssertEqual(review.stage, "reviewed")

        let final = try await client.closeDay(date: "2026-10-25", body, idempotencyKey: "k2")
        XCTAssertEqual(captured?.url?.path, "/api/v1/day/2026-10-25/close/final")
        XCTAssertEqual(final.stage, "reviewed")
    }

    func testRefusalSurfacesAsUnexpectedStatus() async {
        respond(#"{"detail":"nope"}"#, status: 409)
        do {
            _ = try await client.removeFact(date: "2026-10-25", itemID: DayFixtures.pushupsID, entryID: 1, unmark: false)
            XCTFail("expected a throw")
        } catch {
            XCTAssertEqual(error as? APIClientError, .unexpectedStatus(409))
        }
    }

    // MARK: Fixtures

    static let factWriteJSON = """
    {"entry_id": 502,
     "facts": {"item_id": "33333333-3333-4333-8333-333333333333",
               "link": {"category_id": 7, "category_name": "Отжимания", "category_active": true,
                        "field_id": 70, "field_name": "Повторы", "field_type": "number", "unit": "раз",
                        "target_value": 300.0, "state": "ok", "fields": []},
               "entries": [{"entry_id": 501, "entry_date": "2026-10-25", "values": [{"field_id": 70, "value": "100"}]},
                           {"entry_id": 502, "entry_date": "2026-10-25", "values": [{"field_id": 70, "value": "200"}]}],
               "total": 300.0, "done": true, "progress": "met"},
     "mark": {"item_id": "33333333-3333-4333-8333-333333333333", "state": "done", "note": null,
              "marked_at": "2026-10-25T09:00:00Z", "updated_at": "2026-10-25T09:00:00Z", "source": "web"}}
    """

    static let summaryJSON = """
    {"day_date": "2026-10-25", "closed": false, "stage": "reviewed", "reviewed_at": "2026-10-25T14:40:00Z",
     "review_skipped": false, "rule_set_id": 3, "verdict": null, "verdict_reason": "not_closed",
     "anchors_done": 1, "anchors_total": 2, "tasks_done": 1, "tasks_total": 1, "work_minutes": 420,
     "streak_after": null, "body_md": "", "missing_data": [], "missing_anchors": [], "clauses": []}
    """
}
