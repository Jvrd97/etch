// [review:need-review] PHASE-01/267
// summary: DTOs of the Onboarding screen — the built-in category catalog and its apply answer (GET/POST /categories/templates), the additive-only plan the voice builder drafts (POST /onboarding/draft) and the batch it is applied as (POST /categories/batch); the `op` tag is kept on the way back so the plan is echoed unchanged
import Foundation

/// A built-in category the person can pre-fill. `added`: a category with this name exists already.
struct CategoryTemplateDTO: Codable, Identifiable, Equatable {
    let key: String
    let name: String
    let description: String?
    let color: String?
    let displayMode: String
    let streakMode: String
    let group: String?
    let fields: [FieldCreateDTO]
    let added: Bool

    var id: String { key }
}

struct TemplateApplyRequestDTO: Codable, Equatable {
    let keys: [String]
}

/// `skipped` carries template keys, not names: the catalog the screen showed turns them into names.
struct TemplateApplyResponseDTO: Codable, Equatable {
    let categories: [CategoryDTO]
    let skipped: [String]
}

/// A field the plan proposes. `fieldType` stays a string: the plan is shown, not interpreted.
struct PlanFieldDTO: Codable, Equatable {
    let name: String
    let fieldType: String
    let isRequired: Bool
    let options: String?
    let order: Int
}

struct CreateCategoryOpDTO: Codable, Equatable {
    var op = "create_category"
    var name: String
    let description: String?
    let icon: String?
    let color: String?
    let displayMode: String
    let streakMode: String
    let group: String?
    let fields: [PlanFieldDTO]
    /// Set by the server when `name` is taken already; echoed back as the web does.
    let nameConflict: Bool
}

struct AddFieldOpDTO: Codable, Equatable {
    var op = "add_field"
    let categoryId: Int
    let field: PlanFieldDTO
}

/// One step of the plan: a new category with its fields, or a field added to an existing one.
/// Nothing in the shape deletes, renames or retypes.
enum OnboardingOperationDTO: Codable, Equatable {
    case createCategory(CreateCategoryOpDTO)
    case addField(AddFieldOpDTO)

    private enum TagKey: String, CodingKey { case op }

    init(from decoder: Decoder) throws {
        let tag = try decoder.container(keyedBy: TagKey.self).decode(String.self, forKey: .op)
        switch tag {
        case "create_category": self = .createCategory(try CreateCategoryOpDTO(from: decoder))
        case "add_field": self = .addField(try AddFieldOpDTO(from: decoder))
        default:
            throw DecodingError.dataCorrupted(
                .init(codingPath: decoder.codingPath, debugDescription: "Unknown plan operation \(tag)"))
        }
    }

    func encode(to encoder: Encoder) throws {
        switch self {
        case .createCategory(let op): try op.encode(to: encoder)
        case .addField(let op): try op.encode(to: encoder)
        }
    }
}

struct OnboardingDraftRequestDTO: Codable, Equatable {
    let transcript: String
}

struct OnboardingPlanDTO: Codable, Equatable {
    let operations: [OnboardingOperationDTO]
}

struct CategoryBatchRequestDTO: Codable, Equatable {
    let operations: [OnboardingOperationDTO]
}

/// What the batch wrote: the categories it created and the fields it appended to existing ones.
struct CategoryBatchResponseDTO: Codable, Equatable {
    let categories: [CategoryDTO]
    let fields: [FieldDTO]
}
