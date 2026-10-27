// [review:need-review] PHASE-01/212, PHASE-03/230
// summary: chat screen state — the open conversation and its stored messages, one streamed turn folded from SSE events (answer text kept apart from progress, text before a retrieval dropped, a late event of an older turn or conversation ignored), refusals with their machine codes, history with guarded deletion and a notice tied to its conversation, and proposed plans with a per-row selection
import Foundation

/// What is left ticked on a plan card. A row can only be unticked, never added: the
/// server narrows the apply to the plan it stored.
struct ChatPlanDraft: Equatable {
    enum Item: Hashable {
        case metric(Int)
        case check(Int)
        case journal
        case dayPlan
    }

    private(set) var ticked: Set<Item>

    /// Rows the model was unsure about arrive unticked.
    init(plan: ChatPlanBodyDTO) {
        var ticked: Set<Item> = []
        for (index, metric) in plan.metrics.enumerated() where metric.isTickedByDefault {
            ticked.insert(.metric(index))
        }
        for (index, check) in plan.checklist.enumerated() where check.isTickedByDefault {
            ticked.insert(.check(index))
        }
        if plan.journal != nil { ticked.insert(.journal) }
        if plan.dayPlan != nil { ticked.insert(.dayPlan) }
        self.ticked = ticked
    }

    var isEmpty: Bool { ticked.isEmpty }

    func isTicked(_ item: Item) -> Bool { ticked.contains(item) }

    mutating func toggle(_ item: Item) {
        if ticked.contains(item) { ticked.remove(item) } else { ticked.insert(item) }
    }

    /// The apply body: the ticked subset of the stored operations, unchanged.
    func selection(of plan: ChatPlanBodyDTO) -> ChatPlanSelectionDTO {
        ChatPlanSelectionDTO(
            metrics: plan.metrics.enumerated().filter { ticked.contains(.metric($0.offset)) }.map(\.element),
            checklist: plan.checklist.enumerated().filter { ticked.contains(.check($0.offset)) }.map(\.element),
            journal: ticked.contains(.journal) ? plan.journal : nil,
            dayPlan: ticked.contains(.dayPlan)
        )
    }
}

@MainActor
final class ChatViewModel: ObservableObject {
    enum Screen: Equatable {
        case loading
        case failed(String)
        /// No conversation on purpose: the open one was deleted, and a silently opened
        /// or created replacement would look like a swap.
        case empty
        case ready(conversationID: Int)
    }

    /// What the model is busy with between the question and the first word.
    enum Activity: Equatable {
        case waiting
        case thinking
        case writing
        case acting(tool: String?)
    }

    /// The turn in flight, or the one that just failed. `text` is the answer only; the
    /// model's progress lives in `activity`, so a thought can never end up in the answer.
    struct Turn: Equatable {
        let question: String
        var text = ""
        var activity: Activity = .waiting
        var retrievalCount = 0
        var failure: String?
        /// The stream ended well, but the stored copy could not be re-read: the bubble
        /// stays as the only place the answer is on screen.
        var isStoredCopyMissing = false
    }

    /// A problem with deleting one conversation. The reason decides when it goes away.
    struct HistoryNotice: Equatable {
        enum Reason: Equatable {
            /// The answer in that conversation is still running; gone when the turn ends.
            case answerRunning
            case other
        }

        let conversationID: Int
        let reason: Reason
        let text: String
    }

    enum HistoryState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    @Published private(set) var screen: Screen = .loading
    @Published private(set) var messages: [ChatMessageDTO] = [] {
        didSet { dropFinishedRunningNotice() }
    }
    @Published private(set) var turn: Turn? {
        didSet { dropFinishedRunningNotice() }
    }
    @Published var draft = ""
    /// A short problem the screen shows above the field (also without a field): a failed
    /// reset, a failed new conversation, a plan that did not load.
    @Published private(set) var notice: String?

