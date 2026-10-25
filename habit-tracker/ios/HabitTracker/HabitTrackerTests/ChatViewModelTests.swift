// [review:need-review] PHASE-01/212
// summary: tests for the chat view model on a scripted API — opening (latest, new, named), a streamed turn folded into the live bubble, refusals, cancelling, a stuck dialogue, guarded deletion from history, and plan ticks, apply and dismiss
import XCTest
@testable import HabitTracker

final class MockChatAPI: ChatAPI {
    var conversationsResult: Result<[ChatConversationDTO], Error> = .success([])
    var createdConversationID = 100
    var details: [Int: [ChatMessageDTO]] = [:]
    var plansByID: [Int: ChatPlanDTO] = [:]
    var deleteResults: [Int: Error] = [:]
    var applyResults: [Result<ChatPlanApplyResultDTO, Error>] = []
    /// Events of the next turn; `nil` as the failure means the server closes the stream.
    var turnEvents: [ChatStreamEvent] = []
    var turnFailure: Error?
    /// The stream stays open after its events, like a model that went quiet.
    var holdTurnOpen = false

    private(set) var createCalls = 0
    private(set) var deletedIDs: [Int] = []
    private(set) var resetIDs: [Int] = []
    private(set) var sentMessages: [(conversationID: Int, content: String)] = []
    private(set) var applyKeys: [String] = []
    private(set) var appliedSelections: [ChatPlanSelectionDTO] = []
    private(set) var dismissedPlans: [Int] = []
    private(set) var turnTerminated = false

    func fetchConversations(limit: Int) async throws -> [ChatConversationDTO] {
        try conversationsResult.get()
    }

    func createConversation() async throws -> ChatConversationDTO {
        createCalls += 1
        return ChatTestData.conversation(id: createdConversationID)
    }

    func fetchConversation(id: Int) async throws -> ChatConversationDetailDTO {
        ChatConversationDetailDTO(id: id, messages: details[id] ?? [])
    }

    func resetConversation(id: Int) async throws -> ChatResetDTO {
        resetIDs.append(id)
        details[id] = (details[id] ?? []).map { ChatTestData.message(from: $0, status: ChatMessageDTO.interruptedStatus) }
        return ChatResetDTO(reset: 1)
    }

    func deleteConversation(id: Int) async throws {
        deletedIDs.append(id)
        if let error = deleteResults[id] { throw error }
    }

    func fetchPlan(id: Int) async throws -> ChatPlanDTO {
        guard let plan = plansByID[id] else { throw APIClientError.unexpectedStatus(404) }
        return plan
    }

    func applyPlan(
        id: Int, selection: ChatPlanSelectionDTO, idempotencyKey: String
    ) async throws -> ChatPlanApplyResultDTO {
        applyKeys.append(idempotencyKey)
        appliedSelections.append(selection)
        return try applyResults.removeFirst().get()
    }

    func dismissPlan(id: Int) async throws {
        dismissedPlans.append(id)
        if let plan = plansByID[id] {
            plansByID[id] = ChatTestData.plan(id: id, status: ChatPlanDTO.dismissedStatus, body: plan.plan)
        }
    }

    func streamMessage(
        conversationID: Int, content: String
    ) -> AsyncThrowingStream<ChatStreamEvent, Error> {
        sentMessages.append((conversationID, content))
        let events = turnEvents
        let failure = turnFailure
        let hold = holdTurnOpen
        return AsyncThrowingStream { continuation in
            for event in events { continuation.yield(event) }
            if hold {
                continuation.onTermination = { [weak self] _ in
                    self?.turnTerminated = true
                }
            } else {
                continuation.finish(throwing: failure)
            }
        }
    }
}

enum ChatTestData {
    static func conversation(id: Int, title: String? = nil, messageCount: Int = 0) -> ChatConversationDTO {
        ChatConversationDTO(
            id: id, title: title, startedOn: "2026-10-25", kind: "general",
            lastMessageAt: nil, createdAt: "2026-10-25T09:00:00",
            usage: ChatUsageDTO(messageCount: messageCount)
        )
    }

    static func message(
        id: Int, seq: Int, role: String = "assistant", content: String = "text",
        status: String = "complete", planId: Int? = nil
    ) -> ChatMessageDTO {
        ChatMessageDTO(
            id: id, seq: seq, role: role, content: content, status: status, errorCode: nil,
            createdAt: "2026-10-25T10:00:00", planId: planId, retrievals: nil
        )
    }

