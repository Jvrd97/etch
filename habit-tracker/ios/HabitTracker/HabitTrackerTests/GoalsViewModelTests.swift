// [review:need-review] PHASE-01/216, PHASE-03/295
// summary: GoalsViewModel tests mirroring GoalsBoard.test.tsx — six levels, ten milestones and five goals; the «⚠ подтверди» line kept apart; M10's chip for M9 changes once M9 is closed; the close date beside the status; the goal.md hint on an empty board — plus the toggle (done ↔ open, board re-read, failure keeps the board), the read cache offline and the not-configured state; adding a goal (empty quarter, existing goals kept, empty text, sixth goal, network failure, server reason) and the Russian words of every failure
import XCTest
@testable import HabitTracker

/// Scriptable stand-in for the API used by `GoalsViewModel`.
final class MockGoalsAPI: GoalsAPI {
    var boards: [Result<GoalsBoardDTO, Error>] = []
    var patchError: Error?
    var putError: Error?
    /// What the server answers a PUT with; defaults to the goals sent, laid over an empty 2026-Q4 board.
    var putBoard: GoalsBoardDTO?
    private(set) var puts: [(quarter: String, goals: [QuarterGoalInDTO])] = []
    private(set) var patches: [(code: String, status: MilestoneStatus)] = []
    private(set) var fetchCount = 0

    func fetchGoals() async throws -> GoalsBoardDTO {
        fetchCount += 1
        guard !boards.isEmpty else { throw APIClientError.invalidResponse }
        return try (boards.count > 1 ? boards.removeFirst() : boards[0]).get()
    }

    func patchMilestone(code: String, status: MilestoneStatus) async throws -> MilestoneDTO {
        patches.append((code, status))
        if let patchError { throw patchError }
        return GoalsFixtures.milestone(code, status: status)
    }

    func putQuarterGoals(quarter: String, goals: [QuarterGoalInDTO]) async throws -> GoalsBoardDTO {
        puts.append((quarter, goals))
        if let putError { throw putError }
        if let putBoard { return putBoard }
        return GoalsBoardDTO(
            levels: [], milestones: [], quarter: quarter,
            goals: goals.map {
                QuarterGoalDTO(
                    id: $0.ord, quarter: quarter, ord: $0.ord, textMd: $0.textMd,
                    milestoneCode: $0.milestoneCode, status: $0.status
                )
            }
        )
    }
}

enum GoalsFixtures {
    static func milestone(
        _ code: String, status: MilestoneStatus = .open, doneOn: String? = nil, dependsOn: [String] = []
    ) -> MilestoneDTO {
        MilestoneDTO(
            code: code, title: "Милстон \(code)", doneCriterion: "сделано", whenText: "сейчас",
            ord: Int(code.dropFirst()) ?? 0, status: status, doneOn: doneOn, dependsOn: dependsOn
        )
    }

    /// The board of the web test: levels 0-5, M1…M10 with M10 waiting on M8 and M9, five goals of 2026-Q3.
    static func board(m9: MilestoneStatus = .open, m9DoneOn: String? = nil) -> GoalsBoardDTO {
        GoalsBoardDTO(
            levels: (0...5).map { level in
                GoalLevelDTO(
                    level: level, title: "уровень \(level)", bodyMd: "",
                    openQuestions: level == 0 ? ["⚠ подтверди: какой из двух главный"] : []
                )
            },
            milestones: (1...8).map { milestone("M\($0)") }
                + [milestone("M9", status: m9, doneOn: m9DoneOn), milestone("M10", dependsOn: ["M8", "M9"])],
            quarter: "2026-Q3",
            goals: (1...5).map { ord in
                QuarterGoalDTO(
                    id: ord, quarter: "2026-Q3", ord: ord, textMd: "**Цель \(ord)**",
                    milestoneCode: nil, status: "open"
                )
            }
        )
    }

    static let empty = GoalsBoardDTO(levels: [], milestones: [], quarter: "2026-Q4", goals: [])
}

@MainActor
final class GoalsViewModelTests: XCTestCase {
    private let offline = APIClientError.transport(code: URLError.notConnectedToInternet.rawValue)

