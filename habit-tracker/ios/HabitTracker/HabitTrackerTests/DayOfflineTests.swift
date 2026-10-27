// [review:need-review] PHASE-03/225
// summary: the Day screen without a network — a mark, a new fact and the notebook go to the shared outbox (the fact under the key of its attempt, the mark and notebook with the server state they were made over) and stay on screen through a re-read; a delivery reads the day again; the day opens from the read cache; closing and fact corrections say they need the server and keep what was typed
import XCTest
@testable import HabitTracker

extension MockDayAPI: OutboxDayAPI {
    func fetchDayUnopened(date: String) async throws -> DayDetailDTO {
        try await fetchDay(date: date)
    }
}

@MainActor
final class DayOfflineTests: XCTestCase {
    private let offline = APIClientError.transport(code: URLError.notConnectedToInternet.rawValue)
    private var api: MockDayAPI!
    private var outbox: OutboxQueue!
    private var cache: InMemoryCacheStore!
    private var viewModel: DayViewModel!

    override func setUp() async throws {
        api = MockDayAPI()
        api.fetchResults = [.success(try DayFixtures.day())]
        let day: MockDayAPI = api
        let server = FakeOutboxServer()
        outbox = OutboxQueue(
            store: InMemoryOutboxStore(),
            sender: { OutboxReplay(entries: server, quickMarks: server, day: day) }
        )
        cache = InMemoryCacheStore()
        viewModel = makeViewModel()
        await viewModel.load()
    }

    private func makeViewModel() -> DayViewModel {
        let day: MockDayAPI = api
        return DayViewModel(apiProvider: { day }, outbox: outbox, cacheStore: cache)
    }

    // MARK: Marks

    func testAnOfflineMarkStaysOnScreenAndWaitsInTheQueue() async {
        api.markResult = .failure(offline)

        await viewModel.cycleMark(DayFixtures.minimumID)

        XCTAssertNil(viewModel.actionError, "an offline mark is deferred, not failed")
        XCTAssertEqual(viewModel.state(of: DayFixtures.minimumID), "done")
        XCTAssertEqual(viewModel.queuedItems, [DayFixtures.minimumID])
        XCTAssertEqual(
            outbox.pending.first?.action,
            .setDayMark(
                QueuedDayMark(date: DayFixtures.date, itemID: DayFixtures.minimumID, state: "done", note: nil, expected: "")
            )
        )
        XCTAssertEqual(outbox.pending.first?.label, "Отметка «Минимум: собрать сборку»")
    }

    func testAQueuedMarkIsNotRolledBackByAReread() async {
        api.markResult = .failure(offline)
        await viewModel.cycleMark(DayFixtures.minimumID)

        await viewModel.rereadInPlace()

        XCTAssertEqual(viewModel.state(of: DayFixtures.minimumID), "done", "the server does not have it yet")
    }

    func testADeliveredMarkReadsTheDayAgainAndLosesItsQueuedSign() async throws {
        api.markResult = .failure(offline)
        await viewModel.cycleMark(DayFixtures.minimumID)
        api.markResult = .success(DayFixtures.mark(DayFixtures.minimumID, "done"))
        api.fetchResults = [.success(try DayFixtures.day(marks: [DayFixtures.mark(DayFixtures.minimumID, "done")]))]
        let readsBefore = api.fetchedDates.count

        await outbox.flush()
        for _ in 0..<100 where api.fetchedDates.count < readsBefore + 2 {
            try await Task.sleep(nanoseconds: 10_000_000)
        }

        XCTAssertEqual(api.markCalls.last?.body.state, "done")
        XCTAssertTrue(viewModel.queuedItems.isEmpty)
        XCTAssertEqual(api.fetchedDates.count, readsBefore + 2, "one read for the replay check, one for the screen")
        XCTAssertEqual(viewModel.state(of: DayFixtures.minimumID), "done")
    }

    // MARK: Facts

    func testAnOfflineFactIsQueuedUnderTheKeyOfItsAttempt() async {
        api.factResult = .failure(offline)

        let cleared = await viewModel.saveFact(DayFixtures.pushupsID, input: .text("30"))

        XCTAssertTrue(cleared, "the input clears: the fact is kept")
        XCTAssertNil(viewModel.actionError)
        XCTAssertEqual(outbox.pending.first?.key, api.recordCalls.first?.key)
        XCTAssertEqual(viewModel.queuedItems, [DayFixtures.pushupsID])
        guard case .recordPlanFact(let fact)? = outbox.pending.first?.action else { return XCTFail("no fact queued") }
        XCTAssertEqual(fact.date, DayFixtures.date)
        XCTAssertEqual(fact.body, api.recordCalls.first?.body)
    }

    func testCorrectingAFactWithoutANetworkSaysItNeedsTheServer() async {
        api.factResult = .failure(offline)

        let cleared = await viewModel.saveFact(DayFixtures.pushupsID, input: .text("120"), correcting: 501)

        XCTAssertFalse(cleared)
        XCTAssertEqual(viewModel.actionError, DayViewModel.factNeedsServerMessage)
        XCTAssertEqual(outbox.pendingCount, 0)
    }

    // MARK: Notebook

    func testAnOfflineNotebookSaveIsKeptAsSavedWithTheTextItWasTypedOver() async {
        api.notebookError = offline
        viewModel.notebook = "Заметка дня и вечер"

        await viewModel.saveNotebook()

        XCTAssertNil(viewModel.actionError)
        XCTAssertFalse(viewModel.isNotebookDirty)
        XCTAssertTrue(viewModel.isNotebookQueued)
        XCTAssertEqual(
            outbox.pending.first?.action,
            .saveNotebook(QueuedNotebook(date: DayFixtures.date, content: "Заметка дня и вечер", expected: "Заметка дня"))
        )
    }

    func testAQueuedNotebookIsShownOverTheServerTextWithoutAConflict() async {
        api.notebookError = offline
        viewModel.notebook = "Заметка дня и вечер"
        await viewModel.saveNotebook()

        await viewModel.rereadInPlace()

        XCTAssertEqual(viewModel.notebook, "Заметка дня и вечер")
        XCTAssertFalse(viewModel.isNotebookDirty)
        XCTAssertNil(viewModel.notebookConflict)
    }

    // MARK: Reading and closing

    func testTheDayOpensFromTheCacheWithoutANetwork() async {
        api.fetchResults = [.failure(offline)]
        let reopened = makeViewModel()

        await reopened.load()

        XCTAssertEqual(reopened.state, .loaded)
        XCTAssertEqual(reopened.shownDate, DayFixtures.date)
        XCTAssertNotNil(reopened.offlineAsOf)
        XCTAssertNil(viewModel.offlineAsOf)
    }

    func testClosingWithoutANetworkSaysItNeedsTheServerAndKeepsTheFields() async {
        api.closingResult = .failure(offline)
        viewModel.closingBody = "итог дня"

        await viewModel.closeDay()

        XCTAssertEqual(viewModel.actionError, DayViewModel.closingNeedsServerMessage)
        XCTAssertEqual(viewModel.closingBody, "итог дня")
        XCTAssertEqual(outbox.pendingCount, 0)
    }
}