    static func message(from message: ChatMessageDTO, status: String) -> ChatMessageDTO {
        ChatMessageDTO(
            id: message.id, seq: message.seq, role: message.role, content: message.content,
            status: status, errorCode: nil, createdAt: message.createdAt,
            planId: message.planId, retrievals: message.retrievals
        )
    }

    static let body = ChatPlanBodyDTO(
        entryDate: "2026-10-25",
        metrics: [
            ChatPlanMetricDTO(categoryId: 1, fieldId: 2, value: 30, sourceText: "30 отжиманий"),
            ChatPlanMetricDTO(categoryId: 1, fieldId: 3, value: 300, sourceText: "300 приседаний", implausible: true),
        ],
        checklist: [
            ChatPlanCheckDTO(categoryId: 3, fieldId: 5, sourceText: "витамины"),
            ChatPlanCheckDTO(categoryId: 3, fieldId: 6, sourceText: "зарядка", uncertain: true),
        ],
        journal: ChatPlanJournalDTO(title: nil, content: "Хороший день", mood: nil, tags: nil, mode: "append"),
        dayPlan: nil
    )

    static func plan(
        id: Int, status: String = ChatPlanDTO.proposedStatus, body: ChatPlanBodyDTO = ChatTestData.body
    ) -> ChatPlanDTO {
        ChatPlanDTO(
            id: id, messageId: 31, entryDate: "2026-10-25", status: status, plan: body,
            operationCount: 4
        )
    }
}

@MainActor
final class ChatViewModelTests: XCTestCase {
    private var api: MockChatAPI!
    private var viewModel: ChatViewModel!

    override func setUp() async throws {
        api = MockChatAPI()
        viewModel = ChatViewModel(api: api)
    }

    private func openConversation(_ id: Int = 4, messages: [ChatMessageDTO] = []) async {
        api.details[id] = messages
        await viewModel.open(conversationID: id)
    }

    private func waitUntil(_ condition: @autoclosure () -> Bool) async {
        for _ in 0..<400 where !condition() {
            try? await Task.sleep(nanoseconds: 5_000_000)
        }
    }

    // MARK: - Opening

    func testOpensTheLatestConversationWhenNoneIsNamed() async {
        api.conversationsResult = .success([ChatTestData.conversation(id: 7)])
        api.details[7] = [ChatTestData.message(id: 1, seq: 1, role: "user", content: "Привет")]
        await viewModel.refresh()

        XCTAssertEqual(viewModel.screen, .ready(conversationID: 7))
        XCTAssertEqual(viewModel.messages.map(\.content), ["Привет"])
        XCTAssertEqual(api.createCalls, 0)
    }

    func testCreatesAConversationWhenThereIsNone() async {
        await viewModel.refresh()

        XCTAssertEqual(viewModel.screen, .ready(conversationID: 100))
        XCTAssertEqual(api.createCalls, 1)
    }

    func testListFailureShowsAFailedScreen() async {
        api.conversationsResult = .failure(APIClientError.unauthorized)
        await viewModel.refresh()

        XCTAssertEqual(viewModel.screen, .failed("Invalid API key (401)"))
    }

    func testNoServerAddressShowsTheSettingsHint() async {
        viewModel = ChatViewModel(apiProvider: { nil })
        await viewModel.refresh()

        XCTAssertEqual(viewModel.screen, .failed(ChatViewModel.notConfiguredMessage))
    }

    func testDraftIsKeptPerConversation() async {
        await openConversation(4)
        viewModel.draft = "недописанное"
        await openConversation(5)
        XCTAssertEqual(viewModel.draft, "")
        await openConversation(4)
        XCTAssertEqual(viewModel.draft, "недописанное")
    }

    // MARK: - Turn

