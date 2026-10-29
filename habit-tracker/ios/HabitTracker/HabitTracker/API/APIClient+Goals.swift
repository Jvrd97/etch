// [review:need-review] PHASE-01/216
// summary: GoalsAPI — GET /goals (levels, milestones, the current quarter) and PATCH /goals/milestones/{code} that moves one milestone; APIClient implements it on the shared request helpers
import Foundation

/// API surface of the Goals screen; `APIClient` is the production implementation.
protocol GoalsAPI {
    func fetchGoals() async throws -> GoalsBoardDTO
    /// `done` dates the milestone with the server's day; any other status clears the date.
    func patchMilestone(code: String, status: MilestoneStatus) async throws -> MilestoneDTO
}

extension APIClient: GoalsAPI {
    func fetchGoals() async throws -> GoalsBoardDTO {
        try await getJSON(path: "/goals", query: [])
    }

    func patchMilestone(code: String, status: MilestoneStatus) async throws -> MilestoneDTO {
        try await sendJSON(path: "/goals/milestones/\(code)", method: "PATCH", body: MilestonePatchDTO(status: status))
    }
}
