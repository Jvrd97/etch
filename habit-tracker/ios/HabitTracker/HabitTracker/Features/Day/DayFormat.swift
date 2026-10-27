// [review:need-review] PHASE-01/211, PHASE-03/226
// summary: pure helpers of the Day screen — day-string arithmetic (yyyy-MM-dd), plan window text read in the device's timezone (formatters are cached, not rebuilt per call), the mark cycle (none -> done -> failed -> none), Russian labels of marks, task counts, closing stage/verdict and verdict reason
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

    private static let calendar: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC") ?? .current
        return calendar
    }()

    private static func makeFormatter(dateFormat: String, locale: String = "en_US_POSIX", timeZone: TimeZone) -> DateFormatter {
        let formatter = DateFormatter()
        formatter.calendar = calendar
        formatter.locale = Locale(identifier: locale)
        formatter.timeZone = timeZone
        formatter.dateFormat = dateFormat
        return formatter
    }

    private static let dayStringFormatter = makeFormatter(dateFormat: "yyyy-MM-dd", timeZone: calendar.timeZone)
    private static let titleFormatter = makeFormatter(dateFormat: "d MMMM, EEE", locale: "ru_RU", timeZone: calendar.timeZone)

    /// One `HH:mm` formatter per zone: a zone is never set on a shared formatter, so a read in
    /// one zone cannot leak into another. `DateFormatter` itself is safe to use from any thread.
    private final class ClockFormatters: @unchecked Sendable {
        private let lock = NSLock()
        private var byZone: [String: DateFormatter] = [:]

        func formatter(for timeZone: TimeZone) -> DateFormatter {
            lock.lock()
            defer { lock.unlock() }
            if let cached = byZone[timeZone.identifier] { return cached }
            let made = DayFormat.makeFormatter(dateFormat: "HH:mm", timeZone: timeZone)
            byZone[timeZone.identifier] = made
            return made
        }
    }

    private static let clockFormatters = ClockFormatters()

    /// `2026-10-25` moved by `days`; nil when the string is not a date.
    static func shift(_ day: String, by days: Int) -> String? {
        guard let date = dayStringFormatter.date(from: day),
              let moved = calendar.date(byAdding: .day, value: days, to: date) else { return nil }
        return dayStringFormatter.string(from: moved)
    }

    /// `2026-10-25` as "25 октября, вс".
    static func title(of day: String) -> String {
        guard let date = dayStringFormatter.date(from: day) else { return day }
        return titleFormatter.string(from: date)
    }

    // MARK: Plan windows

    private static let plainTimestamp: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private static let fractionalTimestamp: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private static func parseTimestamp(_ iso: String) -> Date? {
        plainTimestamp.date(from: iso) ?? fractionalTimestamp.date(from: iso)
    }

    /// The `HH:mm` of a timestamp on the wall clock of the reader's device. The server sends
    /// instants (UTC) and decides which day they belong to; what the clock shows is the
    /// reader's own zone, as on the mobile web (`frontend/lib/time.ts`, acceptance 5.7).
    /// `timeZone` is a parameter so tests do not depend on the machine's setting.
    static func clock(_ iso: String, in timeZone: TimeZone = .current) -> String? {
        guard let date = parseTimestamp(iso) else { return nil }
        return clockFormatters.formatter(for: timeZone).string(from: date)
    }

    /// "06:00" for a point, "09:00–11:30" for a window, nil for an unscheduled line.
    static func window(start: String?, end: String?, in timeZone: TimeZone = .current) -> String? {
        guard let start, let from = clock(start, in: timeZone) else { return nil }
        guard let end, let to = clock(end, in: timeZone) else { return from }
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

    /// Shown above "Закрыть день": the app has no anchors, yet closing counts them, so a day
    /// can come out "проигран" for `anchors`.
    static let anchorsHint = "Якоря отмечаются в вебе: здесь их нет, а закрытие дня их учитывает."

    /// Closing counts anchors, so the hint matters only when the day has some.
    static func showsAnchorsHint(_ summary: DaySummaryDTO?) -> Bool {
        (summary?.anchorsTotal ?? 0) > 0
    }

    /// The tick button reads its line aloud: with many lines a bare "Отметка: сделано" is ambiguous.
    static func markAccessibilityLabel(for text: String, state: String?) -> String {
        "Отметка «\(text)»: \(markLabel(state))"
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