    @Published private(set) var conversations: [ChatConversationDTO] = []
    @Published private(set) var historyState: HistoryState = .idle
    @Published private(set) var historyNotice: HistoryNotice?

    @Published private(set) var plans: [Int: ChatPlanDTO] = [:]
    @Published private(set) var planDrafts: [Int: ChatPlanDraft] = [:]
    @Published private(set) var planNotices: [Int: String] = [:]
    @Published private(set) var planBusy: Set<Int> = []
    @Published private(set) var appliedOperations: [Int: Int] = [:]

    static let notConfiguredMessage = "Set the server address in Settings"
    static let historyLimit = 50
    static let turnFailedFallback = "Ход не удался."
    static let turnInFlightText = "В этом разговоре ещё идёт ход. Дождитесь ответа или сбросьте зависший."
    static let deleteRunningText = "Ответ ещё идёт. Дождитесь его или сбросьте разговор, потом удалите."
    static let deleteConflictText = "В разговоре ещё идёт ответ, удалить его сейчас нельзя."
    static let planConflictText = "План уже применён или устарел."
    static let planLoadFailedText = "План не загрузился: "
    static let planRefreshFailedText = "Не удалось обновить карточку плана: "
    static let planRejectedText = "План не проходит правила дня. Попросите чат предложить заново."
    static let turnErrorText: [String: String] = [
        "backend_failed": "Бэкенд не смог ответить. Ход записан как неудавшийся.",
        "first_delta_timeout": "Бэкенд не сказал ни слова и был остановлен.",
        "turn_timeout": "Ход не уложился в отведённое время и был остановлен.",
        "chat_slots_busy": "Сейчас идут другие разговоры. Попробуйте через минуту.",
    ]
    static let messageStatusNote: [String: String] = [
        ChatMessageDTO.interruptedStatus: "Ответ оборван — показано то, что успело прийти.",
        ChatMessageDTO.streamingStatus: "Ход не закрыт: похоже, бэкенд перезапустили. Сбросьте разговор.",
    ]

    private let apiProvider: () -> ChatAPI?
    private var openID: Int?
    /// What "Retry" opens after a failed load: the conversation asked for, not the latest.
    private var retryID: Int?
    /// Bumped on every switch of conversation; a late answer for an older one is dropped.
    private var generation = 0
    private var turnTask: Task<Void, Never>?
    /// Bumped whenever a turn starts or is cut off; a task of an older turn writes nothing.
    private var turnToken = 0
    private var drafts: [Int: String] = [:]
    private var applyKeys: [Int: String] = [:]

    /// Primary init: the provider is re-evaluated on every call, so Settings changes
    /// (server address / API key) apply without an app restart.
    init(apiProvider: @escaping () -> ChatAPI?) {
        self.apiProvider = apiProvider
    }

    convenience init(api: ChatAPI) {
        self.init(apiProvider: { api })
    }

    static func live() -> ChatViewModel {
        ChatViewModel(apiProvider: { APIClient.live() })
    }

    // MARK: - Derived state

    var isTurnRunning: Bool {
        guard let turn else { return false }
        return turn.failure == nil && !turn.isStoredCopyMissing
    }

    /// A stored turn nobody will close: the worker died with the model process.
    var isStuck: Bool { messages.contains(where: \.isStreaming) }

    var isBusy: Bool { isTurnRunning || isStuck }

    var isReady: Bool {
        if case .ready = screen { return true }
        return false
    }

