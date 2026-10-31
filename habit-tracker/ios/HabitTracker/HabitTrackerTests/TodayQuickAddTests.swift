// [review:need-review] PHASE-03/294
// summary: the plus of a habit row — which plan a category gets (step, one-field sheet, full form), the shape of a step, the order of the cards by use over the day table (count, recency, stability, no read), and the month grid of the relapse date picker
import XCTest
@testable import HabitTracker

final class TodayQuickAddTests: XCTestCase {
    private func field(
        id: Int, type: FieldTypeDTO = .number, required: Bool = true, defaultValue: String? = nil,
        order: Int = 0, steps: [Double]? = nil
    ) -> FieldDTO {
        FieldDTO(
            id: id, name: "f\(id)", fieldType: type, isRequired: required, defaultValue: defaultValue,
            options: nil, order: order, quickSteps: steps
        )
    }

    private func category(
        id: Int = 1, fields: [FieldDTO], displayMode: String = "form", streakMode: String = "build"
    ) -> CategoryDTO {
        CategoryDTO(
            id: id, name: "c\(id)", icon: nil, color: nil, displayMode: displayMode,
            streakMode: streakMode, isActive: true, fields: fields
        )
    }

    // MARK: Plan

    func testOneNumberFieldWithAPositiveStepIsAOneTapStep() {
        let plan = TodayQuickAdd.plan(for: category(fields: [field(id: 10, steps: [-5, 10, 20])]))

        XCTAssertEqual(plan, .step(fieldID: 10, amount: 10), "the first positive step, in the order the person set")
    }

    func testANumberFieldWithoutStepsOrWithOnlyNegativeOnesAsksForTheAmount() {
        XCTAssertEqual(TodayQuickAdd.plan(for: category(fields: [field(id: 10)])), .amountSheet(fieldID: 10))
        XCTAssertEqual(
            TodayQuickAdd.plan(for: category(fields: [field(id: 10, steps: [-1, -5])])), .amountSheet(fieldID: 10)
        )
    }

    func testAnotherFieldThatCanBeLeftToItsDefaultDoesNotTakeTheSheetAway() {
        let withNote = category(fields: [
            field(id: 10, steps: [5]),
            field(id: 11, type: .text, required: false, order: 1),
            field(id: 12, type: .boolean, order: 2),
            field(id: 13, type: .select, defaultValue: "good", order: 3),
        ])

        // A step needs the number to be the only field; with others the person still sees one field.
        XCTAssertEqual(TodayQuickAdd.plan(for: withNote), .amountSheet(fieldID: 10))
        XCTAssertEqual(
            TodayQuickAdd.defaultValues(for: withNote, except: 10), [12: "false", 13: "good"]
        )
    }

    func testARequiredFieldWithNoDefaultLeavesTheFullForm() {
        let needsText = category(fields: [field(id: 10), field(id: 11, type: .text, order: 1)])

        XCTAssertEqual(TodayQuickAdd.plan(for: needsText), .fullForm)
    }

    func testASingleBoxIsATickAndAOneBoxChecklistToo() {
        XCTAssertEqual(
            TodayQuickAdd.plan(for: category(fields: [field(id: 10, type: .boolean)])), .check(fieldID: 10)
        )
        XCTAssertEqual(
            TodayQuickAdd.plan(for: category(fields: [field(id: 10, type: .boolean)], displayMode: "checklist")),
            .check(fieldID: 10)
        )
    }

    func testABoxWithOnlyOptionalFieldsBesideItIsStillATick() {
        let withNote = category(fields: [
            field(id: 10, type: .boolean), field(id: 11, type: .text, required: false, order: 1),
        ])

        XCTAssertEqual(TodayQuickAdd.plan(for: withNote), .check(fieldID: 10))
    }

    func testASingleTextFieldAsksForTheTextInASheet() {
        XCTAssertEqual(
            TodayQuickAdd.plan(for: category(fields: [field(id: 10, type: .text)])), .textSheet(fieldID: 10)
        )
    }

    func testTheFullFormIsLeftForSeveralFieldsThatMustBeFilledByHand() {
        let twoRequiredTexts = category(fields: [field(id: 10, type: .text), field(id: 11, type: .text, order: 1)])
        let twoRequiredBoxes = category(fields: [field(id: 10, type: .boolean), field(id: 11, type: .boolean, order: 1)])
        let longChecklist = category(
            fields: [field(id: 10, type: .boolean), field(id: 11, type: .boolean, order: 1)], displayMode: "checklist"
        )

        XCTAssertEqual(TodayQuickAdd.plan(for: twoRequiredTexts), .fullForm)
        XCTAssertEqual(TodayQuickAdd.plan(for: twoRequiredBoxes), .fullForm, "which box is not a guess")
        XCTAssertEqual(TodayQuickAdd.plan(for: longChecklist), .fullForm)
    }

