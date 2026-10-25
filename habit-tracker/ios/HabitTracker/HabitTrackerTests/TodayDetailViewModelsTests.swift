// [review:need-review] PHASE-01/210
// summary: tests for the two detail view models behind Today — the relapse history screen (server day, period, analysis) and the list of a category's sets of the day (rows from the journal, undo through the screen that owns the totals, a refusal shown in the list)
import XCTest
@testable import HabitTracker

final class MockRelapseHistoryAPI: RelapseHistoryAPI {
    var result: Result<RelapseHistoryDTO, Error> = .failure(APIClientError.invalidResponse)
    private(set) var requestedCategoryIDs: [Int] = []

    func fetchRelapseHistory(categoryId: Int) async throws -> RelapseHistoryDTO {
        requestedCategoryIDs.append(categoryId)
        return try result.get()
    }
}

@MainActor
final class RelapseHistoryViewModelTests: XCTestCase {
    private let history = RelapseHistoryDTO(
        categoryId: 1, streakMode: "avoid", currentStreak: 4, bestStreak: 9,
        lastRelapseDate: "2026-10-21", trackedSince: "2026-08-01",
        relapseDates: ["2026-09-01", "2026-10-01", "2026-10-21"], today: "2026-10-25"
    )

    func testLoadAnalysesFromTheServersTodayNotTheDevicesClock() async {
        let api = MockRelapseHistoryAPI()
        api.result = .success(history)
        let viewModel = RelapseHistoryViewModel(categoryId: 1, apiProvider: { api })

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(api.requestedCategoryIDs, [1])
        XCTAssertEqual(viewModel.summary?.lastWeek, 1)
        XCTAssertEqual(viewModel.summary?.lastMonth, 2)
        XCTAssertEqual(viewModel.timeline?.buckets.last?.end, "2026-10-25")
    }

    func testChangingThePeriodRedrawsTheChartWithoutAnotherRequest() async {
        let api = MockRelapseHistoryAPI()
        api.result = .success(history)
        let viewModel = RelapseHistoryViewModel(categoryId: 1, apiProvider: { api })
        await viewModel.load()
        XCTAssertEqual(viewModel.timeline?.buckets.count, 30)

        viewModel.period = .days90

        XCTAssertEqual(viewModel.timeline?.buckets.count, 90)
        XCTAssertEqual(viewModel.timeline?.granularity, .day)
        XCTAssertEqual(api.requestedCategoryIDs.count, 1)
    }

    func testTheLatestRelapseDaysComeNewestFirstCappedAtTen() async {
        let api = MockRelapseHistoryAPI()
        let days = (1...12).map { String(format: "2026-09-%02d", $0) }
        api.result = .success(
            RelapseHistoryDTO(
                categoryId: 1, streakMode: "avoid", currentStreak: 0, bestStreak: 0,
                lastRelapseDate: "2026-09-12", trackedSince: "2026-08-01", relapseDates: days,
                today: "2026-10-25"
            )
        )
        let viewModel = RelapseHistoryViewModel(categoryId: 1, apiProvider: { api })
        await viewModel.load()

        XCTAssertEqual(viewModel.recentDays.count, RelapseHistoryViewModel.recentDaysShown)
        XCTAssertEqual(viewModel.recentDays.first, "2026-09-12")
        XCTAssertEqual(viewModel.recentDays.last, "2026-09-03")
    }

    func testFailureAndMissingServerAreShownNotHidden() async {
        let api = MockRelapseHistoryAPI()
        api.result = .failure(APIClientError.unexpectedStatus(404))
        let failing = RelapseHistoryViewModel(categoryId: 1, apiProvider: { api })
        await failing.load()
        guard case .failure(let message) = failing.state else {
            return XCTFail("expected a failure, got \(failing.state)")
        }
        XCTAssertFalse(message.isEmpty)

        let unconfigured = RelapseHistoryViewModel(categoryId: 1, apiProvider: { nil })
        await unconfigured.load()
        XCTAssertEqual(unconfigured.state, .failure(TodayViewModel.notConfiguredMessage))
    }
}

@MainActor
final class QuickMarkDaySetsViewModelTests: XCTestCase {
    private func event(id: Int, undoable: Bool, undone: Bool = false) -> QuickMarkDayEventDTO {
        QuickMarkDayEventDTO(
            eventId: id, quickMarkId: 1, label: "Вода", kind: "increment", unitLabel: "л",
            entryDate: "2026-10-25", occurredAt: "2026-10-25T09:00:00+00:00", delta: 0.25,
            boolValue: nil, undoneAt: undone ? "2026-10-25T09:05:00+00:00" : nil,
            undoable: undoable
        )
    }

    func testLoadReadsTheSetsOfTheCategoryInTheOrderOfThePresses() async {
        let api = MockQuickMarksAPI()
        api.dayEventsResult = .success([event(id: 1, undoable: false), event(id: 2, undoable: true)])
        let viewModel = QuickMarkDaySetsViewModel(
            categoryId: 7, apiProvider: { api }, undo: { _ in nil }
        )

        await viewModel.load()

        XCTAssertEqual(api.fetchedDayEventCategories, [7])
        XCTAssertEqual(viewModel.events.map(\.eventId), [1, 2])
        XCTAssertEqual(viewModel.state, .loaded)
    }

    func testUndoGoesThroughTheScreenThatOwnsTheTotalsThenReadsTheListAgain() async {
        let api = MockQuickMarksAPI()
        api.dayEventsResult = .success([event(id: 2, undoable: true)])
        var undone: [Int] = []
        let viewModel = QuickMarkDaySetsViewModel(
            categoryId: 7, apiProvider: { api }, undo: { undone.append($0); return nil }
        )
        await viewModel.load()
        api.dayEventsResult = .success([event(id: 2, undoable: false, undone: true)])

        await viewModel.undo(eventID: 2)

        XCTAssertEqual(undone, [2])
        XCTAssertNil(viewModel.refusal)
        XCTAssertEqual(api.fetchedDayEventCategories.count, 2)
        XCTAssertNotNil(viewModel.events.first?.undoneAt, "a taken-back set stays in the list")
    }

    func testARefusalIsShownInTheListAndTheRowsAreReadAgainAsTheExplanation() async {
        let api = MockQuickMarksAPI()
        api.dayEventsResult = .success([event(id: 2, undoable: true)])
        let viewModel = QuickMarkDaySetsViewModel(
            categoryId: 7, apiProvider: { api }, undo: { _ in "Значение правили руками" }
        )
        await viewModel.load()

        await viewModel.undo(eventID: 2)

        XCTAssertEqual(viewModel.refusal, "Значение правили руками")
        XCTAssertEqual(api.fetchedDayEventCategories.count, 2)
    }

    func testRowWordingSignsANumberAndNamesATick() {
        XCTAssertEqual(event(id: 1, undoable: true).amountText, "+0.25 л")
        let tick = QuickMarkDayEventDTO(
            eventId: 3, quickMarkId: 1, label: "Зарядка", kind: "check", unitLabel: nil,
            entryDate: "2026-10-25", occurredAt: "2026-10-25T09:00:00+00:00", delta: nil,
            boolValue: false, undoneAt: nil, undoable: false
        )
        XCTAssertEqual(tick.amountText, "Снято")
    }
}
