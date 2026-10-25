// [review:need-review] PHASE-01/10-ios-dashboard, PHASE-01/208
// summary: Dashboard state — parallel-loads category/entry/journal counts + recent activity, mirrors the web dashboard
import Foundation

@MainActor
final class DashboardViewModel: ObservableObject {
    /// Discriminated load state for the dashboard.
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    /// Aggregated counters and the recent-activity feed shown on the dashboard.
    struct Stats: Equatable {
        var categoriesCount: Int
        var entriesCount: Int
        var journalCount: Int
        var recentEntries: [EntryDTO]

        static let empty = Stats(
            categoriesCount: 0, entriesCount: 0, journalCount: 0, recentEntries: []
        )
    }

    @Published private(set) var state: LoadState = .idle
    @Published private(set) var stats: Stats = .empty

    /// How many entries the recent-activity feed surfaces (parity with the web dashboard).
    static let recentEntriesLimit = 5
    static let notConfiguredMessage = "Set the server address in Settings"

    private let apiProvider: () -> DashboardAPI?

    /// Primary init: the provider is re-evaluated on every load, so Settings
    /// changes (server address / API key) take effect without an app restart.
    init(apiProvider: @escaping () -> DashboardAPI?) {
        self.apiProvider = apiProvider
    }

    /// Convenience init with a fixed API (used by unit tests).
    convenience init(api: DashboardAPI) {
        self.init(apiProvider: { api })
    }

    /// Builds the production view model from stored Settings (UserDefaults + Keychain).
    static func live() -> DashboardViewModel {
        DashboardViewModel(apiProvider: { APIClient.live() })
    }

    /// Loads category/entry/journal counts and the recent-activity feed in one parallel pass.
    func load() async {
        state = .loading
        guard let api = apiProvider() else {
            state = .failure(Self.notConfiguredMessage)
            return
        }
        do {
            async let categoriesTask = api.fetchCategories()
            async let entriesTask = api.fetchEntries(categoryId: nil)
            async let journalTask = api.fetchJournalList()
            let (categories, entries, journal) = try await (
                categoriesTask, entriesTask, journalTask
            )
            stats = Self.aggregate(
                categories: categories, entries: entries, journalTotal: journal.total
            )
            state = .loaded
        } catch let error as APIClientError {
            state = .failure(error.userMessage)
        } catch {
            state = .failure("Unexpected error")
        }
    }

    /// Pure aggregation of the fetched data into dashboard `Stats`.
    /// Recent entries are newest first (date desc, id desc on ties) and capped
    /// at `recentEntriesLimit`.
    static func aggregate(
        categories: [CategoryDTO], entries: [EntryDTO], journalTotal: Int
    ) -> Stats {
        let recent = entries
            .sorted {
                if $0.entryDate != $1.entryDate {
                    return $0.entryDate > $1.entryDate
                }
                return $0.id > $1.id
            }
            .prefix(recentEntriesLimit)
        return Stats(
            categoriesCount: categories.count,
            entriesCount: entries.count,
            journalCount: journalTotal,
            recentEntries: Array(recent)
        )
    }
}
