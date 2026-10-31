// [review:need-review] PHASE-03/304
// summary: wire types of GET /dashboard/summary (#296) for the dashboard screen — the three rings, streaks with their day strips, key health metrics with the server's direction of «better», bests, workout weeks and the ready insight; Codable so the read cache can keep the last answer per period; the health ring reuses HealthScoreDTO of the Health tab
import Foundation

/// The window of the summary: the last 7 days or the last 30, both ending on the server's today.
enum DashboardPeriod: String, Codable, CaseIterable, Equatable {
    case week
    case month
}

/// The three rings. Every block is always an object; `nil` inside is «no data», never a zero.
struct DashboardScoresDTO: Codable, Equatable {
    struct Habits: Codable, Equatable {
        let value: Int?
        let done: Int?
        let total: Int?
    }

    struct Challenges: Codable, Equatable {
        let done: Int?
        let total: Int?
    }

    let health: HealthScoreDTO
    let habits: Habits
    let challenges: Challenges
}

/// A streak of one category and the strip of the window's days, oldest first.
struct DashboardStreakDTO: Codable, Equatable, Identifiable {
    let categoryId: Int
    let name: String
    /// `build` or `avoid`; anything else is read as `build`.
    let kind: String
    let current: Int
    let best: Int
    /// `true` done or clean, `false` missed or relapsed, `nil` no data.
    let days: [Bool?]

    var id: Int { categoryId }
    var isAvoid: Bool { kind == "avoid" }
}

/// A key health metric with data in the window: the average per day and its distance from the personal norm.
struct DashboardHealthMetricDTO: Codable, Equatable, Identifiable {
    let identifier: String
    let label: String
    let value: Int
    let unit: String
    /// `nil` while the personal norm has not formed.
    let baselineDelta: Int?
    /// The server knows which way is better: the phone never guesses it from the name.
    let higherIsBetter: Bool

    var id: String { identifier }
}

/// The best day of the window for a metric; `isRecord` when it beats the last 90 days.
struct DashboardBestDTO: Codable, Equatable, Identifiable {
    let identifier: String
    let label: String
    let value: Int
    let unit: String
    /// `yyyy-MM-dd`.
    let date: String
    let isRecord: Bool

    var id: String { identifier }
}

struct DashboardWorkoutWeekDTO: Codable, Equatable, Identifiable {
    /// `yyyy-MM-dd`, a Monday.
    let weekStart: String
    let count: Int
    let minutes: Int

    var id: String { weekStart }
}

struct DashboardWorkoutsDTO: Codable, Equatable {
    let weeks: [DashboardWorkoutWeekDTO]
    let total: Int?
    let deltaVsPrevious: Int?
}

/// A ready text built from the summary's numbers by a rule, not by a model.
struct DashboardInsightDTO: Codable, Equatable {
    let text: String
    /// The server's wall clock, `2026-10-31T09:00:00+03:00`; read from the string, never moved to the phone's zone.
    let generatedAt: String
}

struct DashboardSummaryDTO: Codable, Equatable {
    let period: DashboardPeriod
    /// `yyyy-MM-dd`.
    let from: String
    let to: String
    /// The server's day: the phone's clock is never asked which day it is.
    let today: String
    let scores: DashboardScoresDTO
    let streaks: [DashboardStreakDTO]
    let health: [DashboardHealthMetricDTO]
    let bests: [DashboardBestDTO]
    let workouts: DashboardWorkoutsDTO
    let insight: DashboardInsightDTO?
}
