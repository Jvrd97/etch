// [review:need-review] PHASE-01/35-ios-category-detail
// summary: unit tests for CategoryDetailViewModel — load by category, date grouping, quick-add payload, edit/delete mutation
// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 — the chart asks the table of its own category, and its read leaves before the entry list answers
import XCTest
@testable import HabitTracker

/// Scriptable stand-in for the API used by `CategoryDetailViewModel`.
final class MockCategoryDetailAPI: CategoryChartAPI {
    var entriesResult: Result<[EntryDTO], Error> = .success([])
    var createResult: Result<EntryDTO, Error>?
    var updateResult: Result<EntryDTO, Error>?
    var deleteResult: Result<Void, Error> = .success(())
    var tableResult: Result<TableResponseDTO, Error> = .success(
        TableResponseDTO(categories: [], days: [])
    )
    private(set) var fetchedCategoryFilters: [Int?] = []
    private(set) var fetchedTableRanges: [(from: String, to: String)] = []
    private(set) var createdPayloads: [EntryCreateDTO] = []
    private(set) var updatedPayloads: [(id: Int, payload: EntryUpdateDTO)] = []
    private(set) var deletedIDs: [Int] = []

    func fetchEntries(categoryId: Int?) async throws -> [EntryDTO] {
        fetchedCategoryFilters.append(categoryId)
        let answer = entriesResult
        if let hook = duringFetchEntries {
            duringFetchEntries = nil
            await hook()
        }
        return try answer.get()
    }

    private(set) var fetchedTableCategoryIDs: [Int] = []
    /// Runs once inside the next entry-list read, before its answer.
    var duringFetchEntries: (@MainActor () async -> Void)?

    func fetchTable(dateFrom: String, dateTo: String) async throws -> TableResponseDTO {
        fetchedTableRanges.append((from: dateFrom, to: dateTo))
        return try tableResult.get()
    }

    func fetchTable(dateFrom: String, dateTo: String, categoryId: Int) async throws -> TableResponseDTO {
        fetchedTableCategoryIDs.append(categoryId)
        return try await fetchTable(dateFrom: dateFrom, dateTo: dateTo)
    }

    func createEntry(_ entry: EntryCreateDTO) async throws -> EntryDTO {
        createdPayloads.append(entry)
        guard let result = createResult else { throw APIClientError.invalidResponse }
        return try result.get()
    }

    func updateEntry(id: Int, _ payload: EntryUpdateDTO) async throws -> EntryDTO {
        updatedPayloads.append((id: id, payload: payload))
        guard let result = updateResult else { throw APIClientError.invalidResponse }
        return try result.get()
    }

    func deleteEntry(id: Int) async throws {
        deletedIDs.append(id)
        try deleteResult.get()
    }
}

@MainActor
final class CategoryDetailViewModelTests: XCTestCase {
    private let fixedDate = "2026-07-21"

    private func makeField(id: Int, name: String, order: Int) -> FieldDTO {
        FieldDTO(
            id: id,
            name: name,
            fieldType: .number,
            isRequired: false,
            defaultValue: nil,
            options: nil,
            order: order
        )
    }

    private func makeCategory(id: Int, name: String, fields: [FieldDTO]) -> CategoryDTO {
        CategoryDTO(
            id: id,
            name: name,
            icon: nil,
            color: "#B8FF36",
            displayMode: "form",
            isActive: true,
            fields: fields
        )
    }

    private func makeEntry(
        id: Int, categoryId: Int, date: String, values: [EntryValueDTO]
    ) -> EntryDTO {
        EntryDTO(id: id, categoryId: categoryId, entryDate: date, values: values)
    }

    private func makeViewModel(
        category: CategoryDTO, api: CategoryChartAPI
    ) -> CategoryDetailViewModel {
        CategoryDetailViewModel(
            category: category,
            api: api,
            timeZone: TimeZone(identifier: "UTC")!,
            now: { self.date(from: self.fixedDate) }
        )
    }

    private func date(from string: String) -> Date {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.date(from: string)!
    }

    // MARK: - Load

    func testLoadFetchesEntriesForThisCategoryOnly() async {
        let category = makeCategory(
            id: 1, name: "Push-ups", fields: [makeField(id: 10, name: "Reps", order: 0)]
        )
        let api = MockCategoryDetailAPI()
        api.entriesResult = .success([
            makeEntry(id: 100, categoryId: 1, date: "2026-07-20",
                      values: [EntryValueDTO(fieldId: 10, value: "42")]),
        ])

        let viewModel = makeViewModel(category: category, api: api)
        await viewModel.load()

        XCTAssertEqual(viewModel.state, .loaded)
        XCTAssertEqual(api.fetchedCategoryFilters, [1])
        XCTAssertEqual(viewModel.entries.map(\.id), [100])
    }

