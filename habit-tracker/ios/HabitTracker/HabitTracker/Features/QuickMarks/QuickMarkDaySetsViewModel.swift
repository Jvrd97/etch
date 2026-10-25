// [review:need-review] PHASE-01/210
// summary: the sets of one category's day as the journal keeps them — one row per tap in the order of the presses, a taken-back set kept and marked, undo handed to the screen that owns the totals, its refusal shown in the list
import Foundation

@MainActor
final class QuickMarkDaySetsViewModel: ObservableObject {
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    @Published private(set) var state: LoadState = .idle
    @Published private(set) var events: [QuickMarkDayEventDTO] = []
    /// The server's sentence when it refused an undo; shown in the list, not under it.
    @Published private(set) var refusal: String?
    @Published private(set) var undoingEventID: Int?

    private let categoryId: Int
    private let apiProvider: () -> QuickMarksAPI?
    private let undoHandler: (Int) async -> String?

    /// `undo` takes one tap back and resolves with the server's refusal, or nil once it is gone:
    /// the screen owns the buttons' totals, so it owns the call.
    init(
        categoryId: Int,
        apiProvider: @escaping () -> QuickMarksAPI?,
        undo: @escaping (Int) async -> String?
    ) {
        self.categoryId = categoryId
        self.apiProvider = apiProvider
        self.undoHandler = undo
    }

    func load() async {
        guard let api = apiProvider() else {
            state = .failure(TodayViewModel.notConfiguredMessage)
            return
        }
        if events.isEmpty { state = .loading }
        do {
            events = try await api.fetchQuickMarkDayEvents(categoryId: categoryId)
            state = .loaded
        } catch let error as APIClientError {
            state = .failure(error.userMessage)
        } catch {
            state = .failure("Unexpected error")
        }
    }

    func undo(eventID: Int) async {
        undoingEventID = eventID
        refusal = nil
        refusal = await undoHandler(eventID)
        // Read again after a refusal as well: a 409 means the journal is not what the list was
        // drawn from, and the fresh rows are the explanation.
        await load()
        undoingEventID = nil
    }
}
