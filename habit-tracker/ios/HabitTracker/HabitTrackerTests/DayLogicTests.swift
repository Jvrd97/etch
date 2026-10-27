// [review:need-review] PHASE-01/211, PHASE-03/226
// summary: pure-rule tests of the Day screen — typed value parsing (comma decimals, h:mm durations), progress/value/link-state texts, plan window text in a passed timezone (the device's by default, DST aware), day stepping, closing headline by stage
import SwiftUI
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

    // The server sends instants; the wall clock is the device's (decision of the owner,
    // as on the mobile web). Zones are passed in, so the machine's setting is irrelevant.
    private let berlin = TimeZone(identifier: "Europe/Berlin")!
    private let newYork = TimeZone(identifier: "America/New_York")!

    func testWindowIsReadOnTheWallClockOfTheGivenZone() {
        // 2026-10-25 05:00Z is 06:00 in Berlin (CET after the clocks went back that night).
        XCTAssertEqual(DayFormat.window(start: "2026-10-25T05:00:00Z", end: "2026-10-25T07:30:00Z", in: berlin), "06:00–08:30")
        XCTAssertEqual(DayFormat.window(start: "2026-10-25T05:00:00Z", end: nil, in: berlin), "06:00")
        XCTAssertNil(DayFormat.window(start: nil, end: nil, in: berlin))
        XCTAssertEqual(DayFormat.clock("2026-10-25T05:00:00.123456+00:00", in: berlin), "06:00")
        XCTAssertEqual(DayFormat.clock("2026-07-01T05:00:00Z", in: berlin), "07:00", "summer time")
    }

    func testTheSameInstantReadsDifferentlyInAnotherZoneAndNeverInTheRuleZone() {
        // The plan was written in Berlin; a reader in New York sees New York's clock.
        XCTAssertEqual(DayFormat.clock("2026-10-25T05:00:00Z", in: newYork), "01:00")
        XCTAssertEqual(DayFormat.window(start: "2026-10-25T05:00:00Z", end: "2026-10-25T07:30:00Z", in: newYork), "01:00–03:30")
        XCTAssertEqual(DayFormat.clock("2026-10-25T05:00:00Z", in: TimeZone(identifier: "UTC")!), "05:00")
    }

    func testDefaultZoneIsTheDevices() {
        let iso = "2026-10-25T05:00:00Z"
        XCTAssertEqual(DayFormat.clock(iso), DayFormat.clock(iso, in: .current))
    }

    func testUnreadableMomentGivesNoClock() {
        XCTAssertNil(DayFormat.clock("not a moment", in: berlin))
        XCTAssertNil(DayFormat.window(start: "2026-10-25T05:00:00", end: nil, in: berlin), "a moment without an offset is not guessed")
    }

    func testRepeatedClockReadsStayCorrectPerZone() {
        // Formatters are cached per zone: a read in one zone must not leak into the next.
        for _ in 0..<3 {
            XCTAssertEqual(DayFormat.clock("2026-10-25T05:00:00Z", in: berlin), "06:00")
            XCTAssertEqual(DayFormat.clock("2026-10-25T05:00:00Z", in: newYork), "01:00")
        }
    }

    func testMarkButtonNamesItsLineForVoiceOver() {
        XCTAssertEqual(DayFormat.markAccessibilityLabel(for: "Релиз iOS", state: "done"), "Отметка «Релиз iOS»: сделано")
        XCTAssertEqual(DayFormat.markAccessibilityLabel(for: "Релиз iOS", state: nil), "Отметка «Релиз iOS»: не отмечено")
    }

    func testTheScreenRereadsWhenTheSceneBecomesActiveFromAnyOtherPhase() {
        // SwiftUI reports .background -> .inactive -> .active, never .background -> .active.
        XCTAssertTrue(DayView.shouldReread(from: .inactive, to: .active))
        XCTAssertTrue(DayView.shouldReread(from: .background, to: .active))
        XCTAssertFalse(DayView.shouldReread(from: .active, to: .inactive))
        XCTAssertFalse(DayView.shouldReread(from: .background, to: .inactive))
        XCTAssertFalse(DayView.shouldReread(from: .active, to: .active))
    }

    func testAnchorsHintIsShownOnlyWhenTheDayHasAnchors() {
        XCTAssertFalse(DayFormat.showsAnchorsHint(nil))
        XCTAssertTrue(DayFormat.showsAnchorsHint(DayFixtures.summary()), "the fixture counts two anchors")
        let none = DaySummaryDTO(
            dayDate: DayFixtures.date, closed: false, stage: "open", reviewSkipped: false, verdict: nil,
            verdictReason: "", anchorsDone: 0, anchorsTotal: 0, tasksDone: 0, tasksTotal: 0,
            workMinutes: nil, streakAfter: nil, bodyMd: "", missingAnchors: [], clauses: []
        )
        XCTAssertFalse(DayFormat.showsAnchorsHint(none))
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

    // MARK: When a write also ticks the line (port of frontend/lib/plan-facts.test.ts)

    private func entry(_ id: Int, _ value: String) -> PlanFactEntryDTO {
        PlanFactEntryDTO(entryId: id, entryDate: "2026-10-25", values: [PlanFactValueDTO(fieldId: 70, value: value)])
    }

    private func linked(
        field: String = "number", target: Double? = 300, total: Double?, entries: [PlanFactEntryDTO] = []
    ) -> PlanItemFactsDTO {
        PlanItemFactsDTO(
            itemId: DayFixtures.pushupsID,
            link: PlanLinkDTO(
                categoryId: 7, categoryName: "К", categoryActive: true, fieldId: 70, fieldName: "П",
                fieldType: field, unit: "раз", targetValue: target, state: "ok", fields: []
            ),
            entries: entries, total: total, done: false, progress: "none"
        )
    }

    func testRecordTicksOnceTheTargetIsReachedNotBefore() {
        XCTAssertEqual(PlanFactLogic.markAfterRecord(linked(total: 200), value: .number(100)), "done")
        XCTAssertNil(PlanFactLogic.markAfterRecord(linked(total: 100), value: .number(100)))
    }

    func testRecordTicksALineWithoutATargetAndABoxSetToHappened() {
        XCTAssertEqual(PlanFactLogic.markAfterRecord(linked(target: nil, total: nil), value: .number(3)), "done")
        let box = linked(field: "boolean", target: nil, total: nil)
        XCTAssertEqual(PlanFactLogic.markAfterRecord(box, value: .flag(true)), "done")
        XCTAssertNil(PlanFactLogic.markAfterRecord(box, value: .flag(false)))
    }

    func testCorrectionCountsTheCorrectedEntryOnce() {
        let written = linked(total: 300, entries: [entry(7, "300")])
        XCTAssertEqual(PlanFactLogic.markAfterCorrect(written, entryID: 7, value: .number(200)), "unmark")
        XCTAssertEqual(PlanFactLogic.markAfterCorrect(written, entryID: 7, value: .number(300)), "done")
    }

    func testADoneLineCorrectedButStillAboveTheTargetStaysDone() {
        let written = linked(total: 300, entries: [entry(7, "300")])
        XCTAssertEqual(PlanFactLogic.markAfterCorrect(written, entryID: 7, value: .number(350)), "done")
    }

    func testAPartialLineCorrectedDownToSomethingShorterLeavesTheMarkBe() {
        let partial = linked(total: 200, entries: [entry(7, "200")])
        XCTAssertNil(PlanFactLogic.markAfterCorrect(partial, entryID: 7, value: .number(100)))
    }

    func testAMarkTheyPutOnAPartialSumIsTheirOwnCallAndSurvivesACorrection() {
        // Class of error from #200 round 3: 100 of 300 never backed "done", so a
        // ticked line means the person did it; 100 -> 120 must not take it back.
        let short = linked(total: 100, entries: [entry(7, "100")])
        XCTAssertNil(PlanFactLogic.markAfterCorrect(short, entryID: 7, value: .number(120)))

        let two = linked(total: 200, entries: [entry(7, "100"), entry(8, "100")])
        XCTAssertNil(PlanFactLogic.markAfterRemove(two, entryID: 7))

        let box = linked(field: "boolean", target: nil, total: nil, entries: [entry(7, "false")])
        XCTAssertNil(PlanFactLogic.markAfterCorrect(box, entryID: 7, value: .flag(false)))
        XCTAssertNil(PlanFactLogic.markAfterRemove(box, entryID: 7))
    }

    func testABoxCorrectedToNotHappenedTakesTheMarkBackUnlessAnotherEntryStillSaysHappened() {
        var box = linked(field: "boolean", target: nil, total: nil, entries: [entry(7, "true")])
        XCTAssertEqual(PlanFactLogic.markAfterCorrect(box, entryID: 7, value: .flag(false)), "unmark")

        box = linked(field: "boolean", target: nil, total: nil, entries: [entry(7, "true"), entry(8, "true")])
        XCTAssertNil(PlanFactLogic.markAfterCorrect(box, entryID: 7, value: .flag(false)))
    }

    func testADeleteTakesTheMarkBackOnceWhatIsLeftNoLongerDoesTheLine() {
        XCTAssertEqual(PlanFactLogic.markAfterRemove(linked(total: 300, entries: [entry(7, "300")]), entryID: 7), "unmark")

        var two = linked(total: 300, entries: [entry(7, "150"), entry(8, "150")])
        XCTAssertEqual(PlanFactLogic.markAfterRemove(two, entryID: 7), "unmark")
        two = linked(target: 100, total: 300, entries: [entry(7, "150"), entry(8, "150")])
        XCTAssertNil(PlanFactLogic.markAfterRemove(two, entryID: 7))

        let box = linked(field: "boolean", target: nil, total: nil, entries: [entry(7, "true")])
        XCTAssertEqual(PlanFactLogic.markAfterRemove(box, entryID: 7), "unmark")
    }
}
