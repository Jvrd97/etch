// [review:need-review] PHASE-03/229, PHASE-03/243
// summary: a server-shaped answer of GET /week-review for a finished week (three judged days, two roles, one category, one avoid streak, sleep not connected) as JSON, with helpers to patch it into a running or an empty week
import Foundation
@testable import HabitTracker

enum WeekFixtures {
    static let reviewJSON = """
    {
      "window": {
        "iso_code": "2026-W35", "starts_on": "2026-08-24", "ends_on": "2026-08-30",
        "timezone": "Europe/Berlin", "day_start_hour": 4, "is_complete": true,
        "counted_days": 7, "today_counted": false, "as_of": "2026-08-30",
        "previous_iso_code": "2026-W34", "next_iso_code": "2026-W36", "compared_days": 7
      },
      "totals": {
        "closed_days": 3, "won_days": 2, "lost_days": 1, "tasks_done": 8, "tasks_total": 12,
        "plan_pct": 67, "anchors_done": 2, "anchors_total": 2, "work_minutes": 1200,
        "role_minutes": 400, "days_total": 3, "day_streak_end": 1
      },
      "previous_totals": {
        "closed_days": 2, "won_days": 1, "lost_days": 1, "tasks_done": 3, "tasks_total": 8,
        "plan_pct": 38, "anchors_done": 0, "anchors_total": 0, "work_minutes": 400,
        "role_minutes": 100, "days_total": 2, "day_streak_end": 0
      },
      "delta": {"won_days": 1, "tasks_done": 5, "plan_pct": 29, "work_minutes": 800, "role_minutes": 300},
      "debt_minutes": 0,
      "is_won": false,
      "verdict_line": "Неделя выиграна: нет (правило: выиграны все дни недели и нет долга за переработку; выиграно 2 из 3 дней, долг 0 мин).",
      "days": [
        {"date": "2026-08-24", "weekday": 0, "counted": true, "verdict": "won", "tasks_done": 4, "tasks_total": 4, "plan_pct": 100, "work_minutes": null, "role_minutes": 0, "streak_after": null},
        {"date": "2026-08-25", "weekday": 1, "counted": true, "verdict": "lost", "tasks_done": 1, "tasks_total": 4, "plan_pct": 25, "work_minutes": null, "role_minutes": 0, "streak_after": null},
        {"date": "2026-08-26", "weekday": 2, "counted": true, "verdict": "won", "tasks_done": 3, "tasks_total": 4, "plan_pct": 75, "work_minutes": null, "role_minutes": 0, "streak_after": null},
        {"date": "2026-08-27", "weekday": 3, "counted": true, "verdict": null, "tasks_done": 0, "tasks_total": 0, "plan_pct": null, "work_minutes": null, "role_minutes": 0, "streak_after": null},
        {"date": "2026-08-28", "weekday": 4, "counted": true, "verdict": null, "tasks_done": 0, "tasks_total": 0, "plan_pct": null, "work_minutes": null, "role_minutes": 0, "streak_after": null},
        {"date": "2026-08-29", "weekday": 5, "counted": true, "verdict": null, "tasks_done": 0, "tasks_total": 0, "plan_pct": null, "work_minutes": null, "role_minutes": 0, "streak_after": null},
        {"date": "2026-08-30", "weekday": 6, "counted": true, "verdict": null, "tasks_done": 0, "tasks_total": 0, "plan_pct": null, "work_minutes": null, "role_minutes": 0, "streak_after": null}
      ],
      "best_day": "2026-08-24",
      "worst_day": "2026-08-25",
      "roles": [
        {"role_id": 1, "role_code": "techlead", "title": "Тимлид", "minutes": 300, "share_pct": 75, "target_share_pct": 50, "previous_minutes": 100, "delta_minutes": 200},
        {"role_id": 2, "role_code": "architect", "title": "Архитектор", "minutes": 0, "share_pct": 0, "target_share_pct": null, "previous_minutes": 0, "delta_minutes": 0}
      ],
      "categories": [
        {"category_id": 5, "name": "Бег", "minutes": 60, "previous_minutes": 15, "delta_minutes": 45, "entry_days": 2, "previous_entry_days": 1}
      ],
      "habit_streaks": [
        {"category_id": 9, "name": "Курение", "current_streak": 4, "relapses": 1}
      ],
      "health": [
        {"key": "sleep", "name": "Сон", "unit": null, "available": false, "total": null, "avg_per_day": null, "days_with_data": 0, "previous_days_with_data": 0, "previous_avg_per_day": null, "delta_avg_per_day": null, "daily": [null, null, null, null, null, null, null]},
        {"key": "steps", "name": "Шаги", "unit": "count", "available": true, "total": 12000, "avg_per_day": 6000, "days_with_data": 2, "previous_days_with_data": 1, "previous_avg_per_day": 3000, "delta_avg_per_day": 3000, "daily": [8000, 4000, null, null, null, null, null]},
        {"key": "workouts", "name": "Минуты тренировки", "unit": "min", "available": true, "total": 45, "avg_per_day": 45, "days_with_data": 1, "previous_days_with_data": 0, "previous_avg_per_day": null, "delta_avg_per_day": null, "daily": [null, null, null, null, null, null, 45]}
      ]
    }
    """

