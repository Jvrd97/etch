// [review:need-review] PHASE-01/211
// summary: pure-rule tests of the Day screen — typed value parsing (comma decimals, h:mm durations), progress/value/link-state texts, plan window text in the rule's timezone (DST aware), day stepping, closing headline by stage
import XCTest
@testable import HabitTracker

final class DayLogicTests: XCTestCase {
    // MARK: Parsing

    func testNumbersAcceptACommaAsDecimalPoint() {
        XCTAssertEqual(PlanFactLogic.parseInput(fieldType: "number", "300"), 300)
        XCTAssertEqual(PlanFactLogic.parseInput(fieldType: "number", " 3,5 "), 3.5)
        XCTAssertNil(PlanFactLogic.parseInput(fieldType: "number", ""))
        XCTAssertNil(PlanFactLogic.parseInput(fieldType: "number", "abc"))
    }

    func testDurationsParseAsSeconds() {
        XCTAssertEqual(PlanFactLogic.parseInput(fieldType: "duration", "1:20"), 4800)
        XCTAssertEqual(PlanFactLogic.parseInput(fieldType: "duration", "45"), 2700)
        XCTAssertNil(PlanFactLogic.parseInput(fieldType: "duration", "1:75"))
        XCTAssertNil(PlanFactLogic.parseInput(fieldType: "duration", "1:2:3"))
        XCTAssertNil(PlanFactLogic.parseInput(fieldType: "duration", "-5"))
        XCTAssertEqual(PlanFactLogic.inputText(seconds: 4800), "1:20")
        XCTAssertEqual(PlanFactLogic.inputText(seconds: 300), "0:05")
    }

    // MARK: Texts

    private func facts(field: String, total: Double?, target: Double?, progress: String, done: Bool = true, unit: String? = "раз") -> PlanItemFactsDTO {
        PlanItemFactsDTO(
            itemId: DayFixtures.pushupsID,
            link: PlanLinkDTO(
                categoryId: 7, categoryName: "К", categoryActive: true, fieldId: 70, fieldName: "П",
                fieldType: field, unit: unit, targetValue: target, state: "ok", fields: []
            ),
            entries: [], total: total, done: done, progress: progress
        )
    }

    func testProgressKeepsTargetAndFactApart() {
        XCTAssertEqual(PlanFactLogic.progressText(facts(field: "number", total: nil, target: 300, progress: "none", done: false)), "Цель 300 раз, пока не записано")
        XCTAssertEqual(PlanFactLogic.progressText(facts(field: "number", total: 100, target: 300, progress: "partial")), "Сделано 100 из 300 раз")
        XCTAssertEqual(PlanFactLogic.progressText(facts(field: "number", total: 20, target: nil, progress: "recorded")), "Записано 20 раз")
        XCTAssertEqual(PlanFactLogic.progressText(facts(field: "duration", total: 5400, target: 7200, progress: "partial", unit: nil)), "Сделано 1 ч 30 мин из 2 ч")
        XCTAssertEqual(PlanFactLogic.progressText(facts(field: "boolean", total: nil, target: nil, progress: "recorded")), "Было")
    }

    func testValueTexts() {
        XCTAssertEqual(PlanFactLogic.valueText(fieldType: "number", raw: "100", unit: "раз"), "100 раз")
        XCTAssertEqual(PlanFactLogic.valueText(fieldType: "boolean", raw: "true", unit: nil), "было")
        XCTAssertEqual(PlanFactLogic.valueText(fieldType: "boolean", raw: "false", unit: nil), "не было")
        XCTAssertEqual(PlanFactLogic.valueText(fieldType: "duration", raw: "2700", unit: nil), "45 мин")
        XCTAssertEqual(PlanFactLogic.valueText(fieldType: "number", raw: nil, unit: nil), "—")
    }

    func testBrokenLinksSayWhy() {
        XCTAssertNil(PlanFactLogic.linkStateText("ok"))
        XCTAssertNotNil(PlanFactLogic.linkStateText("category_archived"))
        XCTAssertNotNil(PlanFactLogic.linkStateText("something_new"), "an unknown state still refuses, loudly")
    }

    // MARK: Dates and windows

    func testDaySteppingCrossesMonthAndYear() {
        XCTAssertEqual(DayFormat.shift("2026-10-31", by: 1), "2026-11-01")
        XCTAssertEqual(DayFormat.shift("2026-01-01", by: -1), "2025-12-31")
        XCTAssertNil(DayFormat.shift("not a date", by: 1))
    }

    func testWindowIsReadOnTheWallClockOfTheRuleZone() {
        // 2026-10-25 05:00Z is 06:00 in Berlin (CET after the clocks went back that night).
        XCTAssertEqual(DayFormat.window(start: "2026-10-25T05:00:00Z", end: "2026-10-25T07:30:00Z", timeZoneID: "Europe/Berlin"), "06:00–08:30")
        XCTAssertEqual(DayFormat.window(start: "2026-10-25T05:00:00Z", end: nil, timeZoneID: "Europe/Berlin"), "06:00")
        XCTAssertNil(DayFormat.window(start: nil, end: nil, timeZoneID: "Europe/Berlin"))
        XCTAssertEqual(DayFormat.clock("2026-10-25T05:00:00.123456+00:00", timeZoneID: "Europe/Berlin"), "06:00")
        XCTAssertEqual(DayFormat.clock("2026-07-01T05:00:00Z", timeZoneID: "Europe/Berlin"), "07:00", "summer time")
    }

    // MARK: Headlines

    func testHalfClosedDayReadsAsEarlyNotLost() {
        XCTAssertEqual(DayFormat.headline(DayFixtures.summary(stage: "reviewed", verdict: nil)), "Вердикт будет вечером")
        XCTAssertEqual(DayFormat.headline(DayFixtures.summary(stage: "open", verdict: nil)), "День не закрыт")
        XCTAssertEqual(DayFormat.headline(DayFixtures.summary(verdict: "won")), "День выигран")
        XCTAssertEqual(DayFormat.headline(DayFixtures.summary(verdict: "lost", reason: "tasks")), "День проигран")
        XCTAssertEqual(DayFormat.reasonLabel("overtime"), "переработка")
    }

    func testCountsLine() {
        XCTAssertEqual(DayFormat.countsLine(TaskCountsDTO(planned: 4, done: 2, failed: 1, skipped: 1, pending: 0)), "закрыто 2 из 4 · не сделано 1 · снято 1")
        XCTAssertEqual(DayFormat.countsLine(TaskCountsDTO(planned: 3, done: 0, failed: 0, skipped: 0, pending: 3)), "закрыто 0 из 3")
    }
}
