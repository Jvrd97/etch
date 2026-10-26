// [review:need-review] PHASE-01/213
// summary: day-summary endpoints — draft a plan from a retelling, apply the checked part under one Idempotency-Key per plan; the category catalogue names the ids of a plan
import Foundation

/// The day-summary flow (`/api/v1/daily-summary`). `APIClient` is the production implementation.
protocol DailySummaryAPI {
    /// Nothing is written: the server only proposes a plan.
    func draftDailySummary(_ request: DailySummaryDraftRequestDTO) async throws -> DailySummaryDraftDTO
    /// One transaction. The key makes a retry after a lost answer the same write, not a second one.
    func applyDailySummary(
        _ request: DailySummaryApplyRequestDTO, idempotencyKey: String
    ) async throws -> DailySummaryApplyResponseDTO
    /// Names for the ids of a plan.
    func fetchCategories() async throws -> [CategoryDTO]
}

extension APIClient: DailySummaryAPI {
    func draftDailySummary(
        _ request: DailySummaryDraftRequestDTO
    ) async throws -> DailySummaryDraftDTO {
        try await sendJSON(path: "/daily-summary/draft", method: "POST", body: request)
    }

    func applyDailySummary(
        _ request: DailySummaryApplyRequestDTO, idempotencyKey: String
    ) async throws -> DailySummaryApplyResponseDTO {
        try await sendJSON(
            path: "/daily-summary/apply", method: "POST", body: request,
            idempotencyKey: idempotencyKey
        )
    }
}