    static func review(patch: (inout [String: Any]) -> Void = { _ in }) throws -> WeekReviewDTO {
        var object = try XCTUnwrapJSON(Data(reviewJSON.utf8))
        patch(&object)
        let data = try JSONSerialization.data(withJSONObject: object)
        return try APIJSONCoding.makeDecoder().decode(WeekReviewDTO.self, from: data)
    }

    /// The running week: three of seven days counted, compared with the first three of the last week.
    /// `iso` moves the dates too, so a test can say which week "now" falls in.
    static func runningWeek(iso: String = "2026-W35") throws -> WeekReviewDTO {
        try review { object in
            var window = object["window"] as? [String: Any] ?? [:]
            window["iso_code"] = iso
            setDates(of: &window, forIso: iso)
            window["is_complete"] = false
            window["counted_days"] = 3
            window["compared_days"] = 3
            window["as_of"] = "2026-08-26"
            object["window"] = window
            object["is_won"] = NSNull()
        }
    }

    /// The week of Monday 24 August 2026 (`2026-W35`) shifted by whole weeks: its Monday and Sunday.
    private static func setDates(of window: inout [String: Any], forIso iso: String) {
        guard let number = Int(iso.suffix(2)) else { return }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let formatter = DateFormatter()
        formatter.calendar = calendar
        formatter.timeZone = calendar.timeZone
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        let anchor = calendar.date(from: DateComponents(year: 2026, month: 8, day: 24))!
        let weeks = number - 35
        window["starts_on"] = formatter.string(from: calendar.date(byAdding: .day, value: weeks * 7, to: anchor)!)
        window["ends_on"] = formatter.string(from: calendar.date(byAdding: .day, value: weeks * 7 + 6, to: anchor)!)
    }

    /// A week with no counted day: the server gives it `counted_days = 0` and no «as of», whether the
    /// week is still ahead or it is Monday and Monday is not closed yet. Only the calendar tells them apart.
    static func unclosedWeek(iso: String) throws -> WeekReviewDTO {
        try review { object in
            var window = object["window"] as? [String: Any] ?? [:]
            window["iso_code"] = iso
            setDates(of: &window, forIso: iso)
            window["is_complete"] = false
            window["counted_days"] = 0
            window["compared_days"] = 0
            window["as_of"] = NSNull()
            object["window"] = window
            object["is_won"] = NSNull()
        }
    }

    /// Nothing at all in the week: the server's emptiness test holds. `healthDays` puts back one sign of life.
    static func emptyWeek(healthDays: Int = 0) throws -> WeekReviewDTO {
        try review { object in
            var totals = object["totals"] as? [String: Any] ?? [:]
            for key in ["closed_days", "won_days", "lost_days", "tasks_done", "tasks_total", "role_minutes"] {
                totals[key] = 0
            }
            object["totals"] = totals
            object["categories"] = []
            object["habit_streaks"] = []
            object["best_day"] = NSNull()
            object["worst_day"] = NSNull()
            let health = (object["health"] as? [[String: Any]] ?? []).map { metric -> [String: Any] in
                var metric = metric
                metric["days_with_data"] = metric["key"] as? String == "steps" ? healthDays : 0
                return metric
            }
            object["health"] = health
        }
    }

    /// The same answer named as another week, for navigation tests.
    static func week(_ iso: String, previous: String, next: String) throws -> WeekReviewDTO {
        try review { object in
            var window = object["window"] as? [String: Any] ?? [:]
            window["iso_code"] = iso
            window["previous_iso_code"] = previous
            window["next_iso_code"] = next
            setDates(of: &window, forIso: iso)
            object["window"] = window
        }
    }

    private static func XCTUnwrapJSON(_ data: Data) throws -> [String: Any] {
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw APIClientError.invalidResponse
        }
        return object
    }
}
