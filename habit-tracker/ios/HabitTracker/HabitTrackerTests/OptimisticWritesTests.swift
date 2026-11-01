// [review:need-review] PHASE-03/316
// summary: PHASE-03/316 round 3 — a mark that waited (behind a write that failed, or past the quiet period after replacing an unsent one) is checked against the day before its PUT, and a mark the web moved meanwhile is refused instead of overwritten
// summary: PHASE-03/316 round 2 — a read on its way when a press is delivered is shown with the press laid over it, and the cache matches the screen (Today, buttons, supplements, Day marks); an online mark is one bare PUT; undo during the send is one undo of its own event, or a withdrawal when the send fails; a refused checklist save gives the server's row back; a newer save of a day replaces the waiting one, never the one being sent
// summary: the class of "a press waits for the server" — a press is on screen and in the sum while the send hangs, a refusal takes it away into "not sent" with a reason while a dead network keeps it, five pluses are five writes under five keys and four presses of a button four steps, two taps of one tick one write, one key across every retry, undo of an unsent press sends nothing, a second Day mark during the first PUT is not lost; the strip stays quiet while a write is merely on its way
import XCTest
@testable import HabitTracker

/// The network side of the queue in miniature: records every send with its key, can hold sends until
/// released, fails on script, and answers each kind of write the way the server does.
@MainActor
final class HeldSender: OutboxSending {
    private(set) var sent: [(action: OutboxAction, key: String)] = []
    /// While true, every send waits for `release()`.
    var holds = false
    /// Consumed one per send, after the hold.
    var failures: [Error] = []
    /// The server's total of each button before any press of the test.
    var tapTotals: [Int: Double] = [:]
    private var held: [CheckedContinuation<Void, Never>] = []

    var heldCount: Int { held.count }

    func release() {
        holds = false
        let waiting = held
        held = []
        waiting.forEach { $0.resume() }
    }

    func send(_ action: OutboxAction, idempotencyKey: String) async throws -> OutboxReply? {
        sent.append((action, idempotencyKey))
        if holds { await withCheckedContinuation { held.append($0) } }
        if !failures.isEmpty { throw failures.removeFirst() }
        switch action {
        case .createEntry(let entry):
            return .entry(EntryDTO(id: 1000 + sent.count, categoryId: entry.categoryId, entryDate: entry.entryDate, values: entry.values))
        case .upsertChecklist(let list):
            let values = list.values.sorted { $0.key < $1.key }.compactMap { key, ticked in
                Int(key).map { EntryValueDTO(fieldId: $0, value: ticked ? "true" : "false") }
            }
            return .entry(EntryDTO(id: 2000, categoryId: list.categoryId, entryDate: list.entryDate, values: values))
        case .tapQuickMark(let tap):
            let total = (tapTotals[tap.quickMarkId] ?? 0) + 1
            tapTotals[tap.quickMarkId] = total
            return .quickMarkEvent(
                QuickMarkEventDTO(
                    eventId: sent.count, quickMarkId: tap.quickMarkId, entryId: 1, entryDate: "2026-10-25",
                    occurredAt: "2026-10-25T09:00:00+00:00", todayTotal: total, done: true
                )
            )
        case .setDayMark(let mark):
            return .dayMark(DayMarkDTO(itemId: mark.itemID, state: mark.state, note: mark.note))
        case .markSupplementTaken(let intake):
            return .supplementIntake(
                SupplementIntakeDTO(id: sent.count, supplementId: intake.supplementId, intakeDate: intake.intakeDate ?? "")
            )
        case .recordPlanFact, .saveNotebook:
            return nil
        }
    }

    func taps(of markID: Int) -> [(action: OutboxAction, key: String)] {
        sent.filter { if case .tapQuickMark(let tap) = $0.action { return tap.quickMarkId == markID } else { return false } }
    }
}

@MainActor
final class OptimisticWritesTests: XCTestCase {
    private let utc = TimeZone(identifier: "UTC")!
    /// 2026-10-25 09:00 UTC.
    private let clock = Date(timeIntervalSince1970: 1_792_918_800)
    private let today = "2026-10-25"

