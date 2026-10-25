// [review:need-review] PHASE-01/35-ios-category-detail, PHASE-01/208
// summary: Entries history state — load list + categories, category filter; grouping/edit/delete come from the shared EntryMutating surface
import Foundation

@MainActor
final class EntriesViewModel: ObservableObject, EntryMutating {
    @Published private(set) var state: EntryLoadState = .idle
    @Published var entries: [EntryDTO] = []
    @Published private(set) var categories: [CategoryDTO] = []
    /// Category filter for the list; `nil` shows every category.
    @Published var selectedCategoryId: Int?
    /// The entry currently open in the edit form; `nil` when no form is shown.
    /// A failed save leaves it intact so the user's input is never lost.
    @Published var editDraft: EntryEditDraft?
    @Published var saveErrorMessage: String?

    private let apiProvider: () -> EntriesAPI?

    /// Primary init: the provider is re-evaluated on every call, so Settings
    /// changes (server address / API key) take effect without an app restart.
    init(apiProvider: @escaping () -> EntriesAPI?) {
        self.apiProvider = apiProvider
    }

    /// Convenience init with a fixed API (used by unit tests).
    convenience init(api: EntriesAPI) {
        self.init(apiProvider: { api })
    }

    /// Builds the production view model from stored Settings (UserDefaults + Keychain).
    static func live() -> EntriesViewModel {
        EntriesViewModel(apiProvider: { APIClient.live() })
    }

    func mutationAPI() -> EntryMutationAPI? { apiProvider() }

    // MARK: - Derived state

    /// Entries matching the current category filter, preserving load order.
    var filteredEntries: [EntryDTO] {
        guard let categoryID = selectedCategoryId else { return entries }
        return entries.filter { $0.categoryId == categoryID }
    }

    /// The shared history list groups the filtered entries.
    var groupableEntries: [EntryDTO] { filteredEntries }

    /// The category an entry belongs to, if still loaded (drives field labels).
    func category(for entry: EntryDTO) -> CategoryDTO? {
        categories.first { $0.id == entry.categoryId }
    }

    // MARK: - Loading

    /// Loads every category (for names/field labels) and the entry history in one pass.
    func load() async {
        state = .loading
        guard let api = apiProvider() else {
            state = .failure(Self.notConfiguredMessage)
            return
        }
        do {
            async let categoriesTask = api.fetchCategories()
            async let entriesTask = api.fetchEntries(categoryId: nil)
            let (fetchedCategories, fetchedEntries) = try await (categoriesTask, entriesTask)
            categories = fetchedCategories
            entries = fetchedEntries
            state = .loaded
        } catch let error as APIClientError {
            state = .failure(error.userMessage)
        } catch {
            state = .failure("Unexpected error")
        }
    }
}