    private func m10(_ model: GoalsViewModel) throws -> MilestoneDTO {
        try XCTUnwrap(model.board?.milestones.first { $0.code == "M10" })
    }

    func testShowsSixLevelsTenMilestonesAndFiveGoals() async {
        let api = MockGoalsAPI()
        api.boards = [.success(GoalsFixtures.board())]
        let model = GoalsViewModel(api: api)

        await model.load()

        XCTAssertEqual(model.state, .loaded)
        XCTAssertEqual(model.board?.levels.count, 6)
        XCTAssertEqual(model.board?.milestones.count, 10)
        XCTAssertEqual(model.board?.goals.map { GoalsFormat.plain($0.textMd) }.first, "Цель 1")
        XCTAssertEqual(model.board?.quarter, "2026-Q3")
        XCTAssertFalse(model.isEmpty)
    }

    func testOpenQuestionStaysApartFromTheProse() async {
        let api = MockGoalsAPI()
        api.boards = [.success(GoalsFixtures.board())]
        let model = GoalsViewModel(api: api)

        await model.load()

        XCTAssertEqual(model.board?.levels.first?.openQuestions, ["⚠ подтверди: какой из двух главный"])
        XCTAssertEqual(model.board?.levels.first?.bodyMd, "")
    }

    func testClosingM9ChangesHowM10ShowsIt() async throws {
        let api = MockGoalsAPI()
        api.boards = [.success(GoalsFixtures.board()), .success(GoalsFixtures.board(m9: .done, m9DoneOn: "2026-08-30"))]
        let model = GoalsViewModel(api: api)
        await model.load()
        XCTAssertEqual(model.dependencies(of: try m10(model)).map(\.text), ["M8 · ждёт", "M9 · ждёт"])

        await model.toggle("M9")

        XCTAssertEqual(api.patches.map(\.code), ["M9"])
        XCTAssertEqual(api.patches.map(\.status), [.done])
        XCTAssertEqual(model.dependencies(of: try m10(model)).map(\.text), ["M8 · ждёт", "M9 · открыт"])
        XCTAssertEqual(model.dependencies(of: try m10(model)).map(\.isOpened), [false, true])
        XCTAssertTrue(model.saving.isEmpty)
    }

    func testClosedMilestoneShowsItsDateAndReopens() async throws {
        let api = MockGoalsAPI()
        api.boards = [.success(GoalsFixtures.board(m9: .done, m9DoneOn: "2026-08-30"))]
        let model = GoalsViewModel(api: api)
        await model.load()
        let m9 = try XCTUnwrap(model.board?.milestones.first { $0.code == "M9" })

        XCTAssertEqual(GoalsFormat.statusLine(m9), "закрыт · 2026-08-30")
        XCTAssertEqual(GoalsFormat.actionTitle(for: m9.status), "Открыть")

        await model.toggle("M9")

        XCTAssertEqual(api.patches.map(\.status), [.open])
    }

    func testStatusWordsAndActions() {
        XCTAssertEqual(MilestoneStatus.allCases.map(GoalsFormat.statusLabel), ["открыт", "в работе", "закрыт", "снят"])
        XCTAssertEqual(GoalsFormat.toggled(.inProgress), .done)
        XCTAssertEqual(GoalsFormat.toggled(.dropped), .done)
        XCTAssertEqual(GoalsFormat.actionTitle(for: .open), "Закрыть")
        XCTAssertEqual(GoalsFormat.statusLine(GoalsFixtures.milestone("M1")), "открыт")
    }

    func testNoDependenciesReadsAsUnblocked() {
        let model = GoalsViewModel(api: MockGoalsAPI())
        XCTAssertTrue(model.dependencies(of: GoalsFixtures.milestone("M1")).isEmpty)
        XCTAssertEqual(GoalsFormat.unblockedText, "ничем не заблокирован")
    }

    func testBoldIsStrippedRatherThanRendered() {
        XCTAssertEqual(GoalsFormat.plain("**Небольшой дом** и **сад**"), "Небольшой дом и сад")
        XCTAssertEqual(GoalsFormat.plain("без разметки"), "без разметки")
    }

