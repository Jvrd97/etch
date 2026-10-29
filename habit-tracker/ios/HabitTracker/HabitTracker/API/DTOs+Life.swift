// [review:need-review] PHASE-01/265
// summary: wire types of GET /days?from&to (one row per recorded day: title, verdict, where the verdict came from, tasks done of planned) and GET /day-mode (only the server's current day is read); Codable so the read cache keeps the last answer
import Foundation

/// One recorded day of the timeline. A date the server has no row for is simply absent.
struct LifeDayDTO: Codable, Equatable {
    /// `yyyy-MM-dd`.
    let date: String
    /// Title of the day's plan; empty when there is none.
    let title: String
    /// `won`, `lost`, or `nil` for a day nobody closed.
    let verdict: String?
    /// `computed`, `migrated_prose` or `none`.
    let verdictOrigin: String
    let done: Int
    let total: Int
}

/// `GET /day-mode` without a date: the answer names the day the server is running.
struct LifeServerDayDTO: Codable, Equatable {
    let date: String
}

/// What the Life screen keeps in the read cache: the server's day and the days read against it.
struct LifeSnapshotDTO: Codable, Equatable {
    let today: String
    let days: [LifeDayDTO]
}
