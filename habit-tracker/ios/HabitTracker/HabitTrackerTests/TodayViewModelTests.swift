// [review:need-review] PHASE-01/05-ios-today-quick-entry, PHASE-01/38-ios-avoid-streaks, PHASE-01/210, PHASE-03/225, PHASE-03/242, PHASE-03/248, PHASE-03/256, PHASE-03/263
// summary: PHASE-03/263 — two parallel loads (L2 answered, L1 failed late), empty screen refresh failure, real failing save for another action's error
// summary: PHASE-03/256 — a re-read of the records leaves the cache stamp at the age of the categories; a second load keeps the loaded screen (no loader, a failure is a line of text)
// summary: PHASE-03/248 round 2 — a refresh that works takes back the failure line of an earlier refresh and leaves the error of another action
// summary: PHASE-03/242 — a failed re-read after a background delivery leaves no error; a load's read answered after the re-read a delivery started neither replaces the screen nor the cache; the double sits on the main actor
// summary: unit tests for TodayViewModel — load, save success/failure, checklist upsert routing, one bulk avoid-streak read, one-tap relapse with undo and details, re-read of the day after a quick-mark tap, entry delete; offline: a form or checklist save goes to the shared outbox under the key of its attempt and shows as pending until delivered, the count is the queue's
import Combine
import XCTest
@testable import HabitTracker

/// Scriptable stand-in for the API used by `TodayViewModel`. On the main actor: the screen reads it
/// while the queue replays through it, and the two must not race on its state.
@MainActor
final class MockTodayAPI: TodayScreenAPI {
    var categoriesResult: Result<[CategoryDTO], Error> = .success([])
    var entriesResult: Result<[EntryDTO], Error> = .success([])
    var createEntryResult: Result<EntryDTO, Error>?
    var upsertChecklistResult: Result<EntryDTO, Error>?
    var streakResults: [Int: Result<CategoryStreakDTO, Error>] = [:]
    var avoidStreaksResult: Result<[CategoryStreakDTO], Error> = .success([])
    var relapseResults: [Result<RelapseRecordedDTO, Error>] = []
    var updateEntryResult: Result<EntryDTO, Error>?
    var deleteEntryError: Error?
    private(set) var avoidStreakFetches = 0
    private(set) var relapseCalls: [(categoryId: Int, key: String)] = []
    private(set) var updatedEntries: [(id: Int, payload: EntryUpdateDTO)] = []
    private(set) var deletedEntryIDs: [Int] = []
    private(set) var fetchedEntryRanges: [(start: String, end: String)] = []
    private(set) var createdEntries: [EntryCreateDTO] = []
    private(set) var createKeys: [String?] = []
    private(set) var upsertedChecklists: [ChecklistUpsertDTO] = []
    private(set) var fetchedStreakIDs: [Int] = []

    /// Runs once inside the next categories read, before its answer: the load's own parent waits on the
    /// categories first, so holding them here never cancels the entries read beside it.
    var duringFetchCategories: (@MainActor () async -> Void)?

    func fetchCategories() async throws -> [CategoryDTO] {
        if let hook = duringFetchCategories {
            duringFetchCategories = nil
            await hook()
        }
        return try categoriesResult.get()
    }

    /// Runs once inside the next entries read, after its answer is fixed and before it returns: the
    /// answer is what the server held when the read arrived.
    var duringFetchEntries: (@MainActor () async -> Void)?
    /// Runs once inside the next entry create, before its answer.
    var duringCreateEntry: (@MainActor () async -> Void)?
    private(set) var entriesAnswered = 0

    func fetchEntries(startDate: String, endDate: String) async throws -> [EntryDTO] {
        fetchedEntryRanges.append((start: startDate, end: endDate))
        let answer = entriesResult
        if let hook = duringFetchEntries {
            duringFetchEntries = nil
            await hook()
        }
        entriesAnswered += 1
        return try answer.get()
    }

    func createEntry(_ entry: EntryCreateDTO) async throws -> EntryDTO {
        try await createEntry(entry, idempotencyKey: nil)
    }

    func createEntry(_ entry: EntryCreateDTO, idempotencyKey: String?) async throws -> EntryDTO {
        createdEntries.append(entry)
        createKeys.append(idempotencyKey)
        if let hook = duringCreateEntry {
            duringCreateEntry = nil
            await hook()
        }
        guard let result = createEntryResult else {
            throw APIClientError.invalidResponse
        }
        return try result.get()
    }

    func upsertChecklistEntry(_ payload: ChecklistUpsertDTO) async throws -> EntryDTO {
        upsertedChecklists.append(payload)
        guard let result = upsertChecklistResult else {
            throw APIClientError.invalidResponse
        }
        return try result.get()
    }

    func fetchStreak(categoryId: Int) async throws -> CategoryStreakDTO {
        fetchedStreakIDs.append(categoryId)
        guard let result = streakResults[categoryId] else {
            throw APIClientError.invalidResponse
        }
        return try result.get()
    }

    func fetchAvoidStreaks() async throws -> [CategoryStreakDTO] {
        avoidStreakFetches += 1
        return try avoidStreaksResult.get()
    }

    func recordRelapse(categoryId: Int, idempotencyKey: String) async throws -> RelapseRecordedDTO {
        relapseCalls.append((categoryId: categoryId, key: idempotencyKey))
        guard !relapseResults.isEmpty else { throw APIClientError.invalidResponse }
        return try relapseResults.removeFirst().get()
    }

    func updateEntry(id: Int, _ payload: EntryUpdateDTO) async throws -> EntryDTO {
        updatedEntries.append((id: id, payload: payload))
        guard let result = updateEntryResult else { throw APIClientError.invalidResponse }
        return try result.get()
    }

