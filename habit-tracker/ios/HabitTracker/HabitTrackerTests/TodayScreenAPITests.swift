// [review:need-review] PHASE-01/210
// summary: wire-format tests for the #210 Today endpoints — quick-mark directory/tap/undo/day events, bulk avoid streaks, one-tap relapse with Idempotency-Key, relapse history
import XCTest
@testable import HabitTracker

final class TodayScreenAPITests: XCTestCase {
    private var client: APIClient!

    override func setUp() {
        super.setUp()
        client = APIClient(
            baseURL: URL(string: "http://localhost:8000")!,
            apiKeyProvider: { "secret" },
            session: MockURLProtocol.makeSession()
        )
    }

    override func tearDown() {
        MockURLProtocol.requestHandler = nil
        client = nil
        super.tearDown()
    }

    private static func response(
        _ request: URLRequest, status: Int = 200, body: String
    ) -> (HTTPURLResponse, Data) {
        let response = HTTPURLResponse(
            url: request.url!, statusCode: status, httpVersion: nil,
            headerFields: ["Content-Type": "application/json"]
        )!
        return (response, Data(body.utf8))
    }

    static func bodyData(of request: URLRequest) -> Data? {
        if let body = request.httpBody { return body }
        guard let stream = request.httpBodyStream else { return nil }
        stream.open()
        defer { stream.close() }
        var data = Data()
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 1024)
        defer { buffer.deallocate() }
        while stream.hasBytesAvailable {
            let read = stream.read(buffer, maxLength: 1024)
            if read <= 0 { break }
            data.append(buffer, count: read)
        }
        return data
    }

    func testFetchQuickMarksAsksTheIosSurfaceAndDecodesTheDayState() async throws {
        var captured: URLRequest?
        MockURLProtocol.requestHandler = { request in
            captured = request
            return Self.response(request, body: """
            [{"id": 3, "label": "Вода", "category_id": 1, "field_id": 10, "kind": "increment",
              "step": 0.25, "unit_label": "л", "icon": null, "color": null, "hotkey": null,
              "order": 0, "show_in_agent": true, "is_active": true,
              "entry_date": "2026-10-25", "today_total": 1.5, "done": true,
              "planned": true, "plan_item_id": "0b4e7c1e-0000-4000-8000-000000000001"}]
            """)
        }

        let marks = try await client.fetchQuickMarks()

        XCTAssertEqual(captured?.httpMethod, "GET")
        XCTAssertEqual(captured?.url?.path, "/api/v1/quick-marks")
        XCTAssertEqual(captured?.url?.query, "surface=ios")
        XCTAssertEqual(captured?.value(forHTTPHeaderField: "X-API-Key"), "secret")
        XCTAssertEqual(marks.count, 1)
        XCTAssertEqual(marks[0].label, "Вода")
        XCTAssertEqual(marks[0].kind, "increment")
        XCTAssertEqual(marks[0].step, 0.25)
        XCTAssertEqual(marks[0].todayTotal, 1.5)
        XCTAssertTrue(marks[0].done)
        XCTAssertTrue(marks[0].planned)
    }

    func testTapQuickMarkPostsOnlyTheIntentUnderAnIdempotencyKey() async throws {
        var captured: URLRequest?
        var body: Data?
        MockURLProtocol.requestHandler = { request in
            captured = request
            body = Self.bodyData(of: request)
            return Self.response(request, status: 201, body: """
            {"event_id": 91, "quick_mark_id": 3, "entry_id": 55, "entry_date": "2026-10-25",
             "occurred_at": "2026-10-25T09:00:00.123456+00:00", "today_total": 1.75, "done": true}
            """)
        }

        let event = try await client.tapQuickMark(
            id: 3,
            request: QuickMarkEventRequestDTO(
                value: nil, entryDate: "2026-10-25", utcOffsetMinutes: 180, source: "ios"
            ),
            idempotencyKey: "tap-key-1"
        )

        XCTAssertEqual(captured?.httpMethod, "POST")
        XCTAssertEqual(captured?.url?.path, "/api/v1/quick-marks/3/events")
        XCTAssertEqual(captured?.value(forHTTPHeaderField: "Idempotency-Key"), "tap-key-1")
        let json = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: XCTUnwrap(body)) as? [String: Any]
        )
        XCTAssertEqual(json["entry_date"] as? String, "2026-10-25")
        XCTAssertEqual(json["utc_offset_minutes"] as? Int, 180)
        XCTAssertEqual(json["source"] as? String, "ios")
        XCTAssertNil(json["value"], "an unset value must not be sent: the server applies the step")
        XCTAssertNil(json["category_id"], "the client sends an id, not a decision")
        XCTAssertEqual(event.eventId, 91)
        XCTAssertEqual(event.todayTotal, 1.75)
    }

    func testUndoQuickMarkEventPostsWithoutBody() async throws {
        var captured: URLRequest?
        MockURLProtocol.requestHandler = { request in
            captured = request
            return Self.response(request, body: """
            {"event_id": 91, "quick_mark_id": 3, "entry_date": "2026-10-25",
             "undone_at": "2026-10-25T09:01:00+00:00", "today_total": 1.5, "done": true}
            """)
        }

        let undone = try await client.undoQuickMarkEvent(id: 91)

        XCTAssertEqual(captured?.httpMethod, "POST")
        XCTAssertEqual(captured?.url?.path, "/api/v1/quick-marks/events/91/undo")
        XCTAssertEqual(undone.todayTotal, 1.5)
    }

    func testFetchQuickMarkDayEventsFiltersByCategory() async throws {
        var captured: URLRequest?
        MockURLProtocol.requestHandler = { request in
            captured = request
            return Self.response(request, body: """
            [{"event_id": 91, "quick_mark_id": 3, "label": "Вода", "kind": "increment",
              "unit_label": "л", "entry_date": "2026-10-25",
              "occurred_at": "2026-10-25T09:00:00+00:00", "delta": 0.25, "bool_value": null,
              "undone_at": null, "undoable": true}]
            """)
        }

        let events = try await client.fetchQuickMarkDayEvents(categoryId: 1)

        XCTAssertEqual(captured?.url?.path, "/api/v1/quick-marks/events")
        XCTAssertEqual(captured?.url?.query, "category_id=1")
        XCTAssertEqual(events.first?.delta, 0.25)
        XCTAssertEqual(events.first?.undoable, true)
        XCTAssertNil(events.first?.undoneAt)
    }

    func testFetchAvoidStreaksIsOneBulkRequest() async throws {
        var captured: [URLRequest] = []
        MockURLProtocol.requestHandler = { request in
            captured.append(request)
            return Self.response(request, body: """
            [{"category_id": 1, "streak_mode": "avoid", "current_streak": 4, "best_streak": 9,
              "last_relapse_date": "2026-10-21"},
             {"category_id": 2, "streak_mode": "avoid", "current_streak": 0, "best_streak": 0,
              "last_relapse_date": null}]
            """)
        }

        let streaks = try await client.fetchAvoidStreaks()

        XCTAssertEqual(captured.count, 1)
        XCTAssertEqual(captured.first?.url?.path, "/api/v1/streaks")
        XCTAssertEqual(captured.first?.url?.query, "streak_mode=avoid")
        XCTAssertEqual(streaks.map(\.categoryId), [1, 2])
        XCTAssertEqual(streaks.first?.currentStreak, 4)
    }

    func testRecordRelapseSendsNoBodyAndKeepsTheKeyAndDecodesCreated() async throws {
        var captured: URLRequest?
        MockURLProtocol.requestHandler = { request in
            captured = request
            return Self.response(request, status: 201, body: """
            {"id": 77, "category_id": 1, "entry_date": "2026-10-25", "notes": null,
             "created_at": "2026-10-25T09:00:00", "updated_at": "2026-10-25T09:00:00",
             "values": [{"id": 1, "entry_id": 77, "field_id": 10, "value": "true"}],
             "created": true}
            """)
        }

        let recorded = try await client.recordRelapse(categoryId: 1, idempotencyKey: "relapse-key")

        XCTAssertEqual(captured?.httpMethod, "POST")
        XCTAssertEqual(captured?.url?.path, "/api/v1/categories/1/relapses")
        XCTAssertEqual(captured?.value(forHTTPHeaderField: "Idempotency-Key"), "relapse-key")
        XCTAssertEqual(recorded.entry.id, 77)
        XCTAssertEqual(recorded.entry.values, [EntryValueDTO(fieldId: 10, value: "true")])
        XCTAssertTrue(recorded.created)
    }

    func testFetchRelapseHistoryDecodesTheDaysAndTheServersToday() async throws {
        var captured: URLRequest?
        MockURLProtocol.requestHandler = { request in
            captured = request
            return Self.response(request, body: """
            {"category_id": 1, "streak_mode": "avoid", "current_streak": 4, "best_streak": 9,
             "last_relapse_date": "2026-10-21", "tracked_since": "2026-08-01",
             "relapse_dates": ["2026-09-01", "2026-10-21"], "today": "2026-10-25"}
            """)
        }

        let history = try await client.fetchRelapseHistory(categoryId: 1)

        XCTAssertEqual(captured?.url?.path, "/api/v1/categories/1/relapses")
        XCTAssertEqual(history.relapseDates, ["2026-09-01", "2026-10-21"])
        XCTAssertEqual(history.trackedSince, "2026-08-01")
        XCTAssertEqual(history.today, "2026-10-25")
        XCTAssertEqual(history.currentStreak, 4)
    }
}