    private var pushups: CategoryDTO {
        CategoryDTO(
            id: 1, name: "Pushups", icon: nil, color: nil, displayMode: "form", streakMode: "build", isActive: true,
            fields: [
                FieldDTO(
                    id: 10, name: "Count", fieldType: .number, isRequired: true, defaultValue: nil,
                    options: nil, order: 0, quickSteps: [10]
                )
            ]
        )
    }

    private var morning: CategoryDTO {
        CategoryDTO(
            id: 2, name: "Morning", icon: nil, color: nil, displayMode: "checklist", streakMode: "build", isActive: true,
            fields: [FieldDTO(id: 20, name: "Meditate", fieldType: .boolean, isRequired: false, defaultValue: nil, options: nil, order: 0)]
        )
    }

    private func button(id: Int = 1, total: Double) -> QuickMarkDTO {
        QuickMarkDTO(
            id: id, label: "Water \(id)", categoryId: id, fieldId: 10 + id, kind: "increment",
            step: 1, unitLabel: nil, icon: nil, color: nil, hotkey: nil, order: 1,
            showInAgent: true, isActive: true, entryDate: today, todayTotal: total,
            done: total != 0, planned: false, planItemId: nil
        )
    }

    private func makeQueue(_ sender: HeldSender) -> OutboxQueue {
        OutboxQueue(store: InMemoryOutboxStore(), now: { [clock] in clock }, sender: { sender })
    }

    private func makeToday(
        categories: [CategoryDTO], sender: HeldSender, cache: CacheStore = InMemoryCacheStore(), entries: [EntryDTO] = []
    ) async -> (TodayViewModel, OutboxQueue, MockTodayAPI) {
        let api = MockTodayAPI()
        api.categoriesResult = .success(categories)
        api.entriesResult = .success(entries)
        let queue = makeQueue(sender)
        let viewModel = TodayViewModel(api: api, cacheStore: cache, outbox: queue, timeZone: utc, now: { [clock] in clock })
        await viewModel.load()
        return (viewModel, queue, api)
    }

    private func makeButtons(
        total: Double, sender: HeldSender, others: [QuickMarkDTO] = [], cache: CacheStore = InMemoryCacheStore()
    ) async -> (QuickMarksViewModel, OutboxQueue, MockQuickMarksAPI) {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([button(total: total)] + others)
        sender.tapTotals[1] = total
        let queue = makeQueue(sender)
        let viewModel = QuickMarksViewModel(api: api, cacheStore: cache, outbox: queue, timeZone: utc, now: { [clock] in clock })
        await viewModel.load()
        return (viewModel, queue, api)
    }

    private func values(_ viewModel: TodayViewModel) -> [String?] {
        viewModel.entries(forCategory: 1).flatMap(\.values).map(\.value)
    }

    // MARK: 1. A press is on screen while the send hangs

    func testAPressIsOnScreenAndInTheSumWhileTheSendHangs() async {
        let sender = HeldSender()
        sender.holds = true
        let (today, _, _) = await makeToday(categories: [pushups], sender: sender)
        let (buttons, _, _) = await makeButtons(total: 3, sender: sender)

        var answered = false
        Task {
            _ = await today.quickAdd(categoryID: 1)
            await buttons.tap(buttons.marks[0])
            answered = true
        }
        await waitUntil { answered }

        XCTAssertEqual(values(today), ["10"], "the step is a row of the day before the server answers")
        XCTAssertEqual(buttons.marks[0].todayTotal, 4, "and the button counts the press")
        XCTAssertFalse(today.waitingCategoryIDs.contains(1), "a write merely on its way is not tagged as waiting")
        await waitUntil { sender.heldCount > 0 }
        sender.release()
    }

    func testTheStripStaysQuietWhileAWriteIsMerelyOnItsWay() {
        let queue = OutboxQueue(store: InMemoryOutboxStore(), now: { [clock] in clock })
        queue.enqueue(.createEntry(EntryCreateDTO(categoryId: 1, entryDate: today, notes: nil, values: [])), label: "Pushups")

        XCTAssertTrue(OutboxQueueBar.shown(queue.writes, at: clock.addingTimeInterval(1)).isEmpty)
        XCTAssertEqual(OutboxQueueBar.shown(queue.writes, at: clock.addingTimeInterval(OutboxQueue.quietPeriod)).count, 1)
    }