    func deleteEntry(id: Int) async throws {
        deletedEntryIDs.append(id)
        if let deleteEntryError { throw deleteEntryError }
    }
}

extension MockTodayAPI: OutboxEntriesAPI {}

@MainActor
final class TodayViewModelTests: XCTestCase {
    private static let fixedToday = "2026-07-23"

    private func makeFixedDate() -> Date {
        var components = DateComponents()
        components.year = 2026
        components.month = 7
        components.day = 23
        components.hour = 12
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar.date(from: components)!
    }

    private func makeViewModel(api: MockTodayAPI) -> TodayViewModel {
        let fixed = makeFixedDate()
        return TodayViewModel(api: api, timeZone: TimeZone(identifier: "UTC")!, now: { fixed })
    }

    private func makeCategory(
        id: Int,
        name: String,
        fields: [FieldDTO],
        displayMode: String = "form",
        streakMode: String = "build"
    ) -> CategoryDTO {
        CategoryDTO(
            id: id,
            name: name,
            icon: nil,
            color: nil,
            displayMode: displayMode,
            streakMode: streakMode,
            isActive: true,
            fields: fields
        )
    }

    private func makeStreak(
        categoryID: Int,
        current: Int,
        best: Int,
        lastRelapse: String?
    ) -> CategoryStreakDTO {
        CategoryStreakDTO(
            categoryId: categoryID,
            streakMode: "avoid",
            currentStreak: current,
            bestStreak: best,
            lastRelapseDate: lastRelapse
        )
    }

    private func makeNumberField(id: Int, name: String) -> FieldDTO {
        FieldDTO(
            id: id,
            name: name,
            fieldType: .number,
            isRequired: true,
            defaultValue: nil,
            options: nil,
            order: 0
        )
    }

    private func makeBooleanField(id: Int, name: String) -> FieldDTO {
        FieldDTO(
            id: id,
            name: name,
            fieldType: .boolean,
            isRequired: false,
            defaultValue: nil,
            options: nil,
            order: 0
        )
    }

