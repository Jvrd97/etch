// [review:need-review] PHASE-01/07-ios-categories-crud, PHASE-01/208
// summary: Categories screen state — list load, draft validation (empty name, select w/o options), create/update/delete
import Foundation

/// A field being edited in the category form. `options` is the raw list the user
/// types for a `select` field; it is serialized to the backend's JSON-array string
/// only when a payload is built, so the editor never has to deal with JSON.
struct FieldDraft: Identifiable, Equatable {
    let id: UUID
    var name: String
    var fieldType: FieldTypeDTO
    var isRequired: Bool
    var options: [String]

    init(
        id: UUID = UUID(),
        name: String = "",
        fieldType: FieldTypeDTO = .number,
        isRequired: Bool = false,
        options: [String] = []
    ) {
        self.id = id
        self.name = name
        self.fieldType = fieldType
        self.isRequired = isRequired
        self.options = options
    }
}

/// A category being created or edited in the form.
struct CategoryDraft: Equatable {
    var name: String
    var color: String?
    var icon: String?
    var displayMode: String
    var fields: [FieldDraft]

    init(
        name: String = "",
        color: String? = nil,
        icon: String? = nil,
        displayMode: String = "form",
        fields: [FieldDraft] = []
    ) {
        self.name = name
        self.color = color
        self.icon = icon
        self.displayMode = displayMode
        self.fields = fields
    }
}

/// A single reason a `CategoryDraft` cannot be saved. Indices point back at the
/// offending field so the form can highlight the exact row.
enum CategoryValidationError: Equatable {
    case emptyName
    case fieldEmptyName(index: Int)
    case selectWithoutOptions(index: Int)

    /// User-facing message; the form surfaces the first error.
    var message: String {
        switch self {
        case .emptyName:
            return "Category name can't be empty"
        case .fieldEmptyName(let index):
            return "Field \(index + 1) needs a name"
        case .selectWithoutOptions(let index):
            return "Field \(index + 1) is a select and needs at least one option"
        }
    }
}

@MainActor
final class CategoriesViewModel: ObservableObject {
    /// Discriminated load state for the category list.
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    @Published private(set) var state: LoadState = .idle
    @Published private(set) var categories: [CategoryDTO] = []
    @Published var saveErrorMessage: String?

    static let notConfiguredMessage = "Set the server address in Settings"
    static let selectFieldType = "select"

    private let apiProvider: () -> CategoriesAPI?

    /// Primary init: the provider is re-evaluated on every call, so Settings
    /// changes (server address / API key) take effect without an app restart.
    init(apiProvider: @escaping () -> CategoriesAPI?) {
        self.apiProvider = apiProvider
    }

    /// Convenience init with a fixed API (used by unit tests).
    convenience init(api: CategoriesAPI) {
        self.init(apiProvider: { api })
    }

    /// Builds the production view model from stored Settings (UserDefaults + Keychain).
    static func live() -> CategoriesViewModel {
        CategoriesViewModel(apiProvider: { APIClient.live() })
    }

    /// Loads every category (active and archived) so the management screen shows all.
    func load() async {
        state = .loading
        guard let api = apiProvider() else {
            state = .failure(Self.notConfiguredMessage)
            return
        }
        do {
            categories = try await api.fetchCategories()
            state = .loaded
        } catch let error as APIClientError {
            state = .failure(error.userMessage)
        } catch {
            state = .failure("Unexpected error")
        }
    }

    /// Pure validation of a draft: returns every problem, in field order.
    /// Empty (after trimming) category names and `select` fields with no non-empty
    /// option are rejected — the two rules the ticket calls out explicitly.
    func validate(_ draft: CategoryDraft) -> [CategoryValidationError] {
        var errors: [CategoryValidationError] = []
        if Self.isBlank(draft.name) {
            errors.append(.emptyName)
        }
        for (index, field) in draft.fields.enumerated() {
            if Self.isBlank(field.name) {
                errors.append(.fieldEmptyName(index: index))
            }
            if field.fieldType == .select, Self.cleanedOptions(field.options).isEmpty {
                errors.append(.selectWithoutOptions(index: index))
            }
        }
        return errors
    }