    // MARK: 2. A refusal takes the press away; a dead network keeps it

    func testARefusalTakesThePressAwayIntoNotSentWithAReason() async {
        let sender = HeldSender()
        sender.failures = [APIClientError.unexpectedStatus(422)]
        let (today, queue, _) = await makeToday(categories: [pushups], sender: sender)

        _ = await today.quickAdd(categoryID: 1)
        await waitForSend(queue)

        XCTAssertEqual(values(today), [], "the server did not take it: it is not on the screen")
        XCTAssertEqual(queue.failedCount, 1, "it is in the \"not sent\" list")
        XCTAssertEqual(today.saveErrorMessage, "Не отправлено «Pushups»: Сервер не принял данные (422).")
    }

    func testADeadNetworkKeepsThePressQueuedAndOnScreen() async {
        let sender = HeldSender()
        sender.failures = [APIClientError.transport(code: URLError.notConnectedToInternet.rawValue)]
        let (today, queue, _) = await makeToday(categories: [pushups], sender: sender)

        _ = await today.quickAdd(categoryID: 1)
        await waitForSend(queue)

        XCTAssertEqual(values(today), ["10"])
        XCTAssertEqual(queue.pendingCount, 1)
        XCTAssertTrue(today.waitingCategoryIDs.contains(1), "a failed attempt is tagged as waiting at once")
        XCTAssertNil(today.saveErrorMessage)
    }

    func testAWriteLeftOnAServerThatWasDownGoesOutOnItsOwnOnceItIsBack() async {
        let sender = HeldSender()
        sender.failures = [APIClientError.transport(code: URLError.cannotConnectToHost.rawValue)]
        let queue = makeQueue(sender)
        queue.startAutoFlush(monitor: MockNetworkMonitor(), retryDelays: [.milliseconds(20)])
        var delivered: [OutboxDelivery] = []
        let watch = queue.delivered.sink { delivered.append($0) }
        defer { watch.cancel() }

        queue.enqueue(.createEntry(EntryCreateDTO(categoryId: 1, entryDate: today, notes: nil, values: [])), label: "Pushups")
        queue.send()
        await waitUntil { queue.writes.isEmpty }

        XCTAssertEqual(sender.sent.count, 2, "the failed attempt and the retry nobody had to ask for")
        guard case .entry(let entry)? = delivered.first?.reply else { return XCTFail("the delivery carries the server's entry") }
        XCTAssertEqual(entry.categoryId, 1)
    }

    // MARK: 3. Every press counts once

    func testFivePlusesAreFiveWritesUnderFiveKeys() async {
        let sender = HeldSender()
        let (today, queue, _) = await makeToday(categories: [pushups], sender: sender)

        for _ in 0..<5 { _ = await today.quickAdd(categoryID: 1) }
        XCTAssertEqual(values(today), Array(repeating: "10", count: 5), "all five are on screen before any answer")
        await waitUntil { queue.writes.isEmpty }

        XCTAssertEqual(sender.sent.count, 5)
        XCTAssertEqual(Set(sender.sent.map(\.key)).count, 5)
        XCTAssertEqual(values(today), Array(repeating: "10", count: 5), "and the server's five rows replace them")
        XCTAssertTrue(today.entries(forCategory: 1).allSatisfy { !$0.isPending })
    }

    func testFourQuickPressesOfAButtonAreFourSteps() async {
        let sender = HeldSender()
        sender.holds = true
        let (buttons, queue, _) = await makeButtons(total: 0, sender: sender)

        for _ in 0..<4 { await buttons.tap(buttons.marks[0]) }
        XCTAssertEqual(buttons.marks[0].todayTotal, 4)
        await waitUntil { sender.heldCount == 1 }
        sender.release()
        await waitUntil { queue.writes.isEmpty }

        XCTAssertEqual(sender.taps(of: 1).count, 4)
        XCTAssertEqual(Set(sender.taps(of: 1).map(\.key)).count, 4)
        XCTAssertEqual(buttons.marks[0].todayTotal, 4, "the server's sum matches the screen")
        XCTAssertEqual(sender.tapTotals[1], 4)
    }

