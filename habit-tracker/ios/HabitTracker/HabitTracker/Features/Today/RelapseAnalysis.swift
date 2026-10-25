// [review:need-review] PHASE-01/210
// summary: Swift port of the relapse analysis of an avoid category (frontend/lib/relapse-analysis.ts, #207) — trailing week and month counts, average gap, Monday-first weekday split, trend against the month before, day or week buckets for the chart, and the Russian labels
import Foundation

/// The span the history chart draws.
enum RelapsePeriod: CaseIterable, Identifiable {
    case days30
    case days90
    case days365
    case all

    var id: Self { self }

    var title: String {
        switch self {
        case .days30: return "30 дней"
        case .days90: return "90 дней"
        case .days365: return "Год"
        case .all: return "Всё время"
        }
    }

    /// Trailing length in days, or nil for the whole history.
    var days: Int? {
        switch self {
        case .days30: return 30
        case .days90: return 90
        case .days365: return 365
        case .all: return nil
        }
    }
}

/// How this month compares with the one before it. `notEnoughData` until the history reaches back
/// over both months: a month that was not tracked is not a clean month.
enum RelapseTrend: Equatable {
    case notEnoughData
    case fewer(current: Int, previous: Int)
    case more(current: Int, previous: Int)
    case same(current: Int, previous: Int)
}

struct RelapseSummary: Equatable {
    /// Relapse days in the last `RelapseAnalysis.weekDays` days, today included.
    let lastWeek: Int
    /// Relapse days in the last `RelapseAnalysis.monthDays` days, today included.
    let lastMonth: Int
    /// Mean number of days between two consecutive relapse days, nil below two.
    let averageGapDays: Double?
    /// Relapse days per weekday over the whole history, Monday first.
    let weekdays: [Int]
    let trend: RelapseTrend
}

/// One bar of the history chart: a day or a week and how many relapse days it held.
struct RelapseBucket: Equatable, Identifiable {
    /// First day of the bucket, `YYYY-MM-DD`.
    let start: String
    /// Last day of the bucket; equal to `start` for a day bucket.
    let end: String
    let relapseDays: Int

    var id: String { start }
}

struct RelapseTimeline: Equatable {
    enum Granularity: Equatable {
        case day
        case week
    }

    let granularity: Granularity
    let buckets: [RelapseBucket]
}

/// Pure arithmetic over `YYYY-MM-DD` dates. What counts as a relapse is the server's call
/// (`GET /categories/{id}/relapses`); nothing here re-derives it. Dates become day numbers
/// of the proleptic Gregorian calendar, so two dates are exactly as many days apart as they
/// say and a daylight-saving change cannot eat an hour of the difference.
enum RelapseAnalysis {
    static let weekDays = 7
    static let monthDays = 30
    /// Up to this many days the chart draws one bar per day, past it one per week.
    static let dailyBucketLimit = 90
    static let weekdayLabels = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    private static let daysPerWeek = 7
    /// 1970-01-01 was a Thursday; Monday is index 0.
    private static let epochWeekdayIndex = 3
    private static let monthLabels = [
        "янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек",
    ]

    // MARK: Day numbers