    func testSendStreamsTheAnswerThenRereadsTheStoredMessages() async {
        await openConversation()
        api.turnEvents = [
            .thinking, .writing, .delta("При"), .delta("вет"),
            .done(messageID: 2, seq: 2, status: "complete"),
        ]
        api.details[4] = [
            ChatTestData.message(id: 1, seq: 1, role: "user", content: "Привет!"),
            ChatTestData.message(id: 2, seq: 2, content: "Привет"),
        ]
        viewModel.draft = "  Привет!  "
        viewModel.send()

        XCTAssertEqual(viewModel.draft, "", "the draft goes with the question")
        XCTAssertEqual(viewModel.turn?.question, "Привет!")
        await viewModel.awaitTurn()

        XCTAssertEqual(api.sentMessages.first?.content, "Привет!")
        XCTAssertNil(viewModel.turn)
        XCTAssertEqual(viewModel.messages.map(\.seq), [1, 2])
    }

    func testTextBeforeARetrievalIsDroppedFromTheLiveBubble() async {
        await openConversation()
        api.turnEvents = [
            .delta("need: day_card"),
            .retrieval(queryName: "day_card", rowCount: 3, refusal: nil),
            .delta("Ответ"),
            .error(code: "turn_timeout"),
        ]
        viewModel.draft = "Что за день?"
        viewModel.send()
        await viewModel.awaitTurn()

        XCTAssertEqual(viewModel.turn?.text, "Ответ")
        XCTAssertEqual(viewModel.turn?.retrievalCount, 1)
        XCTAssertEqual(viewModel.turn?.failure, ChatViewModel.turnErrorText["turn_timeout"])
    }

    func testThoughtActivityNeverReachesTheAnswerText() async {
        await openConversation()
        api.turnEvents = [.thinking, .acting(tool: "Read"), .error(code: "backend_failed")]
        viewModel.draft = "x"
        viewModel.send()
        await viewModel.awaitTurn()

        XCTAssertEqual(viewModel.turn?.text, "")
        XCTAssertEqual(viewModel.turn?.activity, .acting(tool: "Read"))
    }

    func testRefusal409ShowsTheInFlightTextAndRereadsTheFeed() async {
        await openConversation()
        api.turnFailure = ChatTurnRefusal(status: 409, code: "turn 2 is still running")
        api.details[4] = [ChatTestData.message(id: 2, seq: 2, status: ChatMessageDTO.streamingStatus)]
        viewModel.draft = "x"
        viewModel.send()
        await viewModel.awaitTurn()

        XCTAssertEqual(viewModel.turn?.failure, ChatViewModel.turnInFlightText)
        XCTAssertTrue(viewModel.isStuck, "the stored open turn is now in the feed")
        XCTAssertFalse(viewModel.canSend)
    }

    func testRefusal429ShowsTheSlotsText() async {
        await openConversation()
        api.turnFailure = ChatTurnRefusal(status: 429, code: "chat_slots_busy")
        viewModel.draft = "x"
        viewModel.send()
        await viewModel.awaitTurn()

        XCTAssertEqual(viewModel.turn?.failure, ChatViewModel.turnErrorText["chat_slots_busy"])
    }

    func testTransportFailureKeepsTheBubbleWithTheErrorText() async {
        await openConversation()
        api.turnEvents = [.delta("часть")]
        api.turnFailure = APIClientError.transport(code: -1005)
        viewModel.draft = "x"
        viewModel.send()
        await viewModel.awaitTurn()

        XCTAssertEqual(viewModel.turn?.text, "часть")
        XCTAssertEqual(viewModel.turn?.failure, "Network error (-1005)")
        XCTAssertFalse(viewModel.isTurnRunning)
    }

    func testCancellingMidAnswerClosesTheStream() async {
        await openConversation()
        api.turnEvents = [.delta("а")]
        api.holdTurnOpen = true
        viewModel.draft = "x"
        viewModel.send()
        await waitUntil(self.viewModel.turn?.text == "а")
        XCTAssertTrue(viewModel.isTurnRunning)

        viewModel.cancelTurn()
        await waitUntil(self.api.turnTerminated)

        XCTAssertTrue(api.turnTerminated, "the connection is closed, not left to run")
        XCTAssertNil(viewModel.turn)
    }

    func testCannotSendTwiceWhileATurnRuns() async {
        await openConversation()
        api.holdTurnOpen = true
        viewModel.draft = "one"
        viewModel.send()
        viewModel.draft = "two"
        viewModel.send()
        await waitUntil(self.api.sentMessages.count >= 1)

        XCTAssertEqual(api.sentMessages.count, 1)
        XCTAssertEqual(viewModel.draft, "two", "the refused draft stays in the field")
        viewModel.cancelTurn()
    }

