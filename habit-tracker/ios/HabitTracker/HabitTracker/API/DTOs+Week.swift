// [review:need-review] PHASE-03/229, PHASE-03/261, PHASE-03/262
// summary: wire types of GET /week-review[/{iso}] and POST /week-review/{iso}/narrative — the week in one answer (window, totals against the previous week, days, roles, categories, avoid streaks, health) and the AI text; Codable so the read cache can keep the last answer
import Foundation

/// Which days the numbers cover and in which clock they were cut.
struct WeekWindowDTO: Codable, Equatable {
    let isoCode: String
    /// `yyyy-MM-dd`.
    let startsOn: String
    let endsOn: String
    let timezone: String
    let dayStartHour: Int
    /// False while the week runs or has not begun: the figures are partial.
    let isComplete: Bool
    /// Days of the week that are in the figures; 7 for a finished week.
    let countedDays: Int
    let asOf: String?
    let previousIsoCode: String
    let nextIsoCode: String
    /// How many first days of the previous week the comparison covers.
    let comparedDays: Int
    /// Today is already in the figures (its day is closed). Absent in an older server's answer: false.
    let todayCounted: Bool?
}

/// What a stretch of days added up to. `nil` is "nothing to measure", never zero.
struct WeekTotalsDTO: Codable, Equatable {
    let closedDays: Int
    let wonDays: Int
    let lostDays: Int
    let tasksDone: Int
    let tasksTotal: Int
    let planPct: Int?
    let anchorsDone: Int
    let anchorsTotal: Int
    let workMinutes: Int?
    let roleMinutes: Int
    let daysTotal: Int
    let dayStreakEnd: Int?
}

/// This week minus the previous one over the same number of days; the server subtracts.
struct WeekDeltaDTO: Codable, Equatable {
    let wonDays: Int
    let tasksDone: Int
    /// Percentage points.
    let planPct: Int?
    let workMinutes: Int?
    let roleMinutes: Int
}

struct WeekDayStatDTO: Codable, Equatable, Identifiable {
    let date: String
    /// 0 is Monday, 6 is Sunday.
    let weekday: Int
    let counted: Bool
    /// `won`, `lost` or `nil` for a day that is not closed.
    let verdict: String?
    let tasksDone: Int
    let tasksTotal: Int
    let planPct: Int?
    let workMinutes: Int?
    let roleMinutes: Int
    let streakAfter: Int?

    var id: String { date }
}

struct WeekRoleSliceDTO: Codable, Equatable, Identifiable {
    let roleId: Int
    let roleCode: String
    let title: String
    let minutes: Int
    let sharePct: Int
    let targetSharePct: Int?
    let previousMinutes: Int
    let deltaMinutes: Int

    var id: Int { roleId }
}

struct WeekCategorySliceDTO: Codable, Equatable, Identifiable {
    let categoryId: Int
    let name: String
    let minutes: Int
    let previousMinutes: Int
    let deltaMinutes: Int
    let entryDays: Int
    let previousEntryDays: Int

    var id: Int { categoryId }
}

struct WeekHabitStreakDTO: Codable, Equatable, Identifiable {
    let categoryId: Int
    let name: String
    let currentStreak: Int
    let relapses: Int

    var id: Int { categoryId }
}

/// One health figure of the week. `available == false` means the metric is not in the
/// server's catalog, so there can be no data at all (sleep today).
struct WeekHealthMetricDTO: Codable, Equatable, Identifiable {
    /// `sleep`, `steps` or `workouts`.
    let key: String
    let name: String
    /// `count`, `min` or `nil` when there is no metric.
    let unit: String?
    let available: Bool
    let total: Double?
    let avgPerDay: Double?
    let daysWithData: Int
    let previousAvgPerDay: Double?
    let deltaAvgPerDay: Double?
    /// Monday to Sunday; `nil` is "no data that day".
    let daily: [Double?]
    /// Days of the previous week that had data; absent in an older server's answer.
    let previousDaysWithData: Int?

    var id: String { key }
}

/// The whole week in one answer.
struct WeekReviewDTO: Codable, Equatable {
    let window: WeekWindowDTO
    let totals: WeekTotalsDTO
    let previousTotals: WeekTotalsDTO
    let delta: WeekDeltaDTO
    let debtMinutes: Int
    /// `nil` while the week runs: the verdict is not decided.
    let isWon: Bool?
    let days: [WeekDayStatDTO]
    let bestDay: String?
    let worstDay: String?
    let roles: [WeekRoleSliceDTO]
    let categories: [WeekCategorySliceDTO]
    let habitStreaks: [WeekHabitStreakDTO]
    let health: [WeekHealthMetricDTO]
    /// The verdict in the server's own words, the same on the web; absent in an older server's answer.
    let verdictLine: String?
}

/// The AI text of a week. The server does not store it.
struct WeekNarrativeDTO: Decodable, Equatable {
    let isoCode: String
    let text: String
    let model: String
}