    /// Days since 1970-01-01 of a `YYYY-MM-DD` string (civil-from-days, H. Hinnant).
    static func dayNumber(of iso: String) -> Int {
        let parts = iso.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return 0 }
        let year = parts[1] <= 2 ? parts[0] - 1 : parts[0]
        let era = (year >= 0 ? year : year - 399) / 400
        let yearOfEra = year - era * 400
        let monthShifted = parts[1] > 2 ? parts[1] - 3 : parts[1] + 9
        let dayOfYear = (153 * monthShifted + 2) / 5 + parts[2] - 1
        let dayOfEra = yearOfEra * 365 + yearOfEra / 4 - yearOfEra / 100 + dayOfYear
        return era * 146_097 + dayOfEra - 719_468
    }

    static func isoDate(of dayNumber: Int) -> String {
        let shifted = dayNumber + 719_468
        let era = (shifted >= 0 ? shifted : shifted - 146_096) / 146_097
        let dayOfEra = shifted - era * 146_097
        let yearOfEra = (dayOfEra - dayOfEra / 1_460 + dayOfEra / 36_524 - dayOfEra / 146_096) / 365
        let dayOfYear = dayOfEra - (365 * yearOfEra + yearOfEra / 4 - yearOfEra / 100)
        let monthShifted = (5 * dayOfYear + 2) / 153
        let day = dayOfYear - (153 * monthShifted + 2) / 5 + 1
        let month = monthShifted < 10 ? monthShifted + 3 : monthShifted - 9
        let year = yearOfEra + era * 400 + (month <= 2 ? 1 : 0)
        return String(format: "%04d-%02d-%02d", year, month, day)
    }

    /// 0 for Monday … 6 for Sunday.
    private static func weekdayIndex(of dayNumber: Int) -> Int {
        (((dayNumber + epochWeekdayIndex) % daysPerWeek) + daysPerWeek) % daysPerWeek
    }

    private static func uniqueDays(_ relapseDates: [String]) -> [Int] {
        Array(Set(relapseDates.map(dayNumber(of:)))).sorted()
    }

    private static func count(in days: [Int], from: Int, to: Int) -> Int {
        days.filter { $0 >= from && $0 <= to }.count
    }

    // MARK: Analysis

    static func summarize(
        relapseDates: [String], trackedSince: String?, today: String
    ) -> RelapseSummary {
        let days = uniqueDays(relapseDates)
        let todayNumber = dayNumber(of: today)

        let gaps = zip(days.dropFirst(), days).map { $0 - $1 }
        let averageGap = gaps.isEmpty ? nil : Double(gaps.reduce(0, +)) / Double(gaps.count)

        var weekdays = Array(repeating: 0, count: daysPerWeek)
        for day in days {
            weekdays[weekdayIndex(of: day)] += 1
        }

        let monthStart = todayNumber - monthDays + 1
        let previousStart = monthStart - monthDays
        let lastMonth = count(in: days, from: monthStart, to: todayNumber)

        var trend = RelapseTrend.notEnoughData
        if let trackedSince, dayNumber(of: trackedSince) <= previousStart {
            let previous = count(in: days, from: previousStart, to: monthStart - 1)
            if lastMonth < previous {
                trend = .fewer(current: lastMonth, previous: previous)
            } else if lastMonth > previous {
                trend = .more(current: lastMonth, previous: previous)
            } else {
                trend = .same(current: lastMonth, previous: previous)
            }
        }

        return RelapseSummary(
            lastWeek: count(in: days, from: todayNumber - weekDays + 1, to: todayNumber),
            lastMonth: lastMonth,
            averageGapDays: averageGap,
            weekdays: weekdays,
            trend: trend
        )
    }

    /// The bars of the history chart for `period`, oldest first, ending today. `all` starts at the
    /// first tracked day (or the first relapse, if it is earlier). Weeks start on Monday, so a bar
    /// is the same calendar week whichever period is chosen; the first may begin before the period
    /// and the last may end after today, but only days of the period are counted.
    static func timeline(
        relapseDates: [String], trackedSince: String?, today: String, period: RelapsePeriod
    ) -> RelapseTimeline {
        let days = uniqueDays(relapseDates)
        let end = dayNumber(of: today)
        let start: Int
        if let length = period.days {
            start = end - length + 1
        } else {
            let candidates = [end] + (trackedSince.map { [dayNumber(of: $0)] } ?? []) + days.prefix(1)
            start = candidates.min() ?? end
        }

        if end - start + 1 <= dailyBucketLimit {
            let buckets = (start...end).map { day in
                RelapseBucket(
                    start: isoDate(of: day), end: isoDate(of: day),
                    relapseDays: count(in: days, from: day, to: day)
                )
            }
            return RelapseTimeline(granularity: .day, buckets: buckets)
        }

        let buckets = stride(
            from: start - weekdayIndex(of: start), through: end, by: daysPerWeek
        ).map { week in
            let weekEnd = week + daysPerWeek - 1
            return RelapseBucket(
                start: isoDate(of: week), end: isoDate(of: weekEnd),
                relapseDays: count(in: days, from: max(week, start), to: min(weekEnd, end))
            )
        }
        return RelapseTimeline(granularity: .week, buckets: buckets)
    }

    // MARK: Labels

    /// «25 окт 2026» — the same on every machine, unlike locale-dependent formatters.
    static func formatDay(_ iso: String) -> String {
        let parts = iso.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3, (1...12).contains(parts[1]) else { return iso }
        return "\(parts[2]) \(monthLabels[parts[1] - 1]) \(parts[0])"
    }

    /// «Вт» — the weekday of a `YYYY-MM-DD` date.
    static func formatWeekday(_ iso: String) -> String {
        weekdayLabels[weekdayIndex(of: dayNumber(of: iso))]
    }

    /// «1 день», «3 дня», «12 дней».
    static func formatDayCount(_ days: Int) -> String {
        "\(days) \(plural(days, one: "день", few: "дня", many: "дней"))"
    }

    /// An average gap: whole days as a count, a fraction with a comma and «дня».
    static func formatGap(_ days: Double) -> String {
        if days == days.rounded() {
            return formatDayCount(Int(days))
        }
        return String(format: "%.1f", days).replacingOccurrences(of: ".", with: ",") + " дня"
    }

    static func plural(_ count: Int, one: String, few: String, many: String) -> String {
        let mod100 = abs(count) % 100
        let mod10 = mod100 % 10
        if (11...14).contains(mod100) { return many }
        if mod10 == 1 { return one }
        if (2...4).contains(mod10) { return few }
        return many
    }
}