    func testTwoTapsOfOneTickAreOneWriteOfTheDay() async {
        let sender = HeldSender()
        let (today, queue, _) = await makeToday(categories: [morning], sender: sender)

        let first = await today.quickAdd(categoryID: 2)
        let second = await today.quickAdd(categoryID: 2)
        await waitUntil { queue.writes.isEmpty }

        XCTAssertTrue(first)
        XCTAssertFalse(second)
        XCTAssertEqual(sender.sent.count, 1)
        XCTAssertTrue(today.isTicked(categoryID: 2))
    }

    // MARK: 4. One key across the retries of one write

    func testTheKeyOfAPressDoesNotChangeBetweenRetries() async {
        let sender = HeldSender()
        sender.failures = [APIClientError.timeout, APIClientError.unexpectedStatus(503)]
        let (today, queue, _) = await makeToday(categories: [pushups], sender: sender)

        _ = await today.quickAdd(categoryID: 1)
        await waitForSend(queue)
        await queue.flush()
        await queue.flush()

        XCTAssertEqual(sender.sent.count, 3)
        XCTAssertEqual(Set(sender.sent.map(\.key)).count, 1, "a send cut mid-way and its repeats are one write")
        XCTAssertTrue(queue.writes.isEmpty)
    }

    // MARK: 5. Undo of a press not sent yet

    func testUndoOfAPressNotSentYetSendsNothing() async {
        let sender = HeldSender()
        let (buttons, queue, api) = await makeButtons(total: 2, sender: sender)

        await buttons.tap(buttons.marks[0])
        await buttons.undoLast()
        for _ in 0..<10 { await Task.yield() }

        XCTAssertTrue(sender.sent.isEmpty, "the press never left the phone")
        XCTAssertTrue(api.undoneIDs.isEmpty, "and there is nothing to undo on the server")
        XCTAssertTrue(queue.writes.isEmpty)
        XCTAssertEqual(buttons.marks[0].todayTotal, 2)
        XCTAssertNil(buttons.undoCaption)
    }

    func testUndoOfAPressWaitingForTheNetworkSendsNothing() async {
        let sender = HeldSender()
        sender.failures = [APIClientError.transport(code: URLError.notConnectedToInternet.rawValue)]
        let (buttons, queue, api) = await makeButtons(total: 2, sender: sender)
        await buttons.tap(buttons.marks[0])
        await waitForSend(queue)

        await buttons.undoLast()
        await queue.flush()

        XCTAssertEqual(sender.sent.count, 1, "only the attempt that failed")
        XCTAssertTrue(api.undoneIDs.isEmpty)
        XCTAssertTrue(queue.writes.isEmpty)
        XCTAssertEqual(buttons.marks[0].todayTotal, 2)
    }

    // MARK: 6. Day: a second mark during the first PUT

    func testASecondMarkDuringTheFirstPutIsNotLost() async throws {
        let sender = HeldSender()
        sender.holds = true
        let api = MockDayAPI()
        api.fetchResults = [.success(try DayFixtures.day())]
        let queue = makeQueue(sender)
        let viewModel = DayViewModel(
            apiProvider: { api }, timeZoneProvider: { [utc] in utc }, outbox: queue, now: { [clock] in clock }
        )
        await viewModel.load()
        let item = DayFixtures.minimumID

        await viewModel.cycleMark(item)
        await waitUntil { sender.heldCount == 1 }
        XCTAssertFalse(viewModel.busyItems.contains(item), "the line is free while the PUT is on its way")
        await viewModel.cycleMark(item)
        let second = DayFormat.nextMark(after: "done")
        XCTAssertEqual(viewModel.state(of: item), second, "the second tap is on screen at once")
        // From here the server holds the second mark: the re-read after a delivery reads it back.
        api.fetchResults = [.success(try DayFixtures.day(marks: [DayFixtures.mark(item, second)]))]
        sender.release()
        await waitUntil { queue.writes.isEmpty }

        let states = sender.sent.compactMap { sent -> String?? in
            if case .setDayMark(let mark) = sent.action { return .some(mark.state) } else { return nil }
        }
        XCTAssertEqual(states, ["done", second], "both reach the server, in the order they were made")
        XCTAssertEqual(viewModel.state(of: item), second)
    }

