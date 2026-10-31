// [review:need-review] PHASE-01/216, PHASE-03/295
// summary: state of the Goals screen, the native twin of GoalsBoard.tsx — the board read through the read cache, a milestone toggled between closed and open by one PATCH that re-reads the whole board (closing M9 changes how M10 reads), reads numbered so an older answer never overwrites a newer one, and the words the board shows; adding a goal of the quarter (a fresh read first, so the set that goes in the one PUT is the server's own and not the screen's; at most five; the read cache follows the write) and every failure said in Russian
import Foundation

/// Words and small rules of the goal board, the same as the web's `GoalsBoard.tsx`.
enum GoalsFormat {
    static let emptyText = "Целей на этот квартал пока нет. Добавьте первую."
    static let notConfiguredMessage = "Укажите адрес сервера в Настройках."
    /// The server keeps at most five goals in a quarter («больше пяти — цель размазана»).
    static let maxQuarterGoals = 5
    static let emptyTextRefusal = "Напишите, какая это цель."
    static let tooManyGoalsRefusal = "В квартале не больше пяти целей: уберите или замените одну из них."
    static let offlineAddNote = "Нет связи с сервером — цели можно добавить, когда он ответит."
    static let fullQuarterNote = "В квартале пять целей — больше не бывает."
    static let unknownFailure = "Не получилось выполнить действие. Попробуйте ещё раз."

    /// A failure in words a person reads: never the English of `APIClientError.userMessage`, and the
    /// server's own reason when it gave one.
    static func message(for error: Error) -> String {
        switch error {
        case GoalsWriteError.rejected(_, let detail):
            return detail
        case APIClientError.transport:
            return "Нет связи с сервером. Проверьте интернет и адрес в Настройках."
        case APIClientError.timeout:
            return "Сервер не ответил вовремя. Попробуйте ещё раз."
        case APIClientError.unauthorized:
            return "Сервер не принял ключ (401). Проверьте ключ в Настройках."
        case APIClientError.unexpectedStatus(let status):
            return "Сервер ответил ошибкой \(status)."
        case APIClientError.invalidResponse:
            return "Сервер ответил непонятно. Попробуйте ещё раз."
        case APIClientError.invalidBaseURL:
            return "Адрес сервера неверный. Исправьте его в Настройках."
        default:
            return unknownFailure
        }
    }
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
    /// Why the last attempt to add a goal failed; the add form shows it, the board does not.
    @Published private(set) var formError: String?
    @Published private(set) var isAdding = false

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
            guard read > readShown else {
                // The read cache took this answer on its way here; a newer board is already on screen.
                restoreCache()
                return
            }
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
        } catch {
            let message = GoalsFormat.message(for: error)
            if board == nil { state = .failure(message) } else { errorMessage = message }
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
        } catch {
            errorMessage = GoalsFormat.message(for: error)
            return
        }
        await load()
    }

    /// The board is loaded and fresh, and the quarter has a free place. A cached board may be a
    /// quarter or a web edit behind, and the write replaces the whole set.
    var canAddGoal: Bool {
        guard let board, offlineAsOf == nil else { return false }
        return board.goals.count < GoalsFormat.maxQuarterGoals
    }

    /// Why there is no «Добавить цель» button, when there is a board and no button.
    var addGoalNote: String? {
        guard let board else { return nil }
        if offlineAsOf != nil { return GoalsFormat.offlineAddNote }
        return board.goals.count < GoalsFormat.maxQuarterGoals ? nil : GoalsFormat.fullQuarterNote
    }

    func clearFormError() {
        formError = nil
    }

    /// Adds one goal to the quarter. The server takes the quarter as one set and removes the places
    /// that are not in it, so the set is built from a board read right now, never from the one on
    /// screen (a cached board, or a web edit made after the screen opened, would be erased). The
    /// goals already there go with it — same text, link and status — and the new one takes the first
    /// free place. If the read fails, nothing is written. True when the server accepted the goal.
    func addGoal(text: String) async -> Bool {
        guard !isAdding, board != nil else { return false }
        formError = nil
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            formError = GoalsFormat.emptyTextRefusal
            return false
        }
        guard let api = apiProvider() else {
            formError = GoalsFormat.notConfiguredMessage
            return false
        }
        isAdding = true
        defer { isAdding = false }
        let current: GoalsBoardDTO
        do {
            current = try await api.fetchGoals()
        } catch {
            formError = GoalsFormat.message(for: error)
            return false
        }
        adopt(current)
        let taken = Set(current.goals.map(\.ord))
        guard let ord = (1...GoalsFormat.maxQuarterGoals).first(where: { !taken.contains($0) }) else {
            formError = GoalsFormat.tooManyGoalsRefusal
            return false
        }
        let set = current.goals.map {
            QuarterGoalInDTO(ord: $0.ord, textMd: $0.textMd, milestoneCode: $0.milestoneCode, status: $0.status)
        } + [QuarterGoalInDTO(ord: ord, textMd: trimmed, milestoneCode: nil, status: QuarterGoalStatus.open.rawValue)]
        do {
            adopt(try await api.putQuarterGoals(quarter: current.quarter, goals: set))
            errorMessage = nil
            return true
        } catch {
            formError = GoalsFormat.message(for: error)
            return false
        }
    }

    /// Makes an answer the server has just given the board: on screen, in the read cache, and newer
    /// than any read still in flight.
    private func adopt(_ fresh: GoalsBoardDTO) {
        readShown = readsSent
        board = fresh
        offlineAsOf = nil
        restoreCache()
    }

    /// Writes the board on screen back into the read cache. A read that was in flight while the
    /// board changed saves its older answer there when it lands; this puts the newer one back.
    private func restoreCache() {
        guard let board, offlineAsOf == nil else { return }
        cache.store.save(board, forKey: Self.cacheKey, updatedAt: cache.now())
    }

    /// «Открывается чем» of one milestone, read against the statuses of the board on screen.
    func dependencies(of milestone: MilestoneDTO) -> [GoalDependencyChip] {
        let statuses = Dictionary(
            (board?.milestones ?? []).map { ($0.code, $0.status) }, uniquingKeysWith: { first, _ in first }
        )
        return milestone.dependsOn.map { GoalDependencyChip(code: $0, isOpened: statuses[$0] == .done) }
    }
}
