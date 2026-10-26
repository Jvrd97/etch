// [review:need-review] PHASE-01/211
// summary: server-shaped JSON of GET /day (built from the backend schemas DayDetailResponse, PlanResponse, PlanItemFactsResponse, DaySummaryResponse, with the blocks iOS ignores left in) and a scriptable DayAPI double for the Day tests
import Foundation
@testable import HabitTracker

enum DayFixtures {
    static let taskID = UUID(uuidString: "11111111-1111-4111-8111-111111111111")!
    static let minimumID = UUID(uuidString: "22222222-2222-4222-8222-222222222222")!
    static let pushupsID = UUID(uuidString: "33333333-3333-4333-8333-333333333333")!
    static let readingID = UUID(uuidString: "44444444-4444-4444-8444-444444444444")!
    static let date = "2026-10-25"

    /// A work day with a task (+ its minimum), a pushups line linked to category 7
    /// (target 300, 100 recorded), and a line linked to a checkbox (not yet done).
    static let dayJSON = """
    {
      "day": {"date": "2026-10-25", "kind": "work", "is_nocode": false,
              "opened_at": "2026-10-25T04:00:00Z", "last_touched_at": null},
      "rule": {"id": 3, "valid_from": "2026-08-17", "valid_to": null, "timezone": "Europe/Berlin",
               "day_start_hour": 4, "work_cap_min": 480, "max_work_tasks": 3, "tasks_required_ratio": "0.80",
               "workdays": [1,2,3,4,5], "note_md": ""},
      "profile": null,
      "day_map": {"rule_set_id": 3, "edges": [], "anchors": [], "verdict_reasons": ["overtime"]},
      "plan": {
        "id": "99999999-9999-4999-8999-999999999999", "day_date": "2026-10-25", "title": null,
        "lede": "Фокус: релиз", "status": "accepted", "source": "llm", "needs_review": false,
        "fallback_reason": null, "counters": [], "schedule": [], "overlaps": [],
        "sections": [
          {"id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "ord": 0, "title": "Работа", "kind": "work", "role_id": null,
           "items": [
             {"id": "11111111-1111-4111-8111-111111111111", "parent_id": null, "ord": 0, "kind": "task",
              "rigidity": "soft", "text_md": "**Релиз** iOS", "text_plain": "Релиз iOS",
              "starts_at": "2026-10-25T08:00:00Z", "ends_at": "2026-10-25T10:30:00Z", "code": "W1",
              "category_id": null, "field_id": null, "target_value": null, "extra": {},
              "children": [
                {"id": "22222222-2222-4222-8222-222222222222", "parent_id": "11111111-1111-4111-8111-111111111111",
                 "ord": 0, "kind": "minimum", "rigidity": "soft", "text_md": "Минимум", "text_plain": "Минимум: собрать сборку",
                 "starts_at": null, "ends_at": null, "code": null, "category_id": null, "field_id": null,
                 "target_value": null, "extra": {}, "children": []}
              ]}
           ]},
          {"id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "ord": 1, "title": "Спорт", "kind": "training", "role_id": null,
           "items": [
             {"id": "33333333-3333-4333-8333-333333333333", "parent_id": null, "ord": 0, "kind": "bullet",
              "rigidity": "soft", "text_md": "Отжимания", "text_plain": "Отжимания",
              "starts_at": "2026-10-25T05:00:00Z", "ends_at": null, "code": null,
              "category_id": 7, "field_id": 70, "target_value": 300.0, "extra": {}, "children": []},
             {"id": "44444444-4444-4444-8444-444444444444", "parent_id": null, "ord": 1, "kind": "bullet",
              "rigidity": "soft", "text_md": "Чтение", "text_plain": "Чтение",
              "starts_at": null, "ends_at": null, "code": null,
              "category_id": 8, "field_id": 80, "target_value": null, "extra": {}, "children": []}
           ]}
        ]
      },
      "has_plan": true,
      "marks": [
        {"item_id": "11111111-1111-4111-8111-111111111111", "state": "done", "note": "ок",
         "marked_at": "2026-10-25T09:00:00Z", "updated_at": "2026-10-25T09:00:00Z", "source": "web"}
      ],
      "plan_facts": [
        {"item_id": "33333333-3333-4333-8333-333333333333",
         "link": {"category_id": 7, "category_name": "Отжимания", "category_active": true,
                  "field_id": 70, "field_name": "Повторы", "field_type": "number", "unit": "раз",
                  "target_value": 300.0, "state": "ok",
                  "fields": [{"id": 70, "name": "Повторы", "field_type": "number", "unit": "раз"}]},
         "entries": [{"entry_id": 501, "entry_date": "2026-10-25",
                      "values": [{"field_id": 70, "value": "100"}],
                      "created_at": "2026-10-25T05:10:00Z", "updated_at": "2026-10-25T05:10:00Z"}],
         "total": 100.0, "done": true, "progress": "partial"},
        {"item_id": "44444444-4444-4444-8444-444444444444",
         "link": {"category_id": 8, "category_name": "Чтение", "category_active": true,
                  "field_id": 80, "field_name": "Читал", "field_type": "boolean", "unit": null,
                  "target_value": null, "state": "ok",
                  "fields": [{"id": 80, "name": "Читал", "field_type": "boolean", "unit": null}]},
         "entries": [], "total": null, "done": false, "progress": "none"}
      ],
      "task_counts": {"planned": 1, "done": 1, "failed": 0, "skipped": 0, "pending": 0},
      "notebook": "Заметка дня",
      "anchors": {"day_date": "2026-10-25", "anchors": [], "done": 0, "total": 0, "missing": []},
      "training": null,
      "summary": {"day_date": "2026-10-25", "closed": false, "stage": "open", "reviewed_at": null,
                  "review_skipped": false, "rule_set_id": 3, "verdict": null, "verdict_reason": "not_closed",
                  "verdict_override": false, "verdict_override_note": null,
                  "anchors_done": 0, "anchors_total": 2, "tasks_done": 1, "tasks_total": 1,
                  "work_minutes": null, "streak_after": null, "wrote_from_scratch": null,
                  "education_debt": null, "reviewed_today": null, "body_md": "",
                  "missing_data": ["work_minutes"], "missing_anchors": ["Подъём"], "source": "close",
                  "verdict_origin": "none",
                  "clauses": [{"code": "tasks", "passed": true, "detail": "1 из 1"}]},
      "work": {"day_date": "2026-10-25", "intervals": [], "work_minutes": null, "running": false}
    }
    """