    // MARK: Round 2 — a read on its way when a press is delivered

    func testTodayShowsAReadOnItsWayWithTheDeliveredEntryLaidOverIt() async {
        let sender = HeldSender()
        let cache = InMemoryCacheStore()
        let (today, queue, api) = await makeToday(categories: [pushups], sender: sender, cache: cache)
        let web = EntryDTO(id: 77, categoryId: 1, entryDate: self.today, values: [EntryValueDTO(fieldId: 10, value: "5")])
        // The re-read leaves before the press is delivered and answers with the day as it was then: the web's row only.
        api.entriesResult = .success([web])
        api.duringFetchEntries = { await waitUntil { sender.sent.count == 1 && queue.writes.isEmpty } }
        let readsBefore = api.fetchedEntryRanges.count

        let loading = Task { await today.load() }
        await waitUntil { api.fetchedEntryRanges.count > readsBefore }
        _ = await today.quickAdd(categoryID: 1)
        await loading.value

        let shown = today.entries(forCategory: 1).map(\.id).sorted()
        XCTAssertEqual(shown, [77, 1001], "the web's row and the delivered one")
        XCTAssertEqual(
            cache.load(TodaySnapshot.self, forKey: TodayViewModel.cacheKey)?.value.entries.map(\.id).sorted(), shown,
            "the cache holds what the screen shows"
        )
    }

    func testButtonsShowAReadOnItsWayWithTheDeliveredPressLaidOverIt() async {
        let sender = HeldSender()
        let cache = InMemoryCacheStore()
        let (buttons, queue, api) = await makeButtons(total: 0, sender: sender, others: [button(id: 2, total: 0)], cache: cache)
        // Read before the press landed: button 1 still 0, button 2 moved to 3 on the web.
        api.marksResult = .success([button(total: 0), button(id: 2, total: 3)])
        api.duringFetch = { await waitUntil { sender.sent.count == 1 && queue.writes.isEmpty } }
        let readsBefore = api.directoryFetches

        let loading = Task { await buttons.load() }
        await waitUntil { api.directoryFetches > readsBefore }
        await buttons.tap(buttons.marks[0])
        await loading.value

        XCTAssertEqual(buttons.marks.map(\.todayTotal), [1, 3])
        XCTAssertEqual(
            cache.load([QuickMarkDTO].self, forKey: QuickMarksViewModel.cacheKey)?.value.map(\.todayTotal), [1, 3],
            "the cache holds what the buttons show"
        )
    }

    func testSupplementsShowAReadOnItsWayWithTheDeliveredIntakeLaidOverIt() async {
        let sender = HeldSender()
        let cache = InMemoryCacheStore()
        let api = MockSupplementsAPI()
        api.listResult = .success([.stub(id: 1), .stub(id: 2)])
        let queue = makeQueue(sender)
        let model = SupplementsViewModel(
            api: api, cacheStore: cache, outbox: queue, rule: ServerDayRule(timeZoneID: "UTC", dayStartHour: 4),
            now: { [clock] in clock }
        )
        await model.load()
        // Read before the press landed: the web marked the second one.
        api.listResult = .success([.stub(id: 1), .stub(id: 2, taken: true)])
        api.holdNextList = true

        let loading = Task { await model.load() }
        await waitUntil { api.isHoldingList }
        await model.markTaken(model.rows[0].supplement)
        await waitUntil { queue.writes.isEmpty }
        api.releaseList()
        await loading.value

        XCTAssertEqual(model.rows.map(\.isTaken), [true, true])
        XCTAssertEqual(
            cache.load(SupplementsViewModel.Snapshot.self, forKey: SupplementsViewModel.cacheKey)?.value.items.map(\.takenToday),
            [true, true], "the cache holds what the list shows"
        )
    }

