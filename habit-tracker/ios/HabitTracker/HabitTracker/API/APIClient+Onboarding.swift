// [review:need-review] PHASE-01/267
// summary: OnboardingAPI — the same calls the mobile web onboarding makes: GET /categories/templates, POST /categories/templates/apply, POST /onboarding/draft (the model builds the plan), POST /categories/batch (the ticked part of the plan, one transaction); GET /categories only for the first-launch check; APIClient implements it on the shared request helpers
import Foundation

/// API surface of the Onboarding screen; `APIClient` is the production implementation.
protocol OnboardingAPI {
    func fetchTemplates() async throws -> [CategoryTemplateDTO]
    func applyTemplates(keys: [String]) async throws -> TemplateApplyResponseDTO
    func draftPlan(transcript: String) async throws -> OnboardingPlanDTO
    func applyPlan(_ operations: [OnboardingOperationDTO]) async throws -> CategoryBatchResponseDTO
    func fetchCategories() async throws -> [CategoryDTO]
}

extension APIClient: OnboardingAPI {
    func fetchTemplates() async throws -> [CategoryTemplateDTO] {
        try await getJSON(path: "/categories/templates", query: [])
    }

    func applyTemplates(keys: [String]) async throws -> TemplateApplyResponseDTO {
        try await sendJSON(path: "/categories/templates/apply", method: "POST", body: TemplateApplyRequestDTO(keys: keys))
    }

    func draftPlan(transcript: String) async throws -> OnboardingPlanDTO {
        try await sendJSON(path: "/onboarding/draft", method: "POST", body: OnboardingDraftRequestDTO(transcript: transcript))
    }

    func applyPlan(_ operations: [OnboardingOperationDTO]) async throws -> CategoryBatchResponseDTO {
        try await sendJSON(path: "/categories/batch", method: "POST", body: CategoryBatchRequestDTO(operations: operations))
    }
}
