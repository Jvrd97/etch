// [review:need-review] PHASE-03/228
// summary: the part of GET /agent/config the floating panel draws — the task the day is on, the date and the path of the day page — decoded from the server's answer; since #162 also the day mode with who decided it; since #228 a source the window does not know leaves the switcher out instead of failing the whole config
import Foundation

/// Which kind of day it is and who said so. `kind` stays the server's word: a kind
/// the window does not know yet is shown as it came, not dropped.
struct PanelDayMode: Equatable, Decodable {
    enum Source: String, Equatable, Decodable {
        case schedule
        case manual
    }

    let kind: String
    let nocode: Bool
    let source: Source

    /// Kinds in the order the switcher lists them.
    static let kinds: [String] = ["work", "dayoff", "vacation", "sick"]

    static func label(of kind: String) -> String {
        switch kind {
        case "work": return "Рабочий"
        case "dayoff": return "Выходной"
        case "vacation": return "Отпуск"
        case "sick": return "Болезнь"
        default: return kind
        }
    }

    /// «по расписанию» and «вручную» are the same day and two different facts.
    var sourceText: String {
        source == .manual ? "вручную" : "по расписанию"
    }
}

struct PanelConfig: Equatable, Decodable {
    struct Task: Equatable, Decodable {
        let id: UUID
        let title: String
        let startsAt: Date
        let endsAt: Date

        enum CodingKeys: String, CodingKey {
            case id, title
            case startsAt = "starts_at"
            case endsAt = "ends_at"
        }
    }

    let currentTask: Task?
    /// Path of the day page in the web, e.g. `/day/2026-10-25`.
    let dayPath: String
    /// The day the server means by today, `yyyy-MM-dd`. The window labels itself
    /// with it and the button opens `dayPath`, both from this one response.
    let date: String
    /// Nil when the server does not send the mode (an older one): the window then has no switcher.
    let dayMode: PanelDayMode?

    private enum CodingKeys: String, CodingKey {
        case currentTask = "current_task"
        case dayPath = "day_path"
        case dayMode = "day_mode"
    }

    private enum DayModeKeys: String, CodingKey {
        case date, kind, nocode, source
    }

    init(currentTask: Task?, dayPath: String, date: String, dayMode: PanelDayMode? = nil) {
        self.currentTask = currentTask
        self.dayPath = dayPath
        self.date = date
        self.dayMode = dayMode
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        currentTask = try container.decodeIfPresent(Task.self, forKey: .currentTask)
        dayPath = try container.decode(String.self, forKey: .dayPath)
        let mode = try container.nestedContainer(keyedBy: DayModeKeys.self, forKey: .dayMode)
        date = try mode.decode(String.self, forKey: .date)
        if let kind = try mode.decodeIfPresent(String.self, forKey: .kind),
           let nocode = try mode.decodeIfPresent(Bool.self, forKey: .nocode),
           // The source stays a String until it is known: a value from a newer server
           // must cost the switcher, not the task, the date and the day link.
           let source = try mode.decodeIfPresent(String.self, forKey: .source).flatMap(PanelDayMode.Source.init(rawValue:)) {
            dayMode = PanelDayMode(kind: kind, nocode: nocode, source: source)
        } else {
            dayMode = nil
        }
    }

    /// «25 октября» for the header; nil when the server sent something that is not a date.
    var dateLabel: String? {
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withFullDate]
        parser.timeZone = Self.utc
        guard let day = parser.date(from: date) else { return nil }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "ru_RU")
        formatter.timeZone = Self.utc
        formatter.dateFormat = "d MMMM"
        return formatter.string(from: day)
    }

    private static let utc = TimeZone(secondsFromGMT: 0)!
}
