// [review:need-review] PHASE-01/216
// summary: wire types of the goal board — levels with their «⚠ подтверди» lines, milestones with «Открывается чем» as codes, the quarter and its goals as GET /goals answers them, and the body of PATCH /goals/milestones/{code}
import Foundation

/// One `## Уровень N` block of `goal.md`.
struct GoalLevelDTO: Codable, Equatable, Identifiable {
    let level: Int
    let title: String
    let bodyMd: String
    /// The `⚠ подтверди` lines: what the author guessed rather than confirmed.
    let openQuestions: [String]

    var id: Int { level }
}

/// The four states a milestone can be in, as the database spells them.
enum MilestoneStatus: String, Codable, Equatable, CaseIterable {
    case open
    case inProgress = "in-progress"
    case done
    case dropped
}

struct MilestoneDTO: Codable, Equatable, Identifiable {
    let code: String
    let title: String
    let doneCriterion: String?
    let whenText: String?
    let ord: Int
    let status: MilestoneStatus
    /// `YYYY-MM-DD`, filled the server's day the milestone was closed; nil while it is not.
    let doneOn: String?
    /// Codes this milestone waits on — `["M8", "M9"]` for M10.
    let dependsOn: [String]

    var id: String { code }
}

struct QuarterGoalDTO: Codable, Equatable, Identifiable {
    let id: Int
    let quarter: String
    let ord: Int
    let textMd: String
    let milestoneCode: String?
    let status: String
}

/// The whole board, as one request answers it.
struct GoalsBoardDTO: Codable, Equatable {
    let levels: [GoalLevelDTO]
    let milestones: [MilestoneDTO]
    /// The quarter the server's day boundary says is running — `2026-Q3`.
    let quarter: String
    let goals: [QuarterGoalDTO]
}

struct MilestonePatchDTO: Encodable, Equatable {
    let status: MilestoneStatus
}
