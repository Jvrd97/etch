// [review:need-review] PHASE-03/230
// summary: tests of the plan operations the voice summary and the chat share — one set of types reads both server shapes (the chat plan without existing_entry_id, the draft with it), a flag the server leaves out is false, an operation echoes back with its op, the chat's journal never carries replace
import XCTest
@testable import HabitTracker

final class PlanOperationDTOTests: XCTestCase {
    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try APIJSONCoding.makeDecoder().decode(type, from: Data(json.utf8))
    }

    private func object<T: Encodable>(_ value: T) throws -> [String: Any] {
        let data = try APIJSONCoding.makeEncoder().encode(value)
        return try XCTUnwrap(try JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    func testAChatPlanBodyIsMadeOfTheSharedOperations() throws {
        let body = try decode(ChatPlanBodyDTO.self, """
        {"entry_date": "2026-10-25",
         "metrics": [{"op": "log_metric", "category_id": 1, "field_id": 2, "value": 30.0,
                      "source_text": "отжался 30 раз", "uncertain": false,
                      "implausible": false, "estimated": false}],
         "checklist": [{"op": "check", "category_id": 3, "field_id": 5,
                        "source_text": "витамины", "uncertain": true}],
         "journal": {"op": "write_journal", "title": null, "content": "Хороший день",
                     "mood": null, "tags": null, "mode": "create"}}
        """)

        let metrics: [LogMetricOpDTO] = body.metrics
        let checklist: [CheckOpDTO] = body.checklist
        let journal: JournalOpDTO? = body.journal
        XCTAssertEqual(metrics.first?.value, 30)
        XCTAssertEqual(checklist.first?.uncertain, true)
        XCTAssertEqual(journal?.mode, .create)
        XCTAssertNil(journal?.existingEntryId, "the chat plan has no existing entry to point at")
    }

    func testAFlagTheServerLeavesOutIsFalse() throws {
        let metric = try decode(LogMetricOpDTO.self, """
        {"category_id": 1, "field_id": 2, "value": 3.0, "source_text": "три"}
        """)
        let check = try decode(CheckOpDTO.self, """
        {"category_id": 3, "field_id": 5, "source_text": "витамины"}
        """)

        XCTAssertFalse(metric.uncertain || metric.implausible || metric.estimated)
        XCTAssertTrue(metric.isTickedByDefault)
        XCTAssertFalse(check.uncertain)
        XCTAssertEqual(metric.op, "log_metric")
        XCTAssertEqual(check.op, "check")
    }

    func testTheDraftJournalKeepsTheEntryItWillMeet() throws {
        let journal = try decode(JournalOpDTO.self, """
        {"op": "write_journal", "title": null, "content": "День", "mood": null, "tags": null,
         "mode": "append", "existing_entry_id": 55}
        """)

        XCTAssertEqual(journal.existingEntryId, 55)
        XCTAssertEqual(journal.mode, .append)
    }

    func testEveryOperationEchoesBackWithItsOpAndWithoutAnAbsentEntryId() throws {
        let metric = try object(LogMetricOpDTO(categoryId: 1, fieldId: 2, value: 3, sourceText: "три"))
        let check = try object(CheckOpDTO(categoryId: 3, fieldId: 5, sourceText: "витамины"))
        let journal = try object(
            JournalOpDTO(title: nil, content: "День", mood: nil, tags: nil, mode: .create)
        )

        XCTAssertEqual(metric["op"] as? String, "log_metric")
        XCTAssertEqual(check["op"] as? String, "check")
        XCTAssertEqual(journal["op"] as? String, "write_journal")
        XCTAssertEqual(journal["mode"] as? String, "create")
        XCTAssertNil(journal["existing_entry_id"])
    }

    func testTheSelectionTheChatSendsCarriesTheOperationsUnchanged() throws {
        let metric = LogMetricOpDTO(
            categoryId: 1, fieldId: 2, value: 3, sourceText: "три", implausible: true
        )
        let selection = ChatPlanSelectionDTO(metrics: [metric], checklist: [], journal: nil, dayPlan: false)

        let sent = try object(selection)

        let sentMetric = try XCTUnwrap((sent["metrics"] as? [[String: Any]])?.first)
        XCTAssertEqual(sentMetric["implausible"] as? Bool, true)
        XCTAssertEqual(sentMetric["op"] as? String, "log_metric")
    }
}