    func testAvoidAndFieldlessCategoriesKeepTheFullForm() {
        XCTAssertEqual(
            TodayQuickAdd.plan(for: category(fields: [field(id: 10)], streakMode: "avoid")), .fullForm
        )
        XCTAssertEqual(
            TodayQuickAdd.plan(for: category(fields: [field(id: 10, type: .select)])), .fullForm
        )
        XCTAssertEqual(TodayQuickAdd.plan(for: category(fields: [])), .fullForm)
    }

    func testAStepIsWrittenWithoutATrailingZeroOrFloatNoise() {
        XCTAssertEqual(TodayQuickAdd.formatAmount(250), "250")
        XCTAssertEqual(TodayQuickAdd.formatAmount(0.5), "0.5")
        XCTAssertEqual(TodayQuickAdd.formatAmount(0.1 + 0.2), "0.3")
    }

    // MARK: Order by use

    private func table(_ days: [(String, [(category: Int, field: Int, count: Int)])]) -> TableResponseDTO {
        TableResponseDTO(
            categories: [],
            days: days.map { date, cells in
                TableDayDTO(
                    date: date,
                    cells: cells.map {
                        TableCellDTO(categoryId: $0.category, fieldId: $0.field, aggregatedValue: nil, entryCount: $0.count)
                    }
                )
            }
        )
    }

    func testUsageCountsAnEntryOncePerCategoryNotOncePerFieldCell() {
        let usage = TodayOrdering.usage(from: table([
            ("2026-07-22", [(1, 10, 2), (1, 11, 2), (2, 20, 1)]),
            ("2026-07-23", [(1, 10, 1), (1, 11, 0)]),
        ]))

        XCTAssertEqual(usage[1], CategoryUsage(entryCount: 3, lastEntryDate: "2026-07-23"))
        XCTAssertEqual(usage[2], CategoryUsage(entryCount: 1, lastEntryDate: "2026-07-22"))
    }

    func testTheMostFilledCardGoesFirstAndTheLatestFilledWinsATie() {
        let cards = [1, 2, 3, 4].map { category(id: $0, fields: []) }
        let usage: [Int: CategoryUsage] = [
            1: CategoryUsage(entryCount: 3, lastEntryDate: "2026-07-01"),
            2: CategoryUsage(entryCount: 9, lastEntryDate: "2026-06-30"),
            3: CategoryUsage(entryCount: 3, lastEntryDate: "2026-07-20"),
        ]

        XCTAssertEqual(
            TodayOrdering.sorted(cards, usage: usage).map(\.id), [2, 3, 1, 4],
            "4 was never filled: last, not alphabetical"
        )
    }

    func testTheOrderIsStableAndTheSameForTheSameInput() {
        let cards = [5, 3, 9, 1].map { category(id: $0, fields: []) }
        let usage: [Int: CategoryUsage] = [3: CategoryUsage(entryCount: 2, lastEntryDate: "2026-07-20")]

        let first = TodayOrdering.sorted(cards, usage: usage).map(\.id)
        let again = TodayOrdering.sorted(TodayOrdering.sorted(cards, usage: usage), usage: usage).map(\.id)

        XCTAssertEqual(first, [3, 5, 9, 1], "equal cards keep the order the server gave")
        XCTAssertEqual(again, first, "sorting a sorted list moves nothing")
    }

    func testWithoutAUsageReadTheServersOrderStands() {
        let cards = [5, 3, 9].map { category(id: $0, fields: []) }

        XCTAssertEqual(TodayOrdering.sorted(cards, usage: nil).map(\.id), [5, 3, 9])
    }

    // MARK: Month grid

    func testAMonthGridStartsOnTheMondayOfItsFirstDayAndFillsWholeWeeks() {
        let october = DayCalendar.month(containing: "2026-10-31")

        XCTAssertEqual(october.title, "Октябрь 2026")
        XCTAssertEqual(october.firstDay, "2026-10-01")
        XCTAssertEqual(october.cells.count % 7, 0)
        // 1 October 2026 is a Thursday: three blanks before it.
        XCTAssertEqual(Array(october.cells.prefix(4)), [nil, nil, nil, "2026-10-01"])
        XCTAssertEqual(october.cells.compactMap { $0 }.count, 31)
        XCTAssertEqual(october.cells.compactMap { $0 }.last, "2026-10-31")
    }

    func testMonthsStepAcrossTheYearAndFebruaryKnowsItsLeapDay() {
        XCTAssertEqual(DayCalendar.firstDay(ofMonthAfter: "2026-12-01"), "2027-01-01")
        XCTAssertEqual(DayCalendar.firstDay(ofMonthAfter: "2026-01-01", by: -1), "2025-12-01")
        XCTAssertEqual(DayCalendar.month(containing: "2024-02-10").cells.compactMap { $0 }.count, 29)
        XCTAssertEqual(DayCalendar.day("2026-03-01", plusDays: -1), "2026-02-28")
    }
}