    /// Validates then creates the category (with its fields) in one request.
    /// On success the new category is appended to the local list so the screen
    /// updates without a reload. Returns true on success.
    func createCategory(_ draft: CategoryDraft) async -> Bool {
        guard let payload = validatedPayload(draft) else { return false }
        guard let api = requireAPI() else { return false }
        do {
            let created = try await api.createCategory(payload)
            categories.append(created)
            return true
        } catch let error as APIClientError {
            saveErrorMessage = error.userMessage
            return false
        } catch {
            saveErrorMessage = "Unexpected error"
            return false
        }
    }

    /// Patches a category's basic properties (name, color, icon, display mode).
    /// Field mutation is out of scope for editing; use `addField` to append.
    func updateCategory(id: Int, _ draft: CategoryDraft) async -> Bool {
        saveErrorMessage = nil
        if Self.isBlank(draft.name) {
            saveErrorMessage = CategoryValidationError.emptyName.message
            return false
        }
        guard let api = requireAPI() else { return false }
        let payload = CategoryUpdateDTO(
            name: Self.trimmed(draft.name),
            color: draft.color,
            icon: draft.icon,
            displayMode: draft.displayMode
        )
        do {
            let updated = try await api.updateCategory(id: id, payload)
            if let index = categories.firstIndex(where: { $0.id == id }) {
                categories[index] = updated
            }
            return true
        } catch let error as APIClientError {
            saveErrorMessage = error.userMessage
            return false
        } catch {
            saveErrorMessage = "Unexpected error"
            return false
        }
    }

    /// Deletes a category and drops it from the local list. Returns true on success.
    func deleteCategory(id: Int) async -> Bool {
        saveErrorMessage = nil
        guard let api = requireAPI() else { return false }
        do {
            try await api.deleteCategory(id: id)
            categories.removeAll { $0.id == id }
            return true
        } catch let error as APIClientError {
            saveErrorMessage = error.userMessage
            return false
        } catch {
            saveErrorMessage = "Unexpected error"
            return false
        }
    }

    // MARK: - Private

    /// Clears the error, runs validation, and returns the wire payload — or nil
    /// (with `saveErrorMessage` set to the first problem) when the draft is invalid.
    private func validatedPayload(_ draft: CategoryDraft) -> CategoryCreateDTO? {
        saveErrorMessage = nil
        let errors = validate(draft)
        guard errors.isEmpty else {
            saveErrorMessage = errors.first?.message
            return nil
        }
        let fields = draft.fields.enumerated().map { index, field in
            makeFieldPayload(field, order: index)
        }
        return CategoryCreateDTO(
            name: Self.trimmed(draft.name),
            color: draft.color,
            icon: draft.icon,
            displayMode: draft.displayMode,
            fields: fields
        )
    }

    private func makeFieldPayload(_ field: FieldDraft, order: Int) -> FieldCreateDTO {
        FieldCreateDTO(
            name: Self.trimmed(field.name),
            fieldType: field.fieldType,
            isRequired: field.isRequired,
            defaultValue: nil,
            options: Self.encodeOptions(field),
            order: order
        )
    }

    private func requireAPI() -> CategoriesAPI? {
        guard let api = apiProvider() else {
            saveErrorMessage = Self.notConfiguredMessage
            return nil
        }
        return api
    }

    /// Encodes a select field's options as the backend's JSON-array string; nil for
    /// any other type, so non-select fields never carry stray options.
    private static func encodeOptions(_ field: FieldDraft) -> String? {
        guard field.fieldType == .select else { return nil }
        let cleaned = cleanedOptions(field.options)
        guard let data = try? JSONEncoder().encode(cleaned) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func cleanedOptions(_ options: [String]) -> [String] {
        options.map(trimmed).filter { !$0.isEmpty }
    }

    private static func trimmed(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func isBlank(_ value: String) -> Bool {
        trimmed(value).isEmpty
    }
}
