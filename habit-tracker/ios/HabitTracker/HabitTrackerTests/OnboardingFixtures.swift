// [review:need-review] PHASE-01/267
// summary: fixtures and a scripted client for the Onboarding tests — a catalog of three templates (one already added), a plan of a clashing category, a free one and an added field; the client records every call and never reaches a model
import Foundation
@testable import HabitTracker

final class MockOnboardingAPI: OnboardingAPI {
    var templatesHandler: () async throws -> [CategoryTemplateDTO] = { OnboardingFixtures.catalog }
    var applyTemplatesHandler: ([String]) async throws -> TemplateApplyResponseDTO = { _ in
        TemplateApplyResponseDTO(categories: [], skipped: [])
    }
    var draftHandler: (String) async throws -> OnboardingPlanDTO = { _ in OnboardingFixtures.plan }
    var applyPlanHandler: ([OnboardingOperationDTO]) async throws -> CategoryBatchResponseDTO = { _ in
        CategoryBatchResponseDTO(categories: [], fields: [])
    }
    var categoriesHandler: () async throws -> [CategoryDTO] = { [] }

    private(set) var appliedTemplateKeys: [[String]] = []
    private(set) var drafts: [String] = []
    private(set) var appliedPlans: [[OnboardingOperationDTO]] = []

    func fetchTemplates() async throws -> [CategoryTemplateDTO] { try await templatesHandler() }

    func applyTemplates(keys: [String]) async throws -> TemplateApplyResponseDTO {
        appliedTemplateKeys.append(keys)
        return try await applyTemplatesHandler(keys)
    }

    func draftPlan(transcript: String) async throws -> OnboardingPlanDTO {
        drafts.append(transcript)
        return try await draftHandler(transcript)
    }

    func applyPlan(_ operations: [OnboardingOperationDTO]) async throws -> CategoryBatchResponseDTO {
        appliedPlans.append(operations)
        return try await applyPlanHandler(operations)
    }

    func fetchCategories() async throws -> [CategoryDTO] { try await categoriesHandler() }
}

enum OnboardingFixtures {
    static func template(_ key: String, _ name: String, added: Bool = false) -> CategoryTemplateDTO {
        CategoryTemplateDTO(
            key: key, name: name, description: nil, color: nil, displayMode: "form", streakMode: "build",
            group: nil, fields: [], added: added)
    }

    static let catalog = [template("sleep", "Сон"), template("water", "Вода", added: true), template("steps", "Шаги")]

    static func category(_ id: Int, _ name: String) -> CategoryDTO {
        CategoryDTO(id: id, name: name, icon: nil, color: nil, displayMode: "form", isActive: true, fields: [])
    }

    static let hours = PlanFieldDTO(name: "Часы", fieldType: "number", isRequired: true, options: nil, order: 0)

    static func create(_ name: String, conflict: Bool = false) -> CreateCategoryOpDTO {
        CreateCategoryOpDTO(
            name: name, description: nil, icon: nil, color: nil, displayMode: "form", streakMode: "build",
            group: nil, fields: [hours], nameConflict: conflict)
    }

    /// 0: a name that clashes, 1: a free one, 2: a field for an existing category.
    static let plan = OnboardingPlanDTO(operations: [
        .createCategory(create("Вода", conflict: true)),
        .createCategory(create("Сон")),
        .addField(AddFieldOpDTO(categoryId: 4, field: hours)),
    ])
}