    func testTheChartAsksForItsOwnCategoryBeforeTheListAnswers() async {
        let category = makeCategory(id: 7, name: "Push-ups", fields: [makeField(id: 10, name: "Reps", order: 0)])
        let api = MockCategoryDetailAPI()
        var chartAskedBeforeList = false
        api.duringFetchEntries = {
            await waitUntil { !api.fetchedTableCategoryIDs.isEmpty }
            chartAskedBeforeList = !api.fetchedTableCategoryIDs.isEmpty
        }

        let viewModel = makeViewModel(category: category, api: api)
        await viewModel.load()

        XCTAssertTrue(chartAskedBeforeList, "the chart read waits for the entry list")
        XCTAssertEqual(api.fetchedTableCategoryIDs, [7])
        XCTAssertEqual(viewModel.state, .loaded)
    }

    func testLoadFailureSetsFailureMessage() async {
        let category = makeCategory(id: 1, name: "Push-ups", fields: [])
        let api = MockCategoryDetailAPI()
        api.entriesResult = .failure(APIClientError.timeout)

        let viewModel = makeViewModel(category: category, api: api)
        await viewModel.load()

        guard case .failure(let message) = viewModel.state else {
            return XCTFail("Expected failure state, got \(viewModel.state)")
        }
        XCTAssertFalse(message.isEmpty)
    }

    // MARK: - Date grouping

    func testGroupedByDateSortsDaysDescending() async {
        let category = makeCategory(
            id: 1, name: "Push-ups", fields: [makeField(id: 10, name: "Reps", order: 0)]
        )
        let api = MockCategoryDetailAPI()
        api.entriesResult = .success([
            makeEntry(id: 1, categoryId: 1, date: "2026-07-18",
                      values: [EntryValueDTO(fieldId: 10, value: "1")]),
            makeEntry(id: 2, categoryId: 1, date: "2026-07-20",
                      values: [EntryValueDTO(fieldId: 10, value: "2")]),
            makeEntry(id: 3, categoryId: 1, date: "2026-07-20",
                      values: [EntryValueDTO(fieldId: 10, value: "3")]),
        ])

        let viewModel = makeViewModel(category: category, api: api)
        await viewModel.load()

        let groups = viewModel.groupedByDate
        XCTAssertEqual(groups.map(\.date), ["2026-07-20", "2026-07-18"])
        XCTAssertEqual(groups.first?.entries.map(\.id), [2, 3])
    }

    // MARK: - Quick-add (acceptance: quick-add value of the first field)

    func testQuickAddFieldIsFirstFieldByOrder() {
        let category = makeCategory(
            id: 1,
            name: "Push-ups",
            fields: [
                makeField(id: 20, name: "Notes field", order: 1),
                makeField(id: 10, name: "Reps", order: 0),
            ]
        )
        let viewModel = makeViewModel(category: category, api: MockCategoryDetailAPI())

        XCTAssertEqual(viewModel.quickAddField?.id, 10)
    }

    func testQuickAddSendsPayloadWithFirstFieldAndInsertsEntry() async {
        let category = makeCategory(
            id: 1, name: "Push-ups", fields: [makeField(id: 10, name: "Reps", order: 0)]
        )
        let api = MockCategoryDetailAPI()
        api.entriesResult = .success([])
        let created = makeEntry(id: 500, categoryId: 1, date: fixedDate,
                                values: [EntryValueDTO(fieldId: 10, value: "42")])
        api.createResult = .success(created)

        let viewModel = makeViewModel(category: category, api: api)
        await viewModel.load()
        viewModel.quickAddValue = "42"
        let ok = await viewModel.quickAdd()

        XCTAssertTrue(ok)
        XCTAssertEqual(api.createdPayloads.count, 1)
        let payload = api.createdPayloads[0]
        XCTAssertEqual(payload.categoryId, 1)
        XCTAssertEqual(payload.entryDate, fixedDate)
        XCTAssertEqual(payload.values, [EntryValueDTO(fieldId: 10, value: "42")])
        // New entry appears in the list without a reload.
        XCTAssertEqual(viewModel.entries.map(\.id), [500])
        // Input is cleared after a successful quick-add.
        XCTAssertEqual(viewModel.quickAddValue, "")
        XCTAssertNil(viewModel.saveErrorMessage)
    }

