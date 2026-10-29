// [review:need-review] PHASE-01/265
// summary: pure timeline rules ported from lib/life.ts — dates as `yyyy-MM-dd` on a fixed UTC ISO calendar (no device time zone in the arithmetic), the five square states, the weeks-lived counter with the same 52.1775 arithmetic as life.html, ISO week codes, month grids, and the aggregate state of a week square
import Foundation

/// What a square says about a day; the same five states as the web legend.
enum LifeStatus: String, CaseIterable, Equatable {
    case won, lost, open, empty, future

    var label: String {
        switch self {
        case .won: return "день выигран"
        case .lost: return "день проигран"
        case .open: return "день не закрыт"
        case .empty: return "записи нет"
        case .future: return "ещё не наступил"
        }
    }
}

/// The counter above the grid.
struct LifeCounter: Equatable {
    let years: Int
    let weeksLived: Int
    let weeksTotal: Int
    let weeksLeft: Int
    /// 0...100.
    let percent: Double
}

/// The birth date and the frame in years; kept on the device, as the web keeps it in localStorage.
struct LifeFrame: Codable, Equatable {
    var birth: String
    var targetYears: Int

    static let defaultBirth = "2000-05-11"
    static let defaultTargetYears = 97
    static let standard = LifeFrame(birth: defaultBirth, targetYears: defaultTargetYears)
    static let yearsRange = 1...120
}

enum LifeCalendar {
    static let weeksPerRow = 53
    static let daysInWeek = 7
    /// Mean year in weeks: turns a frame in years into weeks, exactly as life.html did.
    static let weeksPerYear = 52.1775
    /// How far back the timeline asks for days; older squares are drawn from the calendar alone.
    static let historyYears = 3
    static let weekdayShort = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    static let monthNames = [
        "январь", "февраль", "март", "апрель", "май", "июнь",
        "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
    ]

    private static let calendar: Calendar = {
        var calendar = Calendar(identifier: .iso8601)
        calendar.timeZone = TimeZone(identifier: "UTC") ?? .gmt
        calendar.locale = Locale(identifier: "ru_RU")
        return calendar
    }()

    // MARK: Dates

    /// A strict `yyyy-MM-dd`; `nil` for anything else, including 2026-02-30.
    static func parse(_ iso: String) -> Date? {
        let parts = iso.split(separator: "-", omittingEmptySubsequences: false)
        guard parts.count == 3, parts[0].count == 4, parts[1].count == 2, parts[2].count == 2,
              let year = Int(parts[0]), let month = Int(parts[1]), let day = Int(parts[2]),
              let date = calendar.date(from: DateComponents(year: year, month: month, day: day)),
              calendar.dateComponents([.year, .month, .day], from: date) == DateComponents(year: year, month: month, day: day)
        else { return nil }
        return date
    }

    static func iso(_ date: Date) -> String {
        let c = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    static func date(year: Int, month: Int, day: Int = 1) -> Date {
        calendar.date(from: DateComponents(year: year, month: month, day: day)) ?? Date(timeIntervalSince1970: 0)
    }

    static func addDays(_ date: Date, _ days: Int) -> Date {
        calendar.date(byAdding: .day, value: days, to: date) ?? date
    }

    static func addMonths(_ date: Date, _ months: Int) -> Date {
        calendar.date(byAdding: .month, value: months, to: date) ?? date
    }

    static func year(_ date: Date) -> Int { calendar.component(.year, from: date) }
    static func month(_ date: Date) -> Int { calendar.component(.month, from: date) }
    static func dayOfMonth(_ date: Date) -> Int { calendar.component(.day, from: date) }

    /// The Monday of the week `date` is in.
    static func startOfWeek(_ date: Date) -> Date {
        calendar.dateInterval(of: .weekOfYear, for: date)?.start ?? date
    }

    /// `2026-W35`, the key the API uses. The year is the one owning the week's Thursday.
    static func isoWeekCode(_ date: Date) -> String {
        let c = calendar.dateComponents([.yearForWeekOfYear, .weekOfYear], from: date)
        return String(format: "%04d-W%02d", c.yearForWeekOfYear ?? 0, c.weekOfYear ?? 0)
    }

    /// Every date of the month `date` falls in.
    static func monthDates(_ date: Date) -> [Date] {
        let first = self.date(year: year(date), month: month(date))
        let count = calendar.range(of: .day, in: .month, for: first)?.count ?? 0
        return (0..<count).map { addDays(first, $0) }
    }

    static func monthName(_ month: Int) -> String {
        monthNames.indices.contains(month - 1) ? monthNames[month - 1] : String(month)
    }

    // MARK: Statuses

    /// A date with no row is `future` ahead of today and `empty` behind it.
    static func dayStatus(_ day: LifeDayDTO?, date: String, today: String) -> LifeStatus {
        if let day {
            switch day.verdict {
            case "won": return .won
            case "lost": return .lost
            default: return .open
            }
        }
        return date > today ? .future : .empty
    }

    /// One square cannot say seven things: the week is won when any day was, lost when any was and none won.
    static func weekStatus(monday: Date, days: [String: LifeDayDTO], today: String) -> LifeStatus {
        var won = 0, lost = 0, open = 0
        for offset in 0..<daysInWeek {
            let date = iso(addDays(monday, offset))
            switch dayStatus(days[date], date: date, today: today) {
            case .won: won += 1
            case .lost: lost += 1
            case .open: open += 1
            case .empty, .future: break
            }
        }
        if won > 0 { return .won }
        if lost > 0 { return .lost }
        if open > 0 { return .open }
        return iso(monday) > today ? .future : .empty
    }

    /// The number of won and lost days of a week, for the cell's spoken label.
    static func weekTally(monday: Date, days: [String: LifeDayDTO]) -> (won: Int, lost: Int) {
        var won = 0, lost = 0
        for offset in 0..<daysInWeek {
            switch days[iso(addDays(monday, offset))]?.verdict {
            case "won": won += 1
            case "lost": lost += 1
            default: break
            }
        }
        return (won, lost)
    }

    // MARK: Counter

    /// The arithmetic of life.html: whole weeks since birth against `targetYears × 52.1775` rounded.
    static func counter(frame: LifeFrame, today: Date) -> LifeCounter {
        let born = parse(frame.birth) ?? parse(LifeFrame.defaultBirth) ?? today
        let livedDays = Int((today.timeIntervalSince(born) / 86_400).rounded(.down))
        let weeksLived = Int((Double(livedDays) / Double(daysInWeek)).rounded(.down))
        let weeksTotal = Int((Double(frame.targetYears) * weeksPerYear).rounded())
        let years = calendar.dateComponents([.year], from: born, to: today).year ?? 0
        let percent = weeksTotal > 0 ? min(100, Double(weeksLived) / Double(weeksTotal) * 100) : 0
        return LifeCounter(
            years: years, weeksLived: weeksLived, weeksTotal: weeksTotal,
            weeksLeft: max(0, weeksTotal - weeksLived), percent: percent
        )
    }

    // MARK: Ranges

    /// The window of days the screen reads: `historyYears` back from January 1st to the end of this year.
    static func historyRange(today: Date) -> (from: String, to: String) {
        let year = year(today)
        return ("\(String(format: "%04d", year - historyYears))-01-01", "\(String(format: "%04d", year))-12-31")
    }

    static func verdictOriginLabel(_ origin: String) -> String {
        switch origin {
        case "computed": return "вычислен"
        case "migrated_prose": return "из записи"
        default: return ""
        }
    }
}