    func testEmptyBoardInvitesToAddAGoal() async {
        let api = MockGoalsAPI()
        api.boards = [.success(GoalsFixtures.empty)]
        let model = GoalsViewModel(api: api)

        await model.load()

        XCTAssertEqual(model.state, .loaded)
        XCTAssertTrue(model.isEmpty)
        XCTAssertTrue(GoalsFormat.emptyText.contains("Добавьте"))
        XCTAssertFalse(GoalsFormat.emptyText.contains("goal.md"))
        XCTAssertTrue(model.canAddGoal)
    }

    func testFailedToggleKeepsTheBoardAndSaysWhy() async {
        let api = MockGoalsAPI()
        api.boards = [.success(GoalsFixtures.board())]
        api.patchError = APIClientError.unexpectedStatus(404)
        let model = GoalsViewModel(api: api)
        await model.load()

        await model.toggle("M9")

        XCTAssertEqual(model.board, GoalsFixtures.board())
        XCTAssertEqual(model.errorMessage, "Сервер ответил ошибкой 404.")
        XCTAssertTrue(model.saving.isEmpty)
        XCTAssertEqual(api.fetchCount, 1)
    }

    func testOfflineLoadShowsTheCachedBoard() async {
        let store = InMemoryCacheStore()
        let online = MockGoalsAPI()
        online.boards = [.success(GoalsFixtures.board())]
        await GoalsViewModel(api: online, cacheStore: store).load()

        let down = MockGoalsAPI()
        down.boards = [.failure(offline)]
        let model = GoalsViewModel(api: down, cacheStore: store)
        await model.load()

        XCTAssertEqual(model.state, .loaded)
        XCTAssertEqual(model.board, GoalsFixtures.board())
        XCTAssertNotNil(model.offlineAsOf)
    }

    func testOfflineWithoutCacheIsAFailure() async {
        let api = MockGoalsAPI()
        api.boards = [.failure(offline)]
        let model = GoalsViewModel(api: api)

        await model.load()

        XCTAssertEqual(model.state, .failure(GoalsFormat.message(for: offline)))
        XCTAssertEqual(
            GoalsFormat.message(for: offline), "Нет связи с сервером. Проверьте интернет и адрес в Настройках."
        )
        XCTAssertNil(model.board)
    }

    func testWithoutServerAddressSaysWhereToSetIt() async {
        let model = GoalsViewModel(apiProvider: { nil })

        await model.load()

        XCTAssertEqual(model.state, .failure(GoalsFormat.notConfiguredMessage))
    }

    func testGoalsRowSitsUnderMore() {
        XCTAssertTrue(MoreDestination.allCases.contains(.goals))
        XCTAssertEqual(MoreDestination.goals.title, "Цели")
    }

    // MARK: Adding a goal

    private func loaded(_ board: GoalsBoardDTO, api: MockGoalsAPI = MockGoalsAPI()) async -> (GoalsViewModel, MockGoalsAPI) {
        api.boards = [.success(board)]
        let model = GoalsViewModel(api: api)
        await model.load()
        return (model, api)
    }

    func testAddingAGoalToAnEmptyQuarterSendsItAsTheFirst() async {
        let (model, api) = await loaded(GoalsFixtures.empty)

        let added = await model.addGoal(text: "  Пробежать 10 км  ")

        XCTAssertTrue(added)
        XCTAssertEqual(api.puts.count, 1)
        XCTAssertEqual(api.puts.first?.quarter, "2026-Q4")
        XCTAssertEqual(api.puts.first?.goals, [QuarterGoalInDTO(ord: 1, textMd: "Пробежать 10 км", milestoneCode: nil, status: "open")])
        XCTAssertEqual(model.board?.goals.map(\.textMd), ["Пробежать 10 км"])
        XCTAssertNil(model.formError)
        XCTAssertFalse(model.isAdding)
        XCTAssertFalse(model.isEmpty)
    }

