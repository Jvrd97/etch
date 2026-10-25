// [review:need-review] PHASE-03/159
// summary: the part of GET /agent/config the floating panel draws — the task the day is on, the date and the path of the day page — decoded from the server's answer
import Foundation

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

    private enum CodingKeys: String, CodingKey {
        case currentTask = "current_task"
        case dayPath = "day_path"
        case dayMode = "day_mode"
    }

    private enum DayModeKeys: String, CodingKey {
        case date
    }

    init(currentTask: Task?, dayPath: String, date: String) {
        self.currentTask = currentTask
        self.dayPath = dayPath
        self.date = date
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        currentTask = try container.decodeIfPresent(Task.self, forKey: .currentTask)
        dayPath = try container.decode(String.self, forKey: .dayPath)
        date = try container.nestedContainer(keyedBy: DayModeKeys.self, forKey: .dayMode)
            .decode(String.self, forKey: .date)
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