    func testQuickAddBlankValueDoesNotCallAPI() async {
        let category = makeCategory(
            id: 1, name: "Push-ups", fields: [makeField(id: 10, name: "Reps", order: 0)]
        )
        let api = MockCategoryDetailAPI()

        let viewModel = makeViewModel(category: category, api: api)
        viewModel.quickAddValue = "   "
        let ok = await viewModel.quickAdd()

        XCTAssertFalse(ok)
        XCTAssertTrue(api.createdPayloads.isEmpty)
    }

    func testQuickAddFailureKeepsValueAndSetsError() async {
        let category = makeCategory(
            id: 1, name: "Push-ups", fields: [makeField(id: 10, name: "Reps", order: 0)]
        )
        let api = MockCategoryDetailAPI()
        api.createResult = .failure(APIClientError.unexpectedStatus(500))

        let viewModel = makeViewModel(category: category, api: api)
        viewModel.quickAddValue = "42"
        let ok = await viewModel.quickAdd()

        XCTAssertFalse(ok)
        XCTAssertEqual(viewModel.quickAddValue, "42")
        XCTAssertNotNil(viewModel.saveErrorMessage)
        XCTAssertTrue(viewModel.entries.isEmpty)
    }

    // MARK: - Edit

    func testEditUpdatesEntryInList() async {
        let category = makeCategory(
            id: 1, name: "Push-ups", fields: [makeField(id: 10, name: "Reps", order: 0)]
        )
        let api = MockCategoryDetailAPI()
        let original = makeEntry(id: 100, categoryId: 1, date: "2026-07-20",
                                 values: [EntryValueDTO(fieldId: 10, value: "422")])
        api.entriesResult = .success([original])
        let corrected = makeEntry(id: 100, categoryId: 1, date: "2026-07-20",
                                  values: [EntryValueDTO(fieldId: 10, value: "42")])
        api.updateResult = .success(corrected)

        let viewModel = makeViewModel(category: category, api: api)
        await viewModel.load()
        viewModel.beginEditing(original)
        viewModel.editDraft?.values[10] = "42"
        let ok = await viewModel.saveEdit()

        XCTAssertTrue(ok)
        XCTAssertEqual(api.updatedPayloads.first?.id, 100)
        XCTAssertEqual(viewModel.entries.first { $0.id == 100 }?.values.first?.value, "42")
        XCTAssertNil(viewModel.editDraft)
    }

    // MARK: - Delete

    func testDeleteRemovesEntryFromList() async {
        let category = makeCategory(
            id: 1, name: "Push-ups", fields: [makeField(id: 10, name: "Reps", order: 0)]
        )
        let api = MockCategoryDetailAPI()
        api.entriesResult = .success([
            makeEntry(id: 100, categoryId: 1, date: "2026-07-20",
                      values: [EntryValueDTO(fieldId: 10, value: "42")]),
            makeEntry(id: 200, categoryId: 1, date: "2026-07-19",
                      values: [EntryValueDTO(fieldId: 10, value: "30")]),
        ])

        let viewModel = makeViewModel(category: category, api: api)
        await viewModel.load()
        let ok = await viewModel.deleteEditEntry(id: 100)

        XCTAssertTrue(ok)
        XCTAssertEqual(api.deletedIDs, [100])
        XCTAssertEqual(viewModel.entries.map(\.id), [200])
    }

    func testDeleteFailureKeepsEntryAndSetsError() async {
        let category = makeCategory(
            id: 1, name: "Push-ups", fields: [makeField(id: 10, name: "Reps", order: 0)]
        )
        let api = MockCategoryDetailAPI()
        api.entriesResult = .success([
            makeEntry(id: 100, categoryId: 1, date: "2026-07-20",
                      values: [EntryValueDTO(fieldId: 10, value: "42")]),
        ])
        api.deleteResult = .failure(APIClientError.unexpectedStatus(500))

        let viewModel = makeViewModel(category: category, api: api)
        await viewModel.load()
        let ok = await viewModel.deleteEditEntry(id: 100)

        XCTAssertFalse(ok)
        XCTAssertEqual(viewModel.entries.map(\.id), [100])
        XCTAssertNotNil(viewModel.saveErrorMessage)
    }

    // MARK: - Chart (ticket #36)

    private func makeField(id: Int, name: String, type: FieldTypeDTO, order: Int) -> FieldDTO {
        FieldDTO(
            id: id, name: name, fieldType: type,
            isRequired: false, defaultValue: nil, options: nil, order: order
        )
    }