    func testDayAReReadStartedBeforeTheSecondMarkLandedDoesNotRollTheTickBack() async throws {
        let sender = HeldSender()
        let api = MockDayAPI()
        api.fetchResults = [.success(try DayFixtures.day())]
        let queue = makeQueue(sender)
        let viewModel = DayViewModel(
            apiProvider: { api }, timeZoneProvider: { [utc] in utc }, outbox: queue, now: { [clock] in clock }
        )
        await viewModel.load()
        let item = DayFixtures.minimumID
        let first = try DayFixtures.day(marks: [DayFixtures.mark(item, "done")])
        let second = try DayFixtures.day(marks: [DayFixtures.mark(item, "failed")])
        // The re-read after the first mark waits until the second has landed, then answers with the first.
        api.duringFetch = {
            await waitUntil { sender.sent.count == 2 && queue.writes.isEmpty }
            api.fetchResults = [.success(first), .success(second)]
            // The next re-read takes a round trip too: a frame fits between the two answers.
            api.duringFetch = { for _ in 0..<5 { await Task.yield() } }
        }
        let readsBefore = api.fetchedDates.count

        await viewModel.cycleMark(item)
        await waitUntil { api.fetchedDates.count > readsBefore }
        await viewModel.cycleMark(item)
        // What a frame could see: the state between turns of the main actor, until both re-reads answered.
        var seen: [String?] = []
        var turnsAfter = 0
        for _ in 0..<2000 where turnsAfter < 20 {
            seen.append(viewModel.state(of: item))
            if api.fetchedDates.count >= readsBefore + 2 { turnsAfter += 1 }
            await Task.yield()
        }

        XCTAssertEqual(viewModel.state(of: item), "failed")
        XCTAssertFalse(seen.contains("done"), "the older answer would blink the first tick back")
    }

    // MARK: Round 2 — undo during the send

    func testUndoDuringTheSendIsOneUndoOfItsOwnEventOnceItLands() async {
        let sender = HeldSender()
        sender.holds = true
        let (buttons, queue, api) = await makeButtons(total: 2, sender: sender)
        api.undoResult = .success(
            QuickMarkUndoDTO(eventId: 1, quickMarkId: 1, entryDate: today, undoneAt: "2026-10-25T09:01:00+00:00", todayTotal: 2, done: true)
        )

        await buttons.tap(buttons.marks[0])
        await waitUntil { sender.heldCount == 1 }
        await buttons.undoLast()
        sender.release()
        await waitUntil { queue.writes.isEmpty && api.undoneIDs.count == 1 }
        for _ in 0..<10 { await Task.yield() }

        XCTAssertEqual(api.undoneIDs, [1], "exactly one undo, of the event the press got")
        XCTAssertEqual(buttons.marks[0].todayTotal, 2)
    }

    func testUndoDuringASendThatFailsWithdrawsThePress() async {
        let sender = HeldSender()
        sender.holds = true
        sender.failures = [APIClientError.transport(code: URLError.networkConnectionLost.rawValue)]
        let (buttons, queue, api) = await makeButtons(total: 2, sender: sender)

        await buttons.tap(buttons.marks[0])
        await waitUntil { sender.heldCount == 1 }
        await buttons.undoLast()
        sender.release()
        await waitUntil { queue.writes.isEmpty }
        await queue.flush()

        XCTAssertEqual(sender.sent.count, 1, "the press is not sent again after the failed attempt")
        XCTAssertTrue(api.undoneIDs.isEmpty)
        XCTAssertEqual(buttons.marks[0].todayTotal, 2)
    }

    // MARK: Round 2 — checklist

    func testARefusedChecklistSaveGivesTheServersRowBack() async {
        let sender = HeldSender()
        sender.failures = [APIClientError.unexpectedStatus(422)]
        let server = EntryDTO(id: 200, categoryId: 2, entryDate: today, values: [EntryValueDTO(fieldId: 20, value: "false")])
        let (today, queue, _) = await makeToday(categories: [morning], sender: sender, entries: [server])

        _ = await today.saveEntry(categoryID: 2, values: [20: "true"])
        await waitForSend(queue)

        XCTAssertEqual(today.entries(forCategory: 2), [server], "the server's row is back, not an empty day")
        XCTAssertEqual(queue.failedCount, 1)
    }