    func testAddingKeepsTheGoalsAlreadyThereWithTheirLinksAndStatus() async {
        var board = GoalsFixtures.empty
        board = GoalsBoardDTO(
            levels: [], milestones: [], quarter: "2026-Q4",
            goals: [
                QuarterGoalDTO(id: 1, quarter: "2026-Q4", ord: 1, textMd: "Первая", milestoneCode: "M9", status: "done"),
                QuarterGoalDTO(id: 3, quarter: "2026-Q4", ord: 3, textMd: "Третья", milestoneCode: nil, status: "open"),
            ]
        )
        let (model, api) = await loaded(board)

        _ = await model.addGoal(text: "Новая")

        XCTAssertEqual(api.puts.first?.goals, [
            QuarterGoalInDTO(ord: 1, textMd: "Первая", milestoneCode: "M9", status: "done"),
            QuarterGoalInDTO(ord: 3, textMd: "Третья", milestoneCode: nil, status: "open"),
            QuarterGoalInDTO(ord: 2, textMd: "Новая", milestoneCode: nil, status: "open"),
        ])
    }

    func testEmptyTextIsRefusedWithoutAnyRequest() async {
        let (model, api) = await loaded(GoalsFixtures.empty)

        let added = await model.addGoal(text: "  \n ")

        XCTAssertFalse(added)
        XCTAssertEqual(model.formError, "Напишите, какая это цель.")
        XCTAssertTrue(api.puts.isEmpty)
    }

    func testSixthGoalIsRefusedAndTheButtonGoesAway() async {
        let (model, api) = await loaded(GoalsFixtures.board())

        XCTAssertFalse(model.canAddGoal)
        let added = await model.addGoal(text: "Шестая")

        XCTAssertFalse(added)
        XCTAssertEqual(model.formError, "В квартале не больше пяти целей: уберите или замените одну из них.")
        XCTAssertTrue(api.puts.isEmpty)
    }

    func testNetworkFailureKeepsTheBoardAndSaysSoInRussian() async {
        let (model, api) = await loaded(GoalsFixtures.empty)
        api.putError = offline

        let added = await model.addGoal(text: "Цель")

        XCTAssertFalse(added)
        XCTAssertEqual(
            model.formError, "Нет связи с сервером. Проверьте интернет и адрес в Настройках."
        )
        XCTAssertEqual(model.board, GoalsFixtures.empty)
        XCTAssertFalse(model.isAdding)
        XCTAssertFalse(model.formError?.contains("Network error") ?? true)
    }

    func testServerRefusalShowsItsRussianReason() async {
        let (model, api) = await loaded(GoalsFixtures.empty)
        api.putError = GoalsWriteError.rejected(
            status: 422, detail: "Квартал 2026-Q4 не записан: место 1 занято дважды."
        )

        _ = await model.addGoal(text: "Цель")

        XCTAssertEqual(model.formError, "Квартал 2026-Q4 не записан: место 1 занято дважды.")
    }

    func testRefusalWithoutAReasonFallsBackToTheStatus() async {
        let (model, api) = await loaded(GoalsFixtures.empty)
        api.putError = APIClientError.unexpectedStatus(500)

        _ = await model.addGoal(text: "Цель")

        XCTAssertEqual(model.formError, "Сервер ответил ошибкой 500.")
    }

    func testStatusWordsAreRussian() {
        XCTAssertEqual(GoalsFormat.message(for: APIClientError.timeout), "Сервер не ответил вовремя. Попробуйте ещё раз.")
        XCTAssertEqual(GoalsFormat.message(for: APIClientError.unauthorized), "Сервер не принял ключ (401). Проверьте ключ в Настройках.")
        XCTAssertEqual(GoalsFormat.message(for: APIClientError.invalidResponse), "Сервер ответил непонятно. Попробуйте ещё раз.")
        XCTAssertEqual(GoalsFormat.message(for: APIClientError.invalidBaseURL), "Адрес сервера неверный. Исправьте его в Настройках.")
        XCTAssertEqual(GoalsFormat.message(for: CancellationError()), "Не получилось выполнить действие. Попробуйте ещё раз.")
        XCTAssertEqual(GoalsFormat.notConfiguredMessage, "Укажите адрес сервера в Настройках.")
    }

    func testFormErrorClearsOnANewAttempt() async {
        let (model, api) = await loaded(GoalsFixtures.empty)
        api.putError = offline
        _ = await model.addGoal(text: "Цель")
        XCTAssertNotNil(model.formError)

        api.putError = nil
        let added = await model.addGoal(text: "Цель")

        XCTAssertTrue(added)
        XCTAssertNil(model.formError)
    }
}
