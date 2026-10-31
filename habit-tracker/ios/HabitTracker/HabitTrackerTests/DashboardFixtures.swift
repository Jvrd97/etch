// [review:need-review] PHASE-03/304
// summary: server-shaped answers of GET /dashboard/summary — a full week (all blocks), a month, and an empty one (every block `null` or empty) — as JSON with the real field names, plus a helper that decodes them
import Foundation
@testable import HabitTracker

enum DashboardFixtures {
    static let weekJSON = """
    {
      "period": "week", "from": "2026-10-25", "to": "2026-10-31", "today": "2026-10-31",
      "scores": {
        "health": {"value": 78, "label": "good", "basis_days": 7},
        "habits": {"value": 64, "done": 45, "total": 70},
        "challenges": {"done": 3, "total": 5}
      },
      "streaks": [
        {"category_id": 1, "name": "Бег", "kind": "build", "current": 4, "best": 12,
         "days": [true, true, false, null, true, true, true]},
        {"category_id": 2, "name": "Сахар", "kind": "avoid", "current": 9, "best": 9,
         "days": [true, true, true, true, true, true, true]}
      ],
      "health": [
        {"identifier": "HKQuantityTypeIdentifierRestingHeartRate", "label": "Пульс покоя", "value": 58,
         "unit": "count/min", "baseline_delta": -2, "higher_is_better": false},
        {"identifier": "HKQuantityTypeIdentifierStepCount", "label": "Шаги", "value": 7200,
         "unit": "count", "baseline_delta": -1200, "higher_is_better": true},
        {"identifier": "HKCategoryTypeIdentifierSleepAnalysis", "label": "Сон", "value": 435,
         "unit": "min", "baseline_delta": null, "higher_is_better": true}
      ],
      "bests": [
        {"identifier": "HKQuantityTypeIdentifierStepCount", "label": "Шаги", "value": 12040,
         "unit": "count", "date": "2026-10-30", "is_record": true},
        {"identifier": "HKCategoryTypeIdentifierSleepAnalysis", "label": "Сон", "value": 500,
         "unit": "min", "date": "2026-10-28", "is_record": false}
      ],
      "workouts": {
        "weeks": [{"week_start": "2026-10-19", "count": 2, "minutes": 90},
                  {"week_start": "2026-10-26", "count": 3, "minutes": 150}],
        "total": 3, "delta_vs_previous": 1
      },
      "insight": {"text": "Сон стал длиннее, шаги просели.", "generated_at": "2026-10-31T09:00:00+03:00"}
    }
    """

    static let emptyJSON = """
    {
      "period": "month", "from": "2026-10-02", "to": "2026-10-31", "today": "2026-10-31",
      "scores": {
        "health": {"value": null, "label": null, "basis_days": 2},
        "habits": {"value": null, "done": null, "total": null},
        "challenges": {"done": null, "total": null}
      },
      "streaks": [], "health": [], "bests": [],
      "workouts": {"weeks": [], "total": null, "delta_vs_previous": null},
      "insight": null
    }
    """

    static func decode(_ json: String) throws -> DashboardSummaryDTO {
        try APIJSONCoding.makeDecoder().decode(DashboardSummaryDTO.self, from: Data(json.utf8))
    }

    static func week() throws -> DashboardSummaryDTO { try decode(weekJSON) }

    static func empty() throws -> DashboardSummaryDTO { try decode(emptyJSON) }

    /// The week answer relabelled as another period, so a test can tell two answers apart.
    static func month() throws -> DashboardSummaryDTO {
        try decode(weekJSON.replacingOccurrences(of: #""period": "week""#, with: #""period": "month""#)
            .replacingOccurrences(of: #""from": "2026-10-25""#, with: #""from": "2026-10-02""#))
    }
}