    func testANewerChecklistSaveReplacesTheWaitingOneButNotTheOneBeingSent() async {
        let sender = HeldSender()
        sender.holds = true
        let (today, queue, _) = await makeToday(categories: [morning], sender: sender)

        _ = await today.saveEntry(categoryID: 2, values: [20: "true"])
        await waitUntil { sender.heldCount == 1 }
        _ = await today.saveEntry(categoryID: 2, values: [20: "true"])
        _ = await today.saveEntry(categoryID: 2, values: [20: "false"])
        XCTAssertEqual(queue.pendingCount, 2, "the one being sent and one waiting: the newer replaced the older waiting one")
        XCTAssertEqual(today.entries(forCategory: 2).count, 1, "one row of the day")
        sender.release()
        await waitUntil { queue.writes.isEmpty }

        let sent = sender.sent.compactMap { sent -> [String: Bool]? in
            if case .upsertChecklist(let list) = sent.action { return list.values } else { return nil }
        }
        XCTAssertEqual(sent, [["20": true], ["20": false]])
        XCTAssertEqual(today.entries(forCategory: 2).first?.values, [EntryValueDTO(fieldId: 20, value: "false")])
    }

    // MARK: Round 3 — a mark that waited is checked against the day

    private func markQueue(server: FakeOutboxServer, now: @escaping () -> Date) -> OutboxQueue {
        OutboxQueue(
            store: InMemoryOutboxStore(), now: now, sender: { OutboxReplay(entries: server, quickMarks: server, day: server) }
        )
    }

    private func mark(_ item: UUID, _ state: String) -> OutboxAction {
        .setDayMark(QueuedDayMark(date: today, itemID: item, state: state, note: nil, expected: ""))
    }

    func testAMarkQueuedBehindAWriteThatFailedIsCheckedAgainstTheDayBeforeItsPut() async {
        let server = FakeOutboxServer()
        var moment = clock
        let queue = markQueue(server: server, now: { moment })
        let item = UUID()
        queue.enqueue(.createEntry(EntryCreateDTO(categoryId: 1, entryDate: today, notes: nil, values: [])), label: "Pushups")
        queue.enqueue(mark(item, "done"), label: "Отметка", uncheckedFirstAttempt: true)
        server.failures = [APIClientError.transport(code: URLError.notConnectedToInternet.rawValue)]
        await queue.flush()
        XCTAssertEqual(queue.pendingCount, 2, "the dead network stopped the flush before the mark")
        // Meanwhile the web moved the mark; the network comes back within the quiet period of the tap.
        server.marks[today] = [item: "failed"]
        moment = clock.addingTimeInterval(1)

        await queue.flush()

        XCTAssertEqual(server.unopenedFetches, [today], "the day is read before the PUT")
        XCTAssertEqual(server.marks[today]?[item], "failed", "the web's mark is not overwritten")
        XCTAssertEqual(queue.failed.first?.failure, OutboxQueue.markChangedReason)
    }

    func testAMarkReplacingAnUnsentOneThatLeavesAfterTheQuietPeriodIsChecked() async {
        let server = FakeOutboxServer()
        var moment = clock
        let queue = markQueue(server: server, now: { moment })
        let item = UUID()
        queue.enqueue(mark(item, "done"), label: "Отметка", uncheckedFirstAttempt: true)
        queue.enqueue(mark(item, "failed"), label: "Отметка", uncheckedFirstAttempt: true)
        XCTAssertEqual(queue.pendingCount, 1, "the second tap replaced the first, which never left")
        server.marks[today] = [item: "skipped"]
        moment = clock.addingTimeInterval(OutboxQueue.quietPeriod)

        await queue.flush()

        XCTAssertEqual(server.unopenedFetches, [today], "a mark that waited past the quiet period reads the day first")
        XCTAssertEqual(server.marks[today]?[item], "skipped")
        XCTAssertEqual(queue.failed.first?.failure, OutboxQueue.markChangedReason)
    }

    func testAMarkSentRightAfterTheTapIsOneBarePut() async {
        let server = FakeOutboxServer()
        let queue = markQueue(server: server, now: { [clock] in clock })
        let item = UUID()
        queue.enqueue(mark(item, "done"), label: "Отметка", uncheckedFirstAttempt: true)

        await queue.flush()

        XCTAssertTrue(server.unopenedFetches.isEmpty)
        XCTAssertEqual(server.marks[today]?[item], "done")
    }
}
