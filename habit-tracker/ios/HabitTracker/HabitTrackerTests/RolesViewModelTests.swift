// [review:need-review] PHASE-01/266
// summary: tests of the Roles and markup-rules view models — the day and the summary through the cache (fresh, offline with the cached answer, nothing to show, a failed summary leaves the day), the period switch asking the right bounds, the writes (minutes validated, act trimmed, confirm, remove) that re-read the day and say so when the network is out, the rule draft with its dry run, the switch of a rule and the re-markup of a period
import XCTest
@testable import HabitTracker

@MainActor
final class RolesViewModelTests: XCTestCase {
    private let moment = Date(timeIntervalSince1970: 1_800_000_000)
    private let offline = APIClientError.transport(code: NSURLErrorNotConnectedToInternet)

    private func makeDay(_ api: MockRolesAPI, store: CacheStore = InMemoryCacheStore()) -> RolesViewModel {
        RolesViewModel(apiProvider: { api }, cacheStore: store, now: { self.moment })
    }

    private func makeRules(_ api: MockRolesAPI, store: CacheStore = InMemoryCacheStore()) -> RoleRulesViewModel {
        RoleRulesViewModel(apiProvider: { api }, cacheStore: store, now: { self.moment })
    }

    // MARK: Day

    func testLoadShowsTheDayTheDirectoryAndTheWeekSummary() async throws {
        let api = MockRolesAPI()
        let viewModel = makeDay(api)

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.day?.workDay, "2026-08-27")
        XCTAssertEqual(viewModel.roles.count, 2)
        XCTAssertEqual(viewModel.summary?.totalMinutes, 600)
        XCTAssertNil(viewModel.offlineAsOf)
        XCTAssertEqual(api.summaryRequests.first?.0, "2026-08-21")
        XCTAssertEqual(api.summaryRequests.first?.1, "2026-08-27")
    }

    func testPeriodSwitchAsksTheBoundsOfThatPeriodAndSkipsARepeat() async {
        let api = MockRolesAPI()
        let viewModel = makeDay(api)
        await viewModel.load()

        await viewModel.select(period: .month)
        await viewModel.select(period: .month)

        XCTAssertEqual(viewModel.period, .month)
        XCTAssertEqual(api.summaryRequests.count, 2)
        XCTAssertEqual(api.summaryRequests.last?.0, "2026-07-29")
    }

    func testFailedSummaryLeavesTheDay() async {
        let api = MockRolesAPI()
        api.summary = { _, _ in throw APIClientError.unexpectedStatus(500) }
        let viewModel = makeDay(api)

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertNil(viewModel.summary)
    }

    func testOfflineServesTheCachedDayWithItsMoment() async {
        let store = InMemoryCacheStore()
        await makeDay(MockRolesAPI(), store: store).load()
        let api = MockRolesAPI()
        api.day = { throw self.offline }
        let viewModel = makeDay(api, store: store)

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.offlineAsOf, moment)
        XCTAssertEqual(viewModel.day?.totalMinutes, 150)
    }

    func testNothingCachedAndNoNetworkIsAnErrorWithWords() async {
        let api = MockRolesAPI()
        api.day = { throw self.offline }
        let viewModel = makeDay(api)

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .failure("Нет связи с сервером"))
    }

    func testNotConfiguredSaysSo() async {
        let viewModel = RolesViewModel(apiProvider: { nil })

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .failure(RolesFormat.notConfiguredMessage))
    }

    // MARK: Writes

    func testMinutesMustBePositiveAndNothingIsSentOtherwise() async {
        let api = MockRolesAPI()
        let viewModel = makeDay(api)
        await viewModel.load()

        let saved = await viewModel.addMinutes(roleCode: "cto", minutes: 0, note: "")

        XCTAssertFalse(saved)
        XCTAssertTrue(api.timeBlockDrafts.isEmpty)
        XCTAssertEqual(viewModel.errorMessage, "Минут должно быть больше нуля")
    }

    func testMinutesGoOutForTheServerDayWithATrimmedNoteAndTheDayIsReread() async {
        let api = MockRolesAPI()
        var dayReads = 0
        api.day = { dayReads += 1; return try RolesFixtures.day() }
        let viewModel = makeDay(api)
        await viewModel.load()

        let saved = await viewModel.addMinutes(roleCode: "cto", minutes: 90, note: "  найм ")

        XCTAssertTrue(saved)
        XCTAssertEqual(api.timeBlockDrafts, [
            RoleTimeBlockDraftDTO(roleCode: "cto", minutes: 90, workDay: "2026-08-27", note: "найм")
        ])
        XCTAssertEqual(dayReads, 2)
    }

    func testEmptyActTitleIsNotSentAndATitleIsTrimmed() async {
        let api = MockRolesAPI()
        let viewModel = makeDay(api)
        await viewModel.load()

        let empty = await viewModel.addAct(roleCode: "cto", actKind: "adr_written", title: "  ")
        let filled = await viewModel.addAct(roleCode: "cto", actKind: "adr_written", title: " ADR-1 ")

        XCTAssertFalse(empty)
        XCTAssertTrue(filled)
        XCTAssertEqual(api.actDrafts.map(\.title), ["ADR-1"])
    }

    func testConfirmAndRemoveGoByBlockId() async {
        let api = MockRolesAPI()
        let viewModel = makeDay(api)
        await viewModel.load()

        await viewModel.confirmBlock(id: 12)
        await viewModel.removeBlock(id: 11)

        XCTAssertEqual(api.confirmed, [12])
        XCTAssertEqual(api.deleted, [11])
    }

    func testWriteWithoutNetworkSaysItAndKeepsTheScreen() async {
        let api = MockRolesAPI()
        let viewModel = makeDay(api)
        await viewModel.load()
        api.write = { throw self.offline }

        let saved = await viewModel.addMinutes(roleCode: "cto", minutes: 30, note: "")

        XCTAssertFalse(saved)
        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.errorMessage, "Нет связи: запись ролей уходит только при сети, повторите позже")
        XCTAssertFalse(viewModel.isSaving)
    }

    // MARK: Rules

    func testRulesLoadWithDirectoryAndServerDayAndPickFirstRole() async {
        let api = MockRolesAPI()
        let viewModel = makeRules(api)

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.rules.map(\.id), [5, 6])
        XCTAssertEqual(viewModel.today, "2026-08-27")
        XCTAssertEqual(viewModel.draft.roleCode, "cto")
    }

    func testDryRunNeedsAPatternAndSavesNothing() async {
        let api = MockRolesAPI()
        let viewModel = makeRules(api)
        await viewModel.load()

        await viewModel.runDryRun()
        XCTAssertTrue(api.dryRunDrafts.isEmpty)

        viewModel.draft.pattern = " feat( "
        await viewModel.runDryRun()

        XCTAssertEqual(api.dryRunDrafts.map(\.pattern), ["feat("])
        XCTAssertTrue(api.ruleDrafts.isEmpty)
        XCTAssertEqual(viewModel.dryRun?.matchedTimeBlocks, 7)
    }

    func testSavingARuleClearsTheFormAndRereadsTheList() async {
        let api = MockRolesAPI()
        var listReads = 0
        api.rules = { listReads += 1; return try RolesFixtures.rules() }
        let viewModel = makeRules(api)
        await viewModel.load()
        viewModel.draft.pattern = "feat("

        await viewModel.saveRule()

        XCTAssertEqual(api.ruleDrafts.count, 1)
        XCTAssertEqual(viewModel.draft.pattern, "")
        XCTAssertNil(viewModel.dryRun)
        XCTAssertEqual(listReads, 2)
    }

    func testFailedSaveKeepsTheDraft() async {
        let api = MockRolesAPI()
        let viewModel = makeRules(api)
        await viewModel.load()
        viewModel.draft.pattern = "feat("
        api.write = { throw APIClientError.unexpectedStatus(422) }

        await viewModel.saveRule()

        XCTAssertEqual(viewModel.draft.pattern, "feat(")
        XCTAssertEqual(viewModel.errorMessage, "Сервер ответил ошибкой 422")
    }

    func testSwitchingARuleOffPatchesItsId() async throws {
        let api = MockRolesAPI()
        let viewModel = makeRules(api)
        await viewModel.load()

        await viewModel.setActive(try XCTUnwrap(viewModel.rules.first), isActive: false)

        XCTAssertEqual(api.toggled.map { $0.0 }, [5])
        XCTAssertEqual(api.toggled.map { $0.1 }, [false])
    }

    func testReclassifyDefaultsToAMonthAndTheSegmentSetsBothDates() async {
        let api = MockRolesAPI()
        let viewModel = makeRules(api)
        await viewModel.load()

        await viewModel.reclassify()
        viewModel.selectReclassify(period: .week)
        await viewModel.reclassify()

        XCTAssertEqual(api.reclassifyRequests.map { $0.0 }, ["2026-07-29", "2026-08-21"])
        XCTAssertEqual(api.reclassifyRequests.map { $0.1 }, ["2026-08-27", "2026-08-27"])
        XCTAssertEqual(viewModel.reclassified?.protected, 2)
    }

    func testReclassifySendsAnyChosenDatesAndRefusesAReversedRange() async throws {
        let api = MockRolesAPI()
        let viewModel = makeRules(api)
        await viewModel.load()

        viewModel.reclassifyFrom = RolesFormat.date(fromDay: "2026-05-03")
        viewModel.reclassifyTo = RolesFormat.date(fromDay: "2026-06-11")
        await viewModel.reclassify()
        viewModel.reclassifyFrom = RolesFormat.date(fromDay: "2026-07-01")
        await viewModel.reclassify()

        XCTAssertEqual(api.reclassifyRequests.count, 1)
        XCTAssertEqual(api.reclassifyRequests[0].0, "2026-05-03")
        XCTAssertEqual(api.reclassifyRequests[0].1, "2026-06-11")
        XCTAssertFalse(viewModel.canReclassify)
    }

    func testPriorityMayBeAnyIntegerIncludingNegative() async {
        let api = MockRolesAPI()
        let viewModel = makeRules(api)
        await viewModel.load()
        viewModel.draft.pattern = "x"
        viewModel.draft.priority = -5

        await viewModel.saveRule()

        XCTAssertEqual(api.ruleDrafts.first?.priority, -5)
    }

    func testTwoParallelSavesOfARuleSendOnePost() async {
        let api = MockRolesAPI()
        api.write = { try await Task.sleep(nanoseconds: 100_000_000) }
        let viewModel = makeRules(api)
        await viewModel.load()
        viewModel.draft.pattern = "feat("

        async let first: Void = viewModel.saveRule()
        async let second: Void = viewModel.saveRule()
        _ = await (first, second)

        XCTAssertEqual(api.ruleDrafts.count, 1)
    }

    func testTwoParallelMinuteWritesSendOnePost() async {
        let api = MockRolesAPI()
        api.write = { try await Task.sleep(nanoseconds: 100_000_000) }
        let viewModel = makeDay(api)
        await viewModel.load()

        async let first = viewModel.addMinutes(roleCode: "cto", minutes: 30, note: "")
        async let second = viewModel.addMinutes(roleCode: "cto", minutes: 30, note: "")
        _ = await (first, second)

        XCTAssertEqual(api.timeBlockDrafts.count, 1)
    }
}