    func testStuckDialogueBlocksSendingUntilReset() async {
        await openConversation(messages: [
            ChatTestData.message(id: 2, seq: 2, status: ChatMessageDTO.streamingStatus),
        ])
        viewModel.draft = "x"
        XCTAssertTrue(viewModel.isStuck)
        XCTAssertFalse(viewModel.canSend)

        await viewModel.reset()

        XCTAssertEqual(api.resetIDs, [4])
        XCTAssertFalse(viewModel.isStuck)
        XCTAssertTrue(viewModel.canSend)
    }

    // MARK: - History and deletion

    func testHistoryLoadsTheList() async {
        api.conversationsResult = .success([
            ChatTestData.conversation(id: 4, messageCount: 6), ChatTestData.conversation(id: 3),
        ])
        await viewModel.loadHistory()

        XCTAssertEqual(viewModel.historyState, .loaded)
        XCTAssertEqual(viewModel.conversations.map(\.id), [4, 3])
    }

    func testDeletingAnotherConversationLeavesTheOpenOneAlone() async {
        api.conversationsResult = .success([ChatTestData.conversation(id: 4), ChatTestData.conversation(id: 3)])
        await openConversation(4)
        await viewModel.loadHistory()
        await viewModel.deleteConversation(id: 3)

        XCTAssertEqual(api.deletedIDs, [3])
        XCTAssertEqual(viewModel.conversations.map(\.id), [4])
        XCTAssertEqual(viewModel.screen, .ready(conversationID: 4))
    }

    func testDeletingTheOpenConversationLeavesTheScreenEmptyWithoutANewOne() async {
        await openConversation(4)
        viewModel.draft = "забыть"
        await viewModel.deleteConversation(id: 4)

        XCTAssertEqual(viewModel.screen, .empty)
        XCTAssertTrue(viewModel.messages.isEmpty)
        XCTAssertEqual(viewModel.draft, "")
        XCTAssertEqual(api.createCalls, 0)
        await viewModel.refresh()
        XCTAssertEqual(viewModel.screen, .empty, "coming back to the screen does not swap it silently")
    }

    func testOpenConversationWithARunningAnswerIsNotOfferedForDeletion() async {
        await openConversation(4)
        api.holdTurnOpen = true
        viewModel.draft = "x"
        viewModel.send()

        XCTAssertEqual(viewModel.deleteBlockedReason(for: 4), ChatViewModel.deleteRunningText)
        XCTAssertNil(viewModel.deleteBlockedReason(for: 3))
        await viewModel.deleteConversation(id: 4)

        XCTAssertTrue(api.deletedIDs.isEmpty, "no request is sent")
        XCTAssertEqual(viewModel.historyNotice, ChatViewModel.deleteRunningText)
        viewModel.cancelTurn()
    }

    func testServerConflictOnDeleteIsExplained() async {
        await openConversation(4)
        api.deleteResults[3] = APIClientError.unexpectedStatus(409)
        await viewModel.deleteConversation(id: 3)

        XCTAssertEqual(viewModel.historyNotice, ChatViewModel.deleteConflictText)
        XCTAssertEqual(viewModel.screen, .ready(conversationID: 4))
    }

    func testAlreadyDeletedConversationCountsAsDeleted() async {
        api.conversationsResult = .success([ChatTestData.conversation(id: 3)])
        await openConversation(4)
        await viewModel.loadHistory()
        api.deleteResults[3] = APIClientError.unexpectedStatus(404)
        await viewModel.deleteConversation(id: 3)

        XCTAssertTrue(viewModel.conversations.isEmpty)
        XCTAssertNil(viewModel.historyNotice)
    }

    // MARK: - Plans

    func testPlanRowsTheModelDoubtedArriveUnticked() {
        let draft = ChatPlanDraft(plan: ChatTestData.body)

        XCTAssertTrue(draft.isTicked(.metric(0)))
        XCTAssertFalse(draft.isTicked(.metric(1)), "implausible value")
        XCTAssertTrue(draft.isTicked(.check(0)))
        XCTAssertFalse(draft.isTicked(.check(1)), "uncertain")
        XCTAssertTrue(draft.isTicked(.journal))
        XCTAssertFalse(draft.isTicked(.dayPlan), "the plan has no day plan")
    }

