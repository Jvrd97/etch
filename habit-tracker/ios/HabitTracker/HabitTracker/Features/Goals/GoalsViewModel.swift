// [review:need-review] PHASE-01/216
// summary: state of the Goals screen, the native twin of GoalsBoard.tsx — the board read through the read cache, a milestone toggled between closed and open by one PATCH that re-reads the whole board (closing M9 changes how M10 reads), reads numbered so an older answer never overwrites a newer one, and the words the board shows
import Foundation

/// Words and small rules of the goal board, the same as the web's `GoalsBoard.tsx`.
enum GoalsFormat {
    static let emptyText = "Целей пока нет: импортируйте goal.md — уровни, милстоны и квартал живут в нём."
    static let notConfiguredMessage = "Set the server address in Settings"
    static let unblockedText = "ничем не заблокирован"
    /// Beside a dependency that is not closed yet.
    static let waitingLabel = "ждёт"
    /// Beside a dependency that is already closed.
    static let openedLabel = "открыт"

    /// What each status is called on screen; the codes stay in the database.
    static func statusLabel(_ status: MilestoneStatus) -> String {
        switch status {
        case .open: return "открыт"
        case .inProgress: return "в работе"
        case .done: return "закрыт"
        case .dropped: return "снят"
        }
    }

    /// `закрыт · 2026-08-30` for a closed milestone, the bare status otherwise.
    static func statusLine(_ milestone: MilestoneDTO) -> String {
        guard let doneOn = milestone.doneOn else { return statusLabel(milestone.status) }
        return "\(statusLabel(milestone.status)) · \(doneOn)"
    }

    /// The button is named by what it does, not by where the milestone is now.
    static func actionTitle(for status: MilestoneStatus) -> String {
        status == .done ? "Открыть" : "Закрыть"
    }

    /// A tap closes a milestone or opens a closed one. `in-progress` and `dropped` are not set by a
    /// tap here, as on the web: `PATCH /goals/milestones/{code}` takes them from elsewhere.
    static func toggled(_ status: MilestoneStatus) -> MilestoneStatus {
        status == .done ? .open : .done
    }

    /// `**Небольшой дом**` as the words a reader sees. Bold is the only markup the board's fields
    /// carry, so this strips it rather than rendering markdown.
    static func plain(_ text: String) -> String {
        text.replacingOccurrences(of: #"\*\*(.+?)\*\*"#, with: "$1", options: .regularExpression)
    }
}

/// One chip of «Открывается чем»: a milestone waited on, and whether it is closed already.
struct GoalDependencyChip: Identifiable, Equatable {
    let code: String
    let isOpened: Bool

    var id: String { code }
    var text: String { "\(code) · \(isOpened ? GoalsFormat.openedLabel : GoalsFormat.waitingLabel)" }
}

@MainActor
final class GoalsViewModel: ObservableObject {
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    static let cacheKey = "goals.board"

    @Published private(set) var state: LoadState = .idle
    @Published private(set) var board: GoalsBoardDTO?
    /// Codes whose status is being written right now.
    @Published private(set) var saving: Set<String> = []
    /// Non-nil while the board shown is the cached one; the moment it was cached.
    @Published private(set) var offlineAsOf: Date?
    /// Why the last toggle was refused, in words; the screen shows it above the board.
    @Published var errorMessage: String?

    private let apiProvider: () -> GoalsAPI?
    private let cache: ReadThroughCache
    /// Reads, numbered as they are sent, and the newest one shown: two quick toggles re-read the
    /// board twice, and the first answer may arrive last.
    private var readsSent = 0
    private var readShown = 0

    init(
        apiProvider: @escaping () -> GoalsAPI?,
        cacheStore: CacheStore = InMemoryCacheStore(),
        now: @escaping () -> Date = Date.init
    ) {
        self.apiProvider = apiProvider
        self.cache = ReadThroughCache(store: cacheStore, now: now)
    }

    convenience init(api: GoalsAPI, cacheStore: CacheStore = InMemoryCacheStore()) {
        self.init(apiProvider: { api }, cacheStore: cacheStore)
    }

    static func live() -> GoalsViewModel {
        GoalsViewModel(apiProvider: { APIClient.live() }, cacheStore: ReadCacheLive.shared)
    }

    /// Nothing imported yet: no level, no milestone, no goal of the quarter.
    var isEmpty: Bool {
        guard let board else { return false }
        return board.levels.isEmpty && board.milestones.isEmpty && board.goals.isEmpty
    }

    func load() async {
        // A board already on screen stays while it is read again: pull to refresh must not blank it.
        if state != .loaded { state = .loading }
        guard let api = apiProvider() else {
            state = .failure(GoalsFormat.notConfiguredMessage)
            return
        }
        readsSent += 1
        let read = readsSent
        do {
            let outcome = try await cache.load(key: Self.cacheKey) { try await api.fetchGoals() }
            guard read > readShown else { return }
            readShown = read
            switch outcome {
            case .fresh(let value):
                board = value
                offlineAsOf = nil
            case .stale(let value, let updatedAt):
                board = value
                offlineAsOf = updatedAt
            }
            state = .loaded
        } catch let error as APIClientError {
            if board == nil { state = .failure(error.userMessage) } else { errorMessage = error.userMessage }
        } catch {
            if board == nil { state = .failure("Unexpected error") } else { errorMessage = "Unexpected error" }
        }
    }

    /// Closes the milestone or opens a closed one, then re-reads the whole board: closing M9 is not a
    /// fact about M9 alone — M10 waits on it, and its chip has to change in the same redraw.
    func toggle(_ code: String) async {
        guard !saving.contains(code),
              let milestone = board?.milestones.first(where: { $0.code == code }),
              let api = apiProvider() else { return }
        errorMessage = nil
        saving.insert(code)
        defer { saving.remove(code) }
        do {
            _ = try await api.patchMilestone(code: code, status: GoalsFormat.toggled(milestone.status))
        } catch let error as APIClientError {
            errorMessage = error.userMessage
            return
        } catch {
            errorMessage = "Unexpected error"
            return
        }
        await load()
    }

    /// «Открывается чем» of one milestone, read against the statuses of the board on screen.
    func dependencies(of milestone: MilestoneDTO) -> [GoalDependencyChip] {
        let statuses = Dictionary(
            (board?.milestones ?? []).map { ($0.code, $0.status) }, uniquingKeysWith: { first, _ in first }
        )
        return milestone.dependsOn.map { GoalDependencyChip(code: $0, isOpened: statuses[$0] == .done) }
    }
}