    var canSend: Bool {
        isReady && !isBusy && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var openConversationID: Int? { openID }

    // MARK: - Opening

    /// Screen appeared: load on first show, otherwise re-read what the server stores
    /// (a turn cancelled on leaving the screen is stored as `interrupted`).
    func refresh() async {
        switch screen {
        case .ready(let id):
            guard !isTurnRunning else { return }
            turn = nil
            await reloadMessages(id: id)
        case .empty:
            return
        case .loading, .failed:
            await retry()
        }
    }

    /// Loads again what the last attempt was after, not whatever is the latest now.
    func retry() async {
        await open(conversationID: retryID)
    }

    /// Opens one conversation; `nil` means the latest one, or a new one when there is none.
    func open(conversationID: Int?) async {
        // Already on screen: switching to it would cut the running answer short.
        if let conversationID, conversationID == openID, isReady { return }
        stashDraft()
        cancelTurn()
        generation += 1
        let mine = generation
        openID = nil
        retryID = conversationID
        messages = []
        notice = nil
        screen = .loading
        guard let api = apiProvider() else {
            screen = .failed(Self.notConfiguredMessage)
            return
        }
        do {
            let id: Int
            if let conversationID {
                id = conversationID
            } else if let latest = try await api.fetchConversations(limit: 1).first {
                id = latest.id
            } else {
                id = try await api.createConversation().id
            }
            guard mine == generation else { return }
            retryID = id
            let detail = try await api.fetchConversation(id: id)
            guard mine == generation else { return }
            messages = detail.messages
            draft = drafts[id] ?? ""
            openID = id
            screen = .ready(conversationID: id)
            await loadPlans(api: api, for: detail.messages, id: id)
        } catch {
            // Leaving the screen cancels the load; coming back loads again.
            guard mine == generation, !Task.isCancelled else { return }
            screen = .failed(Self.message(for: error))
        }
    }

    func startNewConversation() async {
        notice = nil
        guard let api = apiProvider() else {
            notice = Self.notConfiguredMessage
            return
        }
        do {
            let created = try await api.createConversation()
            await open(conversationID: created.id)
        } catch {
            notice = Self.message(for: error)
        }
    }

    private func stashDraft() {
        if let openID { drafts[openID] = draft.isEmpty ? nil : draft }
    }

    /// `true` when the stored messages were read and put on screen.
    @discardableResult
    private func reloadMessages(id: Int) async -> Bool {
        guard let api = apiProvider() else { return false }
        do {
            let detail = try await api.fetchConversation(id: id)
            guard openID == id else { return false }
            messages = detail.messages
            await loadPlans(api: api, for: detail.messages, id: id)
            return true
        } catch {
            guard openID == id, !Task.isCancelled else { return false }
            notice = Self.message(for: error)
            return false
        }
    }

    // MARK: - Turn

    /// Sends the draft. The turn runs in a task of its own; `awaitTurn()` joins it.
    func send() {
        guard case .ready(let id) = screen, canSend else { return }
        let question = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        // The draft goes now, not when the turn ends: the question has left, and putting
        // it back would offer to send it twice. A failed turn does not bring it back.
        draft = ""
        drafts[id] = nil
        notice = nil
        turnTask?.cancel()
        turnToken += 1
        let token = turnToken
        turn = Turn(question: question)
        turnTask = Task { await runTurn(id: id, token: token, question: question) }
    }

    func awaitTurn() async {
        await turnTask?.value
    }

    /// Closes the connection. The server stores what it had as `interrupted`.
    func cancelTurn() {
        turnTask?.cancel()
        turnTask = nil
        turnToken += 1
        turn = nil
    }

    /// The turn of this conversation is still the one on screen.
    private func isCurrent(id: Int, token: Int) -> Bool {
        openID == id && turnToken == token
    }

    private func runTurn(id: Int, token: Int, question: String) async {
        guard let api = apiProvider() else {
            if isCurrent(id: id, token: token) { turn?.failure = Self.notConfiguredMessage }
            return
        }
        do {
            for try await event in api.streamMessage(conversationID: id, content: question) {
                guard isCurrent(id: id, token: token) else { return }
                fold(event)
            }
        } catch let refusal as ChatTurnRefusal {
            guard isCurrent(id: id, token: token) else { return }
            turn?.failure = Self.text(for: refusal)
            // A 409 means a stored row nobody closes: it shows in the feed after a re-read.
            if refusal.status == 409 { await reloadMessages(id: id) }
            return
        } catch {
            guard isCurrent(id: id, token: token) else { return }
            turn?.failure = Self.message(for: error)
            return
        }
        guard isCurrent(id: id, token: token), !Task.isCancelled, turn?.failure == nil else { return }
        // The stored rows are the conversation: re-read them instead of gluing in memory.
        let reread = await reloadMessages(id: id)
        guard isCurrent(id: id, token: token) else { return }
        if reread {
            turn = nil
        } else {
            // The answer would vanish from the screen; keep it until a re-read works.
            turn?.isStoredCopyMissing = true
        }
    }

    private func fold(_ event: ChatStreamEvent) {
        guard var current = turn else { return }
        switch event {
        case .delta(let text):
            current.text += text
        case .retrieval:
            // Text before a retrieval frame was addressed to the server, not to the person;
            // the server leaves it out of the stored message and the live bubble must match.
            current.text = ""
            current.retrievalCount += 1
        case .thinking:
            current.activity = .thinking
        case .writing:
            current.activity = .writing
        case .acting(let tool):
            current.activity = .acting(tool: tool)
        case .stepEnd:
            current.activity = .waiting
        case .error(let code):
            current.failure = Self.turnErrorText[code] ?? Self.turnFailedFallback
        case .usage, .stop, .done:
            return
        }
        turn = current
    }

    /// Unsticks a dialogue whose turn nobody will close.
    func reset() async {
        guard case .ready(let id) = screen, let api = apiProvider() else { return }
        do {
            _ = try await api.resetConversation(id: id)
            guard openID == id else { return }
            notice = nil
            await reloadMessages(id: id)
        } catch {
            guard openID == id, !Task.isCancelled else { return }
            notice = Self.message(for: error)
        }
    }

    // MARK: - History

    func loadHistory() async {
        historyNotice = nil
        guard let api = apiProvider() else {
            historyState = .failure(Self.notConfiguredMessage)
            return
        }
        historyState = .loading
        do {
            conversations = try await api.fetchConversations(limit: Self.historyLimit)
            historyState = .loaded
        } catch {
            historyState = .failure(Self.message(for: error))
        }
    }

    /// Why this conversation cannot be deleted right now, or `nil` when it can.
    func deleteBlockedReason(for id: Int) -> String? {
        id == openID && isBusy ? Self.deleteRunningText : nil
    }

    /// The notice with the conversation it is about, so a list of many says what it means.
    var historyNoticeLine: String? {
        guard let notice = historyNotice else { return nil }
        let title = conversations.first { $0.id == notice.conversationID }?.title
        return "«\(title ?? "Разговор \(notice.conversationID)")»: \(notice.text)"
    }

    /// A running-answer notice lasts exactly as long as that answer.
    private func dropFinishedRunningNotice() {
        guard let notice = historyNotice, notice.reason == .answerRunning else { return }
        if deleteBlockedReason(for: notice.conversationID) == nil { historyNotice = nil }
    }

    func deleteConversation(id: Int) async {
        if let reason = deleteBlockedReason(for: id) {
            historyNotice = HistoryNotice(conversationID: id, reason: .answerRunning, text: reason)
            return
        }
        guard let api = apiProvider() else {
            historyNotice = HistoryNotice(conversationID: id, reason: .other, text: Self.notConfiguredMessage)
            return
        }
        do {
            try await api.deleteConversation(id: id)
        } catch APIClientError.unexpectedStatus(404) {
            // Already gone: the list only needs to catch up.
        } catch APIClientError.unexpectedStatus(409) {
            historyNotice = HistoryNotice(conversationID: id, reason: .other, text: Self.deleteConflictText)
            return
        } catch {
            historyNotice = HistoryNotice(conversationID: id, reason: .other, text: Self.message(for: error))
            return
        }
        if historyNotice?.conversationID == id { historyNotice = nil }
        conversations.removeAll { $0.id == id }
        // Decided by what is open now: the person may have switched while the request ran.
        if id == openID {
            cancelTurn()
            generation += 1
            openID = nil
            messages = []
            drafts[id] = nil
            draft = ""
            screen = .empty
        }
    }

    // MARK: - Plans

    private func loadPlans(api: ChatAPI, for messages: [ChatMessageDTO], id: Int) async {
        for planID in messages.compactMap(\.planId) where plans[planID] == nil {
            do {
                let plan = try await api.fetchPlan(id: planID)
                guard openID == id else { return }
                plans[planID] = plan
                planDrafts[planID] = ChatPlanDraft(plan: plan.plan)
            } catch {
                guard openID == id, !Task.isCancelled else { return }
                notice = Self.planLoadFailedText + Self.message(for: error)
            }
        }
    }

    func togglePlanItem(_ item: ChatPlanDraft.Item, planID: Int) {
        planDrafts[planID]?.toggle(item)
    }

    func applyPlan(id planID: Int) async {
        guard
            let plan = plans[planID], plan.status == ChatPlanDTO.proposedStatus,
            let draft = planDrafts[planID], !draft.isEmpty,
            !planBusy.contains(planID), let api = apiProvider()
        else { return }
        planBusy.insert(planID)
        defer { planBusy.remove(planID) }
        // One key per card until the server answers definitively: a retry after a lost
        // answer then returns the original result instead of writing twice.
        let key = applyKeys[planID] ?? UUID().uuidString
        applyKeys[planID] = key
        do {
            let result = try await api.applyPlan(
                id: planID, selection: draft.selection(of: plan.plan), idempotencyKey: key
            )
            plans[planID] = result.plan
            appliedOperations[planID] = result.appliedOperations
            planNotices[planID] = nil
            applyKeys[planID] = nil
        } catch let error as APIClientError {
            if case .unexpectedStatus(let status) = error {
                applyKeys[planID] = nil
                planNotices[planID] = status == 409 ? Self.planConflictText
                    : (status == 422 || status == 400) ? Self.planRejectedText : error.userMessage
                if status == 409 { await refreshPlan(id: planID, api: api) }
            } else {
                planNotices[planID] = error.userMessage
            }
        } catch {
            planNotices[planID] = Self.message(for: error)
        }
    }

    func dismissPlan(id planID: Int) async {
        guard
            let plan = plans[planID], plan.status == ChatPlanDTO.proposedStatus,
            !planBusy.contains(planID), let api = apiProvider()
        else { return }
        planBusy.insert(planID)
        defer { planBusy.remove(planID) }
        do {
            try await api.dismissPlan(id: planID)
            planNotices[planID] = nil
        } catch APIClientError.unexpectedStatus(409) {
            planNotices[planID] = Self.planConflictText
        } catch {
            planNotices[planID] = Self.message(for: error)
            return
        }
        // The server owns the status: take it from there rather than guess.
        await refreshPlan(id: planID, api: api)
    }

    /// Takes the stored plan; if that fails the card keeps its old state and says so,
    /// next to whatever the card already had to say.
    private func refreshPlan(id planID: Int, api: ChatAPI) async {
        do {
            plans[planID] = try await api.fetchPlan(id: planID)
        } catch {
            let failure = Self.planRefreshFailedText + Self.message(for: error)
            planNotices[planID] = [planNotices[planID], failure].compactMap { $0 }.joined(separator: " ")
        }
    }

    // MARK: - Texts

    static func text(for refusal: ChatTurnRefusal) -> String {
        if refusal.status == 409 { return turnInFlightText }
        return refusal.code.flatMap { turnErrorText[$0] } ?? turnFailedFallback
    }

    static func message(for error: Error) -> String {
        (error as? APIClientError)?.userMessage ?? error.localizedDescription
    }
}