    func testSelectionCarriesOnlyTheTickedRowsUnchanged() {
        var draft = ChatPlanDraft(plan: ChatTestData.body)
        draft.toggle(.journal)
        draft.toggle(.check(1))
        let selection = draft.selection(of: ChatTestData.body)

        XCTAssertEqual(selection.metrics, [ChatTestData.body.metrics[0]])
        XCTAssertEqual(selection.checklist, ChatTestData.body.checklist)
        XCTAssertNil(selection.journal)
        XCTAssertFalse(selection.dayPlan)
    }

    func testOpeningAConversationLoadsItsPlans() async {
        api.plansByID[9] = ChatTestData.plan(id: 9)
        await openConversation(messages: [ChatTestData.message(id: 31, seq: 2, planId: 9)])

        XCTAssertEqual(viewModel.plans[9]?.status, ChatPlanDTO.proposedStatus)
        XCTAssertNotNil(viewModel.planDrafts[9])
    }

    func testApplySendsTheTickedSelectionAndTakesTheServersPlan() async {
        api.plansByID[9] = ChatTestData.plan(id: 9)
        await openConversation(messages: [ChatTestData.message(id: 31, seq: 2, planId: 9)])
        api.applyResults = [.success(ChatPlanApplyResultDTO(
            plan: ChatTestData.plan(id: 9, status: ChatPlanDTO.appliedStatus), appliedOperations: 3
        ))]
        await viewModel.applyPlan(id: 9)

        XCTAssertEqual(api.appliedSelections.first?.metrics.count, 1)
        XCTAssertEqual(viewModel.plans[9]?.status, ChatPlanDTO.appliedStatus)
        XCTAssertEqual(viewModel.appliedOperations[9], 3)
    }

    func testRetryAfterALostAnswerReusesTheIdempotencyKey() async {
        api.plansByID[9] = ChatTestData.plan(id: 9)
        await openConversation(messages: [ChatTestData.message(id: 31, seq: 2, planId: 9)])
        api.applyResults = [
            .failure(APIClientError.timeout),
            .success(ChatPlanApplyResultDTO(
                plan: ChatTestData.plan(id: 9, status: ChatPlanDTO.appliedStatus), appliedOperations: 3
            )),
        ]
        await viewModel.applyPlan(id: 9)
        XCTAssertEqual(viewModel.planNotices[9], "Connection timed out")
        await viewModel.applyPlan(id: 9)

        XCTAssertEqual(api.applyKeys.count, 2)
        XCTAssertEqual(Set(api.applyKeys).count, 1, "the same key on the retry")
        XCTAssertNil(viewModel.planNotices[9])
    }

    func testApplyConflictExplainsAndTakesTheCurrentPlan() async {
        api.plansByID[9] = ChatTestData.plan(id: 9)
        await openConversation(messages: [ChatTestData.message(id: 31, seq: 2, planId: 9)])
        api.applyResults = [.failure(APIClientError.unexpectedStatus(409))]
        api.plansByID[9] = ChatTestData.plan(id: 9, status: ChatPlanDTO.staleStatus)
        await viewModel.applyPlan(id: 9)

        XCTAssertEqual(viewModel.planNotices[9], ChatViewModel.planConflictText)
        XCTAssertEqual(viewModel.plans[9]?.status, ChatPlanDTO.staleStatus)
    }

    func testApplyWithNothingTickedSendsNothing() async {
        api.plansByID[9] = ChatTestData.plan(id: 9)
        await openConversation(messages: [ChatTestData.message(id: 31, seq: 2, planId: 9)])
        for item in [ChatPlanDraft.Item.metric(0), .check(0), .journal] {
            viewModel.togglePlanItem(item, planID: 9)
        }
        await viewModel.applyPlan(id: 9)

        XCTAssertTrue(api.applyKeys.isEmpty)
    }

    func testDismissTakesTheStatusFromTheServer() async {
        api.plansByID[9] = ChatTestData.plan(id: 9)
        await openConversation(messages: [ChatTestData.message(id: 31, seq: 2, planId: 9)])
        await viewModel.dismissPlan(id: 9)

        XCTAssertEqual(api.dismissedPlans, [9])
        XCTAssertEqual(viewModel.plans[9]?.status, ChatPlanDTO.dismissedStatus)
    }
}