    static func day() throws -> DayDetailDTO {
        try APIJSONCoding.makeDecoder().decode(DayDetailDTO.self, from: Data(dayJSON.utf8))
    }

    /// The fixture day as the server would answer after a write: same plan, new marks/facts/summary.
    static func day(
        date: String? = nil, notebook: String?? = nil,
        marks: [DayMarkDTO]? = nil, planFacts: [PlanItemFactsDTO]? = nil, summary: DaySummaryDTO? = nil
    ) throws -> DayDetailDTO {
        let base = try day()
        let head = date.map {
            DayHeadDTO(date: $0, kind: base.day.kind, isNocode: base.day.isNocode, openedAt: base.day.openedAt)
        } ?? base.day
        return DayDetailDTO(
            day: head, rule: base.rule, plan: base.plan, hasPlan: base.hasPlan,
            marks: marks ?? base.marks, planFacts: planFacts ?? base.planFacts, taskCounts: base.taskCounts,
            notebook: notebook ?? base.notebook, summary: summary ?? base.summary
        )
    }

    static func mark(_ id: UUID, _ state: String?, note: String? = nil) -> DayMarkDTO {
        DayMarkDTO(itemId: id, state: state, note: note)
    }

    static func summary(stage: String = "closed", verdict: String? = "won", reason: String = "") -> DaySummaryDTO {
        DaySummaryDTO(
            dayDate: date, closed: stage == "closed", stage: stage, reviewSkipped: false, verdict: verdict,
            verdictReason: reason, anchorsDone: 2, anchorsTotal: 2, tasksDone: 1, tasksTotal: 1,
            workMinutes: 420, streakAfter: 4, bodyMd: "итог", missingAnchors: [], clauses: []
        )
    }
}

/// Scriptable `DayAPI`: each closure answers one endpoint, every call is recorded.
final class MockDayAPI: DayAPI {
    var fetchResults: [Result<DayDetailDTO, Error>] = []
    var fetchedDates: [String?] = []
    var markResult: Result<DayMarkDTO, Error> = .failure(APIClientError.invalidResponse)
    var markCalls: [(date: String, id: UUID, body: DayMarkRequestDTO)] = []
    var factResult: Result<PlanFactWriteDTO, Error> = .failure(APIClientError.invalidResponse)
    var recordCalls: [(id: UUID, body: PlanFactRequestDTO, key: String)] = []
    var correctCalls: [(id: UUID, entry: Int, body: PlanFactRequestDTO)] = []
    var removeCalls: [(id: UUID, entry: Int, unmark: Bool)] = []
    var notebookCalls: [String] = []
    var notebookError: Error?
    var closingResult: Result<DaySummaryDTO, Error> = .failure(APIClientError.invalidResponse)
    var closingCalls: [(touch: String, body: DayClosingRequestDTO, key: String)] = []

    func fetchDay(date: String?) async throws -> DayDetailDTO {
        fetchedDates.append(date)
        guard !fetchResults.isEmpty else { throw APIClientError.invalidResponse }
        let result = fetchResults.count > 1 ? fetchResults.removeFirst() : fetchResults[0]
        return try result.get()
    }

    func setMark(date: String, itemID: UUID, _ payload: DayMarkRequestDTO) async throws -> DayMarkDTO {
        markCalls.append((date, itemID, payload))
        return try markResult.get()
    }

    func recordFact(date: String, itemID: UUID, _ payload: PlanFactRequestDTO, idempotencyKey: String) async throws -> PlanFactWriteDTO {
        recordCalls.append((itemID, payload, idempotencyKey))
        return try factResult.get()
    }

    func correctFact(date: String, itemID: UUID, entryID: Int, _ payload: PlanFactRequestDTO) async throws -> PlanFactWriteDTO {
        correctCalls.append((itemID, entryID, payload))
        return try factResult.get()
    }

    func removeFact(date: String, itemID: UUID, entryID: Int, unmark: Bool) async throws -> PlanFactWriteDTO {
        removeCalls.append((itemID, entryID, unmark))
        return try factResult.get()
    }

    func saveNotebook(date: String, content: String) async throws {
        notebookCalls.append(content)
        if let notebookError { throw notebookError }
    }

    func reviewDay(date: String, _ payload: DayClosingRequestDTO, idempotencyKey: String) async throws -> DaySummaryDTO {
        closingCalls.append(("review", payload, idempotencyKey))
        return try closingResult.get()
    }

    func closeDay(date: String, _ payload: DayClosingRequestDTO, idempotencyKey: String) async throws -> DaySummaryDTO {
        closingCalls.append(("final", payload, idempotencyKey))
        return try closingResult.get()
    }
}