    func testLoadSuccessPopulatesCategoriesAndTodayEntries() async {
        let api = MockTodayAPI()
        let pushups = makeCategory(
            id: 1, name: "Pushups", fields: [makeNumberField(id: 10, name: "Count")]
        )
        api.categoriesResult = .success([pushups])
        api.entriesResult = .success([
            EntryDTO(
                id: 100,
                categoryId: 1,
                entryDate: Self.fixedToday,
                values: [EntryValueDTO(fieldId: 10, value: "42")]
            )
        ])

        let viewModel = makeViewModel(api: api)
        await viewModel.load()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.categories.map(\.id), [1])
        XCTAssertEqual(viewModel.entries(forCategory: 1).count, 1)
        XCTAssertEqual(api.fetchedEntryRanges.count, 1)
        XCTAssertEqual(api.fetchedEntryRanges.first?.start, Self.fixedToday)
        XCTAssertEqual(api.fetchedEntryRanges.first?.end, Self.fixedToday)
    }

    func testSaveEntryPostsTodayPayloadAndAppendsEntry() async {
        let api = MockTodayAPI()
        let created = EntryDTO(
            id: 101,
            categoryId: 1,
            entryDate: Self.fixedToday,
            values: [EntryValueDTO(fieldId: 10, value: "42")]
        )
        api.createEntryResult = .success(created)

        let viewModel = makeViewModel(api: api)
        let saved = await viewModel.saveEntry(categoryID: 1, values: [10: "42"])

        XCTAssertTrue(saved)
        XCTAssertEqual(api.createdEntries.count, 1)
        let payload = api.createdEntries[0]
        XCTAssertEqual(payload.categoryId, 1)
        XCTAssertEqual(payload.entryDate, Self.fixedToday)
        XCTAssertEqual(payload.values, [EntryValueDTO(fieldId: 10, value: "42")])
        XCTAssertEqual(viewModel.entries(forCategory: 1), [created])
        XCTAssertNil(viewModel.saveErrorMessage)
    }

    func testSaveEntryFailureSetsErrorMessageAndReturnsFalse() async {
        let api = MockTodayAPI()
        api.createEntryResult = .failure(APIClientError.unauthorized)

        let viewModel = makeViewModel(api: api)
        let saved = await viewModel.saveEntry(categoryID: 1, values: [10: "42"])

        XCTAssertFalse(saved)
        XCTAssertEqual(viewModel.saveErrorMessage, "Invalid API key (401)")
        XCTAssertTrue(viewModel.entries(forCategory: 1).isEmpty)
    }

    func testSaveEntryChecklistCategoryUsesIdempotentUpsertNotPost() async {
        let api = MockTodayAPI()
        let checklist = makeCategory(
            id: 2,
            name: "Morning routine",
            fields: [makeBooleanField(id: 20, name: "Meditate")],
            displayMode: "checklist"
        )
        api.categoriesResult = .success([checklist])
        let upserted = EntryDTO(
            id: 200,
            categoryId: 2,
            entryDate: Self.fixedToday,
            values: [EntryValueDTO(fieldId: 20, value: "true")]
        )
        api.upsertChecklistResult = .success(upserted)

        let viewModel = makeViewModel(api: api)
        await viewModel.load()
        let saved = await viewModel.saveEntry(categoryID: 2, values: [20: "true"])

        XCTAssertTrue(saved)
        XCTAssertTrue(api.createdEntries.isEmpty, "checklist must not use generic POST")
        XCTAssertEqual(api.upsertedChecklists.count, 1)
        let payload = api.upsertedChecklists[0]
        XCTAssertEqual(payload.categoryId, 2)
        XCTAssertEqual(payload.entryDate, Self.fixedToday)
        XCTAssertEqual(payload.values, ["20": true])
        XCTAssertEqual(viewModel.entries(forCategory: 2), [upserted])
    }

    func testSaveEntryChecklistUpsertReplacesExistingEntryInsteadOfDuplicating() async {
        let api = MockTodayAPI()
        let checklist = makeCategory(
            id: 2,
            name: "Morning routine",
            fields: [makeBooleanField(id: 20, name: "Meditate")],
            displayMode: "checklist"
        )
        api.categoriesResult = .success([checklist])
        api.upsertChecklistResult = .success(
            EntryDTO(
                id: 200,
                categoryId: 2,
                entryDate: Self.fixedToday,
                values: [EntryValueDTO(fieldId: 20, value: "false")]
            )
        )

        let viewModel = makeViewModel(api: api)
        await viewModel.load()
        _ = await viewModel.saveEntry(categoryID: 2, values: [20: "false"])
        let updated = EntryDTO(
            id: 200,
            categoryId: 2,
            entryDate: Self.fixedToday,
            values: [EntryValueDTO(fieldId: 20, value: "true")]
        )
        api.upsertChecklistResult = .success(updated)
        _ = await viewModel.saveEntry(categoryID: 2, values: [20: "true"])

        XCTAssertEqual(api.upsertedChecklists.count, 2)
        XCTAssertEqual(viewModel.entries(forCategory: 2), [updated])
    }

    private func avoidCategory(id: Int = 1, fields: [FieldDTO]? = nil) -> CategoryDTO {
        makeCategory(
            id: id,
            name: "RMO",
            fields: fields ?? [makeNumberField(id: 10, name: "Count")],
            streakMode: "avoid"
        )
    }

    private func recorded(
        entryID: Int = 300, created: Bool = true, values: [EntryValueDTO] = []
    ) -> RelapseRecordedDTO {
        RelapseRecordedDTO(
            entry: EntryDTO(
                id: entryID, categoryId: 1, entryDate: Self.fixedToday, values: values
            ),
            created: created
        )
    }

    func testLoadReadsTheStreaksOfAllAvoidCategoriesInOneRequest() async {
        let api = MockTodayAPI()
        let pushups = makeCategory(
            id: 3, name: "Pushups", fields: [makeNumberField(id: 20, name: "Count")]
        )
        api.categoriesResult = .success([avoidCategory(id: 1), avoidCategory(id: 2), pushups])
        api.avoidStreaksResult = .success([
            makeStreak(categoryID: 1, current: 7, best: 12, lastRelapse: "2026-07-16"),
            makeStreak(categoryID: 2, current: 0, best: 3, lastRelapse: Self.fixedToday),
        ])

        let viewModel = makeViewModel(api: api)
        await viewModel.load()

        XCTAssertEqual(api.avoidStreakFetches, 1, "N avoid categories must not cost N requests")
        XCTAssertTrue(api.fetchedStreakIDs.isEmpty)
        XCTAssertEqual(viewModel.streak(forCategory: 1)?.currentStreak, 7)
        XCTAssertEqual(viewModel.streak(forCategory: 2)?.bestStreak, 3)
        XCTAssertNil(viewModel.streak(forCategory: 3), "build categories have no streak card")
    }

    func testNoAvoidCategoryMeansNoStreakRequestAtAll() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([
            makeCategory(id: 3, name: "Pushups", fields: [makeNumberField(id: 20, name: "Count")])
        ])

        let viewModel = makeViewModel(api: api)
        await viewModel.load()

        XCTAssertEqual(api.avoidStreakFetches, 0)
    }

    func testLoadStreakFailureDegradesToNoNumbersWithoutFailingLoad() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([avoidCategory()])
        api.avoidStreaksResult = .failure(APIClientError.unexpectedStatus(500))

        let viewModel = makeViewModel(api: api)
        await viewModel.load()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertNil(viewModel.streak(forCategory: 1))
        XCTAssertNotNil(viewModel.streaksError, "the section says the numbers failed, not the screen")
    }

    func testRecordRelapseIsOneTapAtAnyFieldSetAndResetsTheStreakFromTheServer() async {
        let api = MockTodayAPI()
        // No number field at all: the old client refused this category.
        api.categoriesResult = .success([
            avoidCategory(fields: [makeBooleanField(id: 10, name: "Did it")])
        ])
        api.avoidStreaksResult = .success([
            makeStreak(categoryID: 1, current: 7, best: 12, lastRelapse: "2026-07-16")
        ])
        let viewModel = makeViewModel(api: api)
        await viewModel.load()
        api.relapseResults = [.success(recorded())]
        api.streakResults[1] = .success(
            makeStreak(categoryID: 1, current: 0, best: 12, lastRelapse: Self.fixedToday)
        )

        await viewModel.recordRelapse(categoryID: 1)

        XCTAssertEqual(api.relapseCalls.map(\.categoryId), [1])
        XCTAssertFalse(api.relapseCalls[0].key.isEmpty)
        XCTAssertTrue(api.createdEntries.isEmpty, "the client no longer writes the relapse entry itself")
        XCTAssertEqual(viewModel.streak(forCategory: 1)?.currentStreak, 0)
        XCTAssertEqual(viewModel.streak(forCategory: 1)?.bestStreak, 12)
        XCTAssertEqual(viewModel.relapseState(forCategory: 1), .recorded(recorded()))
        XCTAssertEqual(viewModel.entries(forCategory: 1).map(\.id), [300])
        XCTAssertNil(viewModel.saveErrorMessage)
    }

    func testAFailedRelapseTapIsRetriedUnderTheSameKey() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([avoidCategory()])
        let viewModel = makeViewModel(api: api)
        await viewModel.load()
        api.relapseResults = [.failure(APIClientError.timeout), .success(recorded())]
        api.streakResults[1] = .success(
            makeStreak(categoryID: 1, current: 0, best: 12, lastRelapse: Self.fixedToday)
        )

        await viewModel.recordRelapse(categoryID: 1)
        XCTAssertEqual(viewModel.relapseState(forCategory: 1), .idle)
        XCTAssertNotNil(viewModel.saveErrorMessage)
        await viewModel.recordRelapse(categoryID: 1)

        XCTAssertEqual(api.relapseCalls.count, 2)
        XCTAssertEqual(
            api.relapseCalls[0].key, api.relapseCalls[1].key,
            "a lost answer must not become a second relapse"
        )
    }

    func testARepeatedTapKeepsTheUndoOfTheRelapseThisCardWrote() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([avoidCategory()])
        let viewModel = makeViewModel(api: api)
        await viewModel.load()
        api.relapseResults = [
            .success(recorded(created: true)),
            .success(recorded(created: false)),
        ]
        api.streakResults[1] = .success(
            makeStreak(categoryID: 1, current: 0, best: 1, lastRelapse: Self.fixedToday)
        )

        await viewModel.recordRelapse(categoryID: 1)
        await viewModel.recordRelapse(categoryID: 1)

        XCTAssertEqual(viewModel.relapseState(forCategory: 1), .recorded(recorded(created: true)))
        XCTAssertEqual(viewModel.entries(forCategory: 1).count, 1)
    }

    func testARelapseSomebodyElseWroteCannotBeUndoneFromHere() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([avoidCategory()])
        let viewModel = makeViewModel(api: api)
        await viewModel.load()
        api.relapseResults = [.success(recorded(created: false))]
        api.streakResults[1] = .success(
            makeStreak(categoryID: 1, current: 0, best: 1, lastRelapse: Self.fixedToday)
        )

        await viewModel.recordRelapse(categoryID: 1)
        await viewModel.undoRelapse(categoryID: 1)

        XCTAssertTrue(api.deletedEntryIDs.isEmpty)
        XCTAssertEqual(viewModel.relapseState(forCategory: 1), .recorded(recorded(created: false)))
    }

    func testUndoRelapseDeletesTheEntryAndReadsTheStreakAgain() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([avoidCategory()])
        let viewModel = makeViewModel(api: api)
        await viewModel.load()
        api.relapseResults = [.success(recorded())]
        api.streakResults[1] = .success(
            makeStreak(categoryID: 1, current: 0, best: 12, lastRelapse: Self.fixedToday)
        )
        await viewModel.recordRelapse(categoryID: 1)
        api.streakResults[1] = .success(
            makeStreak(categoryID: 1, current: 8, best: 12, lastRelapse: "2026-07-16")
        )

        await viewModel.undoRelapse(categoryID: 1)

        XCTAssertEqual(api.deletedEntryIDs, [300])
        XCTAssertEqual(viewModel.relapseState(forCategory: 1), .idle)
        XCTAssertTrue(viewModel.entries(forCategory: 1).isEmpty)
        XCTAssertEqual(viewModel.streak(forCategory: 1)?.currentStreak, 8)
    }

    func testRelapseDetailsPatchTheAmountOverTheTickTheServerWrote() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([
            avoidCategory(fields: [
                makeBooleanField(id: 11, name: "Did it"), makeNumberField(id: 10, name: "Count"),
            ])
        ])
        let viewModel = makeViewModel(api: api)
        await viewModel.load()
        api.relapseResults = [
            .success(recorded(values: [EntryValueDTO(fieldId: 11, value: "true")]))
        ]
        api.streakResults[1] = .success(
            makeStreak(categoryID: 1, current: 0, best: 1, lastRelapse: Self.fixedToday)
        )
        await viewModel.recordRelapse(categoryID: 1)
        api.updateEntryResult = .success(
            EntryDTO(
                id: 300, categoryId: 1, entryDate: Self.fixedToday, notes: "slipped",
                values: [
                    EntryValueDTO(fieldId: 11, value: "true"),
                    EntryValueDTO(fieldId: 10, value: "3"),
                ]
            )
        )

        let saved = await viewModel.saveRelapseDetails(
            categoryID: 1, amount: " 3 ", notes: " slipped "
        )

        XCTAssertTrue(saved)
        let patch = api.updatedEntries.last
        XCTAssertEqual(patch?.id, 300)
        XCTAssertEqual(patch?.payload.notes, "slipped")
        XCTAssertEqual(
            patch?.payload.values,
            [EntryValueDTO(fieldId: 11, value: "true"), EntryValueDTO(fieldId: 10, value: "3")],
            "PATCH replaces the whole list, so the server's tick goes back with the amount"
        )
        guard case .recorded(let state) = viewModel.relapseState(forCategory: 1) else {
            return XCTFail("expected the recorded state")
        }
        XCTAssertTrue(state.created)
        XCTAssertEqual(state.entry.notes, "slipped")
    }

    func testRelapseDetailsRefuseAnAmountThatWouldTurnTheRelapseIntoACleanDay() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([avoidCategory()])
        let viewModel = makeViewModel(api: api)
        await viewModel.load()
        api.relapseResults = [.success(recorded())]
        api.streakResults[1] = .success(
            makeStreak(categoryID: 1, current: 0, best: 1, lastRelapse: Self.fixedToday)
        )
        await viewModel.recordRelapse(categoryID: 1)

        let saved = await viewModel.saveRelapseDetails(categoryID: 1, amount: "0", notes: "")

        XCTAssertFalse(saved)
        XCTAssertTrue(api.updatedEntries.isEmpty)
        XCTAssertEqual(viewModel.saveErrorMessage, TodayViewModel.amountNotPositiveMessage)
    }

    func testReloadAfterMarkReadsTheDaysEntriesAndTheStreakOfThatCategory() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([avoidCategory()])
        api.avoidStreaksResult = .success([
            makeStreak(categoryID: 1, current: 7, best: 12, lastRelapse: "2026-07-16")
        ])
        let viewModel = makeViewModel(api: api)
        await viewModel.load()
        api.entriesResult = .success([
            EntryDTO(id: 400, categoryId: 1, entryDate: Self.fixedToday, values: [])
        ])
        api.streakResults[1] = .success(
            makeStreak(categoryID: 1, current: 0, best: 12, lastRelapse: Self.fixedToday)
        )

        await viewModel.reloadAfterMark(categoryID: 1)

        XCTAssertEqual(viewModel.entries(forCategory: 1).map(\.id), [400])
        XCTAssertEqual(api.fetchedStreakIDs, [1])
        XCTAssertEqual(viewModel.streak(forCategory: 1)?.currentStreak, 0)
    }

    func testReloadAfterMarkOfABuildCategoryAsksNoStreak() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([
            makeCategory(id: 3, name: "Pushups", fields: [makeNumberField(id: 20, name: "Count")])
        ])
        let viewModel = makeViewModel(api: api)
        await viewModel.load()

        await viewModel.reloadAfterMark(categoryID: 3)

        XCTAssertTrue(api.fetchedStreakIDs.isEmpty)
    }

    func testDeleteEntryRemovesTheRowAndRefreshesAnAvoidStreak() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([avoidCategory()])
        api.entriesResult = .success([
            EntryDTO(id: 400, categoryId: 1, entryDate: Self.fixedToday, values: [])
        ])
        let viewModel = makeViewModel(api: api)
        await viewModel.load()
        api.streakResults[1] = .success(
            makeStreak(categoryID: 1, current: 5, best: 12, lastRelapse: "2026-07-18")
        )

        let deleted = await viewModel.deleteEntry(id: 400)

        XCTAssertTrue(deleted)
        XCTAssertEqual(api.deletedEntryIDs, [400])
        XCTAssertTrue(viewModel.entries(forCategory: 1).isEmpty)
        XCTAssertEqual(viewModel.streak(forCategory: 1)?.currentStreak, 5)
    }

    func testDeleteEntryFailureKeepsTheRowAndSaysSo() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([avoidCategory()])
        api.entriesResult = .success([
            EntryDTO(id: 400, categoryId: 1, entryDate: Self.fixedToday, values: [])
        ])
        api.deleteEntryError = APIClientError.timeout
        let viewModel = makeViewModel(api: api)
        await viewModel.load()

        let deleted = await viewModel.deleteEntry(id: 400)

        XCTAssertFalse(deleted)
        XCTAssertEqual(viewModel.entries(forCategory: 1).count, 1)
        XCTAssertNotNil(viewModel.saveErrorMessage)
    }

    func testLoadFailureSetsFailureMessageWithoutCrash() async {
        let api = MockTodayAPI()
        api.categoriesResult = .failure(APIClientError.timeout)

        let viewModel = makeViewModel(api: api)
        await viewModel.load()

        guard case .failure(let message) = viewModel.state else {
            return XCTFail("Expected failure state, got \(viewModel.state)")
        }
        XCTAssertFalse(message.isEmpty)
    }

    // MARK: Offline

    private func makeOfflineViewModel(
        api: MockTodayAPI, cache: CacheStore = InMemoryCacheStore()
    ) -> (TodayViewModel, OutboxQueue) {
        let fixed = makeFixedDate()
        let server = FakeOutboxServer()
        let outbox = OutboxQueue(
            store: InMemoryOutboxStore(),
            sender: { OutboxReplay(entries: api, quickMarks: server, day: server) }
        )
        let viewModel = TodayViewModel(
            api: api, cacheStore: cache, outbox: outbox, timeZone: TimeZone(identifier: "UTC")!, now: { fixed }
        )
        return (viewModel, outbox)
    }

    private var pushups: CategoryDTO {
        makeCategory(id: 1, name: "Pushups", fields: [makeNumberField(id: 10, name: "Count")])
    }

    private var routine: CategoryDTO {
        makeCategory(
            id: 2, name: "Morning routine", fields: [makeBooleanField(id: 20, name: "Meditate")],
            displayMode: "checklist"
        )
    }

    func testAnOfflineSaveIsQueuedUnderTheKeyOfItsAttemptAndShownAsPending() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([pushups])
        api.createEntryResult = .failure(APIClientError.transport(code: -1009))
        let (viewModel, outbox) = makeOfflineViewModel(api: api)
        await viewModel.load()

        let saved = await viewModel.saveEntry(categoryID: 1, values: [10: "42"])

        XCTAssertTrue(saved, "airplane mode does not lose the record")
        XCTAssertNil(viewModel.saveErrorMessage)
        XCTAssertEqual(outbox.pendingCount, 1)
        XCTAssertEqual(outbox.pending.first?.key, api.createKeys.first ?? nil, "the replay is the same request")
        XCTAssertNotNil(api.createKeys.first ?? nil)
        XCTAssertEqual(outbox.pending.first?.label, "Pushups")
        XCTAssertEqual(viewModel.entries(forCategory: 1).map(\.isPending), [true])
        XCTAssertEqual(viewModel.entries(forCategory: 1).first?.values.first?.value, "42")
    }

    func testAnOnlineSaveCarriesAKeyAndIsNotQueued() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([pushups])
        api.createEntryResult = .success(
            EntryDTO(id: 101, categoryId: 1, entryDate: Self.fixedToday, values: [EntryValueDTO(fieldId: 10, value: "42")])
        )
        let (viewModel, outbox) = makeOfflineViewModel(api: api)
        await viewModel.load()

        _ = await viewModel.saveEntry(categoryID: 1, values: [10: "42"])

        XCTAssertNotNil(api.createKeys.first ?? nil, "a lost answer of an online save cannot become a duplicate")
        XCTAssertEqual(outbox.pendingCount, 0)
    }

    func testAnOfflineChecklistSaveIsQueuedAndShownInsteadOfTheServerRow() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([routine])
        api.entriesResult = .success(
            [EntryDTO(id: 200, categoryId: 2, entryDate: Self.fixedToday, values: [EntryValueDTO(fieldId: 20, value: "false")])]
        )
        api.upsertChecklistResult = .failure(APIClientError.timeout)
        let (viewModel, outbox) = makeOfflineViewModel(api: api)
        await viewModel.load()

        let saved = await viewModel.saveEntry(categoryID: 2, values: [20: "true"])

        XCTAssertTrue(saved)
        XCTAssertEqual(outbox.pendingCount, 1)
        let shown = viewModel.entries(forCategory: 2)
        XCTAssertEqual(shown.map(\.isPending), [true])
        XCTAssertEqual(shown.first?.values, [EntryValueDTO(fieldId: 20, value: "true")])
    }

    func testAQueuedSaveStaysVisibleAcrossAReloadUntilItIsDelivered() async throws {
        let api = MockTodayAPI()
        api.categoriesResult = .success([pushups])
        api.createEntryResult = .failure(APIClientError.timeout)
        let (viewModel, outbox) = makeOfflineViewModel(api: api)
        await viewModel.load()
        _ = await viewModel.saveEntry(categoryID: 1, values: [10: "42"])

        await viewModel.load()
        XCTAssertEqual(viewModel.entries(forCategory: 1).map(\.isPending), [true], "the server does not have it yet")

        let delivered = EntryDTO(id: 7, categoryId: 1, entryDate: Self.fixedToday, values: [EntryValueDTO(fieldId: 10, value: "42")])
        api.createEntryResult = .success(delivered)
        api.entriesResult = .success([delivered])
        await outbox.flush()
        // The delivery reads the day again on its own; the test waits for it instead of racing it.
        for _ in 0..<100 where viewModel.entries(forCategory: 1) != [delivered] {
            try await Task.sleep(nanoseconds: 10_000_000)
        }

        XCTAssertEqual(outbox.pendingCount, 0)
        XCTAssertEqual(viewModel.entries(forCategory: 1), [delivered])
        XCTAssertEqual(Set(api.createKeys.compactMap { $0 }).count, 1, "one key across the direct try and every replay")
    }

    func testADeliveryInTheBackgroundReadsTheDayAgain() async throws {
        let api = MockTodayAPI()
        api.categoriesResult = .success([pushups])
        api.createEntryResult = .failure(APIClientError.timeout)
        let (viewModel, outbox) = makeOfflineViewModel(api: api)
        await viewModel.load()
        _ = await viewModel.saveEntry(categoryID: 1, values: [10: "42"])
        let readsBefore = api.fetchedEntryRanges.count
        let delivered = EntryDTO(id: 7, categoryId: 1, entryDate: Self.fixedToday, values: [EntryValueDTO(fieldId: 10, value: "42")])
        api.createEntryResult = .success(delivered)
        api.entriesResult = .success([delivered])

        var states: [TodayViewModel.LoadState] = []
        let watch = viewModel.$state.dropFirst().sink { states.append($0) }
        defer { watch.cancel() }
        let monitor = MockNetworkMonitor()
        outbox.startAutoFlush(monitor: monitor)
        await monitor.simulateOnline()
        for _ in 0..<100 where viewModel.todayEntries.contains(where: \.isPending) || api.fetchedEntryRanges.count == readsBefore {
            try await Task.sleep(nanoseconds: 10_000_000)
        }

        XCTAssertGreaterThan(api.fetchedEntryRanges.count, readsBefore)
        XCTAssertFalse(viewModel.todayEntries.contains(where: \.isPending))
        XCTAssertFalse(states.contains(.loading), "a background delivery re-reads quietly, no loader")
    }

    func testARereadsCacheStampIsNotNewerThanTheCategoriesAndStreaksItKeeps() async throws {
        let api = MockTodayAPI()
        api.categoriesResult = .success([pushups])
        api.createEntryResult = .failure(APIClientError.timeout)
        let cache = InMemoryCacheStore()
        let server = FakeOutboxServer()
        let outbox = OutboxQueue(
            store: InMemoryOutboxStore(), sender: { OutboxReplay(entries: api, quickMarks: server, day: server) }
        )
        let loadedAt = makeFixedDate()
        var clock = loadedAt
        let viewModel = TodayViewModel(
            api: api, cacheStore: cache, outbox: outbox, timeZone: TimeZone(identifier: "UTC")!, now: { clock }
        )
        await viewModel.load()
        _ = await viewModel.saveEntry(categoryID: 1, values: [10: "42"])
        let delivered = EntryDTO(id: 7, categoryId: 1, entryDate: Self.fixedToday, values: [EntryValueDTO(fieldId: 10, value: "42")])
        api.createEntryResult = .success(delivered)
        api.entriesResult = .success([delivered])
        clock = loadedAt.addingTimeInterval(600)

        let monitor = MockNetworkMonitor()
        outbox.startAutoFlush(monitor: monitor)
        await monitor.simulateOnline()
        for _ in 0..<100 where cache.load(TodaySnapshot.self, forKey: TodayViewModel.cacheKey)?.value.entries != [delivered] {
            try await Task.sleep(nanoseconds: 10_000_000)
        }

        let cached = cache.load(TodaySnapshot.self, forKey: TodayViewModel.cacheKey)
        XCTAssertEqual(cached?.value.entries, [delivered], "the re-read's records reached the cache")
        XCTAssertEqual(cached?.updatedAt, loadedAt, "the categories in it are from the load: \"data as of\" must not say later")
    }

    func testASecondLoadKeepsTheLoadedScreenWhileItsAnswerIsOnItsWay() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([pushups])
        let viewModel = TodayViewModel(api: api, cacheStore: InMemoryCacheStore())
        await viewModel.load()
        XCTAssertEqual(viewModel.state, .loaded)
        var inFlight = false
        var gate: CheckedContinuation<Void, Never>?
        api.duringFetchEntries = {
            inFlight = true
            await withCheckedContinuation { gate = $0 }
        }

        let second = Task { await viewModel.load() }
        while !inFlight { await Task.yield() }

        XCTAssertEqual(viewModel.state, .loaded, "a full-screen loader would drop the scroll position")
        XCTAssertEqual(viewModel.categories.map(\.id), [1])
        gate?.resume()
        await second.value
        XCTAssertEqual(viewModel.state, .loaded)
    }

    func testAFailedSecondLoadLeavesTheShownDataAndSaysSoInALine() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([pushups])
        let viewModel = TodayViewModel(api: api, cacheStore: InMemoryCacheStore())
        await viewModel.load()
        api.categoriesResult = .failure(APIClientError.unauthorized)

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(viewModel.categories.map(\.id), [1], "the screen keeps what it showed")
        XCTAssertEqual(viewModel.saveErrorMessage, "\(TodayViewModel.refreshFailedMessage): \(APIClientError.unauthorized.userMessage)")
    }

    func testALaterLoadThatWorksTakesTheRefreshFailureLineAway() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([pushups])
        let viewModel = TodayViewModel(api: api, cacheStore: InMemoryCacheStore())
        await viewModel.load()
        api.categoriesResult = .failure(APIClientError.unauthorized)
        await viewModel.load()
        XCTAssertNotNil(viewModel.saveErrorMessage)

        api.categoriesResult = .success([pushups])
        await viewModel.load()

        XCTAssertNil(viewModel.saveErrorMessage, "the refresh worked: the red line must not outlive its cause")
        XCTAssertEqual(viewModel.state, .loaded)
    }

    func testALoadThatWorksKeepsTheErrorOfAnotherAction() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([pushups])
        let viewModel = TodayViewModel(api: api, cacheStore: InMemoryCacheStore())
        await viewModel.load()
        api.categoriesResult = .failure(APIClientError.unauthorized)
        await viewModel.load()
        // A save that really fails in between: its message replaced the refresh line.
        api.createEntryResult = .failure(APIClientError.unauthorized)
        let saved = await viewModel.saveEntry(categoryID: 1, values: [10: "42"])
        XCTAssertFalse(saved)
        let saveMessage = viewModel.saveErrorMessage
        XCTAssertNotNil(saveMessage)
        XCTAssertFalse(saveMessage?.hasPrefix(TodayViewModel.refreshFailedMessage) ?? true)

        api.categoriesResult = .success([pushups])
        await viewModel.load()

        XCTAssertEqual(viewModel.saveErrorMessage, saveMessage, "a refresh that works takes back its own line only")
    }

    func testALateFailureOfAnOldLoadSaysNothingWhenANewerLoadIsOnScreen() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([pushups])
        let viewModel = TodayViewModel(api: api, cacheStore: InMemoryCacheStore())
        await viewModel.load()
        var inFlight = false
        var gate: CheckedContinuation<Void, Never>?
        // L1 reads while the server refuses it (an error the cache does not cover with its copy) and waits
        // there; L2 reads after it and works.
        api.entriesResult = .failure(APIClientError.unauthorized)
        api.duringFetchEntries = {
            inFlight = true
            await withCheckedContinuation { gate = $0 }
        }
        let first = Task { await viewModel.load() }
        while !inFlight { await Task.yield() }
        api.entriesResult = .success([])
        await viewModel.load()
        XCTAssertNil(viewModel.saveErrorMessage)

        gate?.resume()
        await first.value

        XCTAssertNil(viewModel.saveErrorMessage, "the older read failed, but the screen already shows a newer answer")
        XCTAssertEqual(viewModel.state, .loaded)
    }

    /// A delivery during a load re-reads the records; that read says nothing about the categories and streaks
    /// the load is still after, so its success must not silence the load's failure.
    func testAFirstLoadThatFailsAfterAQuietRereadStillTurnsIntoTheErrorState() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([pushups])
        api.createEntryResult = .failure(APIClientError.timeout)
        let (first, outbox) = makeOfflineViewModel(api: api)
        await first.load()
        _ = await first.saveEntry(categoryID: 1, values: [10: "42"])
        let delivered = EntryDTO(id: 7, categoryId: 1, entryDate: Self.fixedToday, values: [EntryValueDTO(fieldId: 10, value: "42")])
        let viewModel = TodayViewModel(
            api: api, cacheStore: InMemoryCacheStore(), outbox: outbox,
            timeZone: TimeZone(identifier: "UTC")!, now: { self.makeFixedDate() }
        )
        let readsBefore = api.fetchedEntryRanges.count
        api.createEntryResult = .success(delivered)
        api.categoriesResult = .failure(APIClientError.unauthorized)
        api.duringCreateEntry = {
            await waitUntil { api.fetchedEntryRanges.count > readsBefore }
            api.entriesResult = .success([delivered])
        }
        // The categories answer only after the re-read reached the screen (yielding, never sleeping).
        api.duringFetchCategories = {
            for _ in 0..<5000 where viewModel.entries(forCategory: 1) != [delivered] { await Task.yield() }
        }

        await viewModel.load()

        XCTAssertEqual(viewModel.entries(forCategory: 1), [delivered], "the re-read did reach the screen first")
        XCTAssertEqual(viewModel.state, .failure(APIClientError.unauthorized.userMessage))
    }

    func testALateFailureOfAnOldFirstLoadDoesNotReplaceTheScreenANewerOneShowed() async {
        let api = MockTodayAPI()
        api.categoriesResult = .failure(APIClientError.unauthorized)
        let viewModel = TodayViewModel(api: api, cacheStore: InMemoryCacheStore())
        var inFlight = false
        var gate: CheckedContinuation<Void, Never>?
        api.duringFetchCategories = {
            inFlight = true
            await withCheckedContinuation { gate = $0 }
        }
        let first = Task { await viewModel.load() }
        while !inFlight { await Task.yield() }
        api.categoriesResult = .success([pushups])
        await viewModel.load()
        XCTAssertEqual(viewModel.state, .loaded)

        gate?.resume()
        await first.value

        XCTAssertEqual(viewModel.state, .loaded, "the older first load failed after a newer one showed the screen")
        XCTAssertEqual(viewModel.categories.map(\.id), [1])
    }

    func testAFailedSecondLoadOfAnEmptyScreenStillSaysSo() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([])
        let viewModel = TodayViewModel(api: api, cacheStore: InMemoryCacheStore())
        await viewModel.load()
        api.categoriesResult = .failure(APIClientError.unauthorized)

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertTrue(viewModel.categories.isEmpty)
        XCTAssertEqual(viewModel.saveErrorMessage, "\(TodayViewModel.refreshFailedMessage): \(APIClientError.unauthorized.userMessage)")
    }

    func testAFailedFirstLoadStillTurnsTheScreenIntoTheErrorState() async {
        let api = MockTodayAPI()
        api.categoriesResult = .failure(APIClientError.unauthorized)
        let viewModel = TodayViewModel(api: api, cacheStore: InMemoryCacheStore())

        await viewModel.load()

        XCTAssertEqual(viewModel.state, .failure(APIClientError.unauthorized.userMessage))
        XCTAssertNil(viewModel.saveErrorMessage)
    }

    func testAFailedBackgroundReReadSaysNothingNobodyAskedFor() async throws {
        let api = MockTodayAPI()
        api.categoriesResult = .success([pushups])
        api.createEntryResult = .failure(APIClientError.timeout)
        let (viewModel, outbox) = makeOfflineViewModel(api: api)
        await viewModel.load()
        _ = await viewModel.saveEntry(categoryID: 1, values: [10: "42"])
        let readsBefore = api.fetchedEntryRanges.count
        api.createEntryResult = .success(
            EntryDTO(id: 7, categoryId: 1, entryDate: Self.fixedToday, values: [EntryValueDTO(fieldId: 10, value: "42")])
        )
        api.entriesResult = .failure(APIClientError.timeout)

        let answeredBefore = api.entriesAnswered
        await outbox.flush()
        await waitUntil { api.entriesAnswered > answeredBefore }
        // The read has answered; its failure is handled on the main actor's next turns.
        for _ in 0..<10 { await Task.yield() }

        XCTAssertGreaterThan(api.fetchedEntryRanges.count, readsBefore, "the delivery did read the day again")
        XCTAssertNil(viewModel.saveErrorMessage, "nobody pressed anything: a failed quiet re-read is not their error")
    }

    func testAReadSentBeforeADeliveryDoesNotOverwriteTheReadAfterIt() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([pushups])
        api.createEntryResult = .failure(APIClientError.timeout)
        let cache = InMemoryCacheStore()
        let (viewModel, outbox) = makeOfflineViewModel(api: api, cache: cache)
        await viewModel.load()
        _ = await viewModel.saveEntry(categoryID: 1, values: [10: "42"])
        let delivered = EntryDTO(id: 7, categoryId: 1, entryDate: Self.fixedToday, values: [EntryValueDTO(fieldId: 10, value: "42")])
        let readsBefore = api.fetchedEntryRanges.count
        api.createEntryResult = .success(delivered)
        // The send waits until the load's read is on its way, then the server holds the entry.
        api.duringCreateEntry = {
            await waitUntil { api.fetchedEntryRanges.count > readsBefore }
            api.entriesResult = .success([delivered])
        }
        // The load's read was answered before the delivery; it returns only after the re-read did.
        api.duringFetchEntries = {
            await waitUntil { api.entriesAnswered > 0 && viewModel.entries(forCategory: 1) == [delivered] }
        }

        await viewModel.load()

        XCTAssertEqual(outbox.pendingCount, 0)
        XCTAssertEqual(viewModel.entries(forCategory: 1), [delivered], "the older answer would drop the delivered entry")
        XCTAssertEqual(
            cache.load(TodaySnapshot.self, forKey: TodayViewModel.cacheKey)?.value.entries, [delivered],
            "the cache keeps the newer records, not the older answer"
        )
        XCTAssertNil(viewModel.offlineAsOf)
    }

    func testASaveOfAChecklistStillWaitingGoesThroughTheQueueSoTheOldOneCannotLandLast() async {
        let api = MockTodayAPI()
        api.categoriesResult = .success([routine])
        api.upsertChecklistResult = .failure(APIClientError.timeout)
        let (viewModel, outbox) = makeOfflineViewModel(api: api)
        await viewModel.load()
        _ = await viewModel.saveEntry(categoryID: 2, values: [20: "false"])
        api.upsertChecklistResult = .success(
            EntryDTO(id: 200, categoryId: 2, entryDate: Self.fixedToday, values: [EntryValueDTO(fieldId: 20, value: "true")])
        )

        let saved = await viewModel.saveEntry(categoryID: 2, values: [20: "true"])

        XCTAssertTrue(saved)
        XCTAssertEqual(api.upsertedChecklists.map(\.values), [["20": false], ["20": true]], "the old one never follows the new")
        XCTAssertEqual(outbox.pendingCount, 0)
    }
}