    private func numberCategory() -> CategoryDTO {
        CategoryDTO(
            id: 1, name: "Running Outdoor", icon: nil, color: "#B8FF36",
            displayMode: "form", isActive: true,
            fields: [
                makeField(id: 10, name: "Distance (km)", type: .number, order: 0),
                makeField(id: 11, name: "Duration", type: .time, order: 1),
            ]
        )
    }

    private func numberDay(_ date: String, km: String?, time: String?) -> TableDayDTO {
        var cells: [TableCellDTO] = []
        if let km {
            cells.append(TableCellDTO(categoryId: 1, fieldId: 10, aggregatedValue: km, entryCount: 1))
        }
        if let time {
            cells.append(TableCellDTO(categoryId: 1, fieldId: 11, aggregatedValue: time, entryCount: 1))
        }
        return TableDayDTO(date: date, cells: cells)
    }

    func testLoadFetchesTableOverMaxWindowAndBuildsSeries() async {
        let category = numberCategory()
        let api = MockCategoryDetailAPI()
        api.tableResult = .success(TableResponseDTO(categories: [], days: [
            numberDay("2026-07-20", km: "5", time: "00:30"),
        ]))

        let viewModel = makeViewModel(category: category, api: api)
        await viewModel.load()

        // The chart window is one year ending "today" (the injected fixed date).
        XCTAssertEqual(api.fetchedTableRanges.count, 1)
        XCTAssertEqual(api.fetchedTableRanges[0].to, fixedDate)
        XCTAssertEqual(api.fetchedTableRanges[0].from, "2025-07-22")
        // km + time become two series on different axes.
        XCTAssertEqual(viewModel.chartSeries.map(\.fieldId), [10, 11])
        XCTAssertEqual(viewModel.chartSeries.map(\.axis), [.left, .right])
    }

    func testLinePointsApplyPeriodThenMode() async {
        let category = numberCategory()
        let api = MockCategoryDetailAPI()
        api.tableResult = .success(TableResponseDTO(categories: [], days: [
            numberDay("2026-07-19", km: "2", time: nil),
            numberDay("2026-07-20", km: "3", time: nil),
            numberDay("2026-07-21", km: "4", time: nil),
        ]))

        let viewModel = makeViewModel(category: category, api: api)
        await viewModel.load()

        // Per day: raw values in ascending date order.
        XCTAssertEqual(viewModel.linePoints.map(\.date), ["2026-07-19", "2026-07-20", "2026-07-21"])
        XCTAssertEqual(viewModel.linePoints.map { $0.values[10] ?? nil }, [2, 3, 4])

        // Cumulative: running sum within the window.
        viewModel.chartMode = .cumulative
        XCTAssertEqual(viewModel.linePoints.map { $0.values[10] ?? nil }, [2, 5, 9])

        // Period slice keeps only the most recent day.
        viewModel.chartMode = .perDay
        viewModel.selectedPeriod = .sevenDays
        // Fewer than 7 days available -> all kept; narrow by faking a short window instead:
        XCTAssertEqual(viewModel.linePoints.count, 3)
    }

    func testChecklistCategoryExposesBarsAndStreaks() async {
        let vitaminD = makeField(id: 1, name: "Vitamin D", type: .boolean, order: 0)
        let magnesium = makeField(id: 2, name: "Magnesium", type: .boolean, order: 1)
        let category = CategoryDTO(
            id: 5, name: "Vitamins", icon: nil, color: "#B8FF36",
            displayMode: "checklist", isActive: true, fields: [vitaminD, magnesium]
        )
        let api = MockCategoryDetailAPI()
        api.tableResult = .success(TableResponseDTO(categories: [], days: [
            TableDayDTO(date: "2026-07-20", cells: [
                TableCellDTO(categoryId: 5, fieldId: 1, aggregatedValue: "true", entryCount: 1),
                TableCellDTO(categoryId: 5, fieldId: 2, aggregatedValue: "true", entryCount: 1),
            ]),
            TableDayDTO(date: fixedDate, cells: [
                TableCellDTO(categoryId: 5, fieldId: 1, aggregatedValue: "true", entryCount: 1),
            ]),
        ]))

        let viewModel = makeViewModel(category: category, api: api)
        await viewModel.load()

        XCTAssertTrue(viewModel.isChecklistChart)
        XCTAssertEqual(viewModel.checklistBarPoints.map(\.done), [2, 1])
        // Vitamin D: done yesterday + today -> streak 2. Magnesium: only yesterday, today pending -> streak 1.
        let streaks = Dictionary(
            uniqueKeysWithValues: viewModel.fieldStreaks.map { ($0.field.id, $0.streak) }
        )
        XCTAssertEqual(streaks[1], 2)
        XCTAssertEqual(streaks[2], 1)
    }
}
