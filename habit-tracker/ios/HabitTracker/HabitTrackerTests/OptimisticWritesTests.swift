// [review:need-review] PHASE-03/316
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
        case .recordPlanFact, .saveNotebook, .markSupplementTaken:
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

    private func button(total: Double) -> QuickMarkDTO {
        QuickMarkDTO(
            id: 1, label: "Water", categoryId: 1, fieldId: 11, kind: "increment",
            step: 1, unitLabel: nil, icon: nil, color: nil, hotkey: nil, order: 1,
            showInAgent: true, isActive: true, entryDate: today, todayTotal: total,
            done: total != 0, planned: false, planItemId: nil
        )
    }

    private func makeQueue(_ sender: HeldSender) -> OutboxQueue {
        OutboxQueue(store: InMemoryOutboxStore(), now: { [clock] in clock }, sender: { sender })
    }

    private func makeToday(categories: [CategoryDTO], sender: HeldSender) async -> (TodayViewModel, OutboxQueue, MockTodayAPI) {
        let api = MockTodayAPI()
        api.categoriesResult = .success(categories)
        let queue = makeQueue(sender)
        let viewModel = TodayViewModel(api: api, outbox: queue, timeZone: utc, now: { [clock] in clock })
        await viewModel.load()
        return (viewModel, queue, api)
    }

    private func makeButtons(total: Double, sender: HeldSender) async -> (QuickMarksViewModel, OutboxQueue, MockQuickMarksAPI) {
        let api = MockQuickMarksAPI()
        api.marksResult = .success([button(total: total)])
        sender.tapTotals[1] = total
        let queue = makeQueue(sender)
        let viewModel = QuickMarksViewModel(api: api, outbox: queue, timeZone: utc, now: { [clock] in clock })
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
}
