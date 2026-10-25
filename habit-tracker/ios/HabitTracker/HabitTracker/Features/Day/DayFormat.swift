// [review:need-review] PHASE-01/211
// summary: pure helpers of the Day screen — day-string arithmetic (yyyy-MM-dd), plan window text read in the rule's timezone, the mark cycle (none -> done -> failed -> none), Russian labels of marks, task counts, closing stage/verdict and verdict reason
import Foundation

enum DayFormat {
    /// The ring a tap walks; `nil` is "no mark". `skipped` (set elsewhere) returns to none.
    static func nextMark(after state: String?) -> String? {
        switch state {
        case nil: return "done"
        case "done": return "failed"
        default: return nil
        }
    }

    static func markLabel(_ state: String?) -> String {
        switch state {
        case "done": return "сделано"
        case "failed": return "не сделано"
        case "skipped": return "пропущено"
        default: return "не отмечено"
        }
    }

    // MARK: Dates

    private static var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC") ?? .current
        return calendar
    }

    private static func dayFormatter(dateFormat: String, locale: String = "en_US_POSIX") -> DateFormatter {
        let formatter = DateFormatter()
        formatter.calendar = calendar
        formatter.locale = Locale(identifier: locale)
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = dateFormat
        return formatter
    }

    /// `2026-10-25` moved by `days`; nil when the string is not a date.
    static func shift(_ day: String, by days: Int) -> String? {
        let formatter = dayFormatter(dateFormat: "yyyy-MM-dd")
        guard let date = formatter.date(from: day),
              let moved = calendar.date(byAdding: .day, value: days, to: date) else { return nil }
        return formatter.string(from: moved)
    }

    /// `2026-10-25` as "25 октября, вс".
    static func title(of day: String) -> String {
        guard let date = dayFormatter(dateFormat: "yyyy-MM-dd").date(from: day) else { return day }
        return dayFormatter(dateFormat: "d MMMM, EEE", locale: "ru_RU").string(from: date)
    }

    // MARK: Plan windows

    private static func parseTimestamp(_ iso: String) -> Date? {
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        if let date = plain.date(from: iso) { return date }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return fractional.date(from: iso)
    }

    /// The `HH:mm` of a timestamp on the wall clock of the day's rule. The server sends
    /// instants (UTC), and "06:00" only means something in the zone the plan was written in.
    static func clock(_ iso: String, timeZoneID: String) -> String? {
        guard let date = parseTimestamp(iso) else { return nil }
        let formatter = dayFormatter(dateFormat: "HH:mm")
        formatter.timeZone = TimeZone(identifier: timeZoneID) ?? .current
        return formatter.string(from: date)
    }

    /// "06:00" for a point, "09:00–11:30" for a window, nil for an unscheduled line.
    static func window(start: String?, end: String?, timeZoneID: String) -> String? {
        guard let start, let from = clock(start, timeZoneID: timeZoneID) else { return nil }
        guard let end, let to = clock(end, timeZoneID: timeZoneID) else { return from }
        return "\(from)–\(to)"
    }

    // MARK: Header and closing

    /// "закрыто 2 из 4 · не сделано 1 · снято 1".
    static func countsLine(_ counts: TaskCountsDTO) -> String {
        var parts = ["закрыто \(counts.done) из \(counts.planned)"]
        if counts.failed > 0 { parts.append("не сделано \(counts.failed)") }
        if counts.skipped > 0 { parts.append("снято \(counts.skipped)") }
        return parts.joined(separator: " · ")
    }

    /// The headline by stage, not by the empty verdict alone: after the 15:40 touch
    /// `verdict == nil` means "рано", not "проиграл".
    static func headline(_ summary: DaySummaryDTO) -> String {
        switch (summary.verdict, summary.stage) {
        case ("won", _): return "День выигран"
        case ("lost", _): return "День проигран"
        case (_, "reviewed"): return "Вердикт будет вечером"
        default: return "День не закрыт"
        }
    }

    static func reasonLabel(_ code: String) -> String {
        switch code {
        case "": return ""
        case "tasks": return "задачи"
        case "anchors": return "якоря"
        case "overtime": return "переработка"
        case "not_closed": return "день не закрыт"
        case "role_act": return "акт роли"
        default: return code
        }
    }

    static func kindLabel(_ kind: String) -> String {
        kind == "work" ? "рабочий день" : "выходной"
    }
}
