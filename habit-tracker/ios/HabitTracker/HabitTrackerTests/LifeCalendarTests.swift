// [review:need-review] PHASE-01/265
// summary: pure timeline rules — strict date parsing, ISO week codes at the year edges, the five square states and the week aggregate, the counter arithmetic of life.html, the history window
import XCTest
@testable import HabitTracker

final class LifeCalendarTests: XCTestCase {
    private func day(_ date: String, verdict: String?, done: Int = 0, total: Int = 0) -> LifeDayDTO {
        LifeDayDTO(date: date, title: "", verdict: verdict, verdictOrigin: "computed", done: done, total: total)
    }

    func testParseIsStrict() {
        XCTAssertNotNil(LifeCalendar.parse("2026-10-29"))
        XCTAssertNil(LifeCalendar.parse("2026-02-30"))
        XCTAssertNil(LifeCalendar.parse("2026-1-9"))
        XCTAssertNil(LifeCalendar.parse(""))
        XCTAssertEqual(LifeCalendar.iso(LifeCalendar.parse("2024-02-29")!), "2024-02-29")
    }

    func testIsoWeekCodeFollowsTheThursdayRule() {
        XCTAssertEqual(LifeCalendar.isoWeekCode(LifeCalendar.parse("2027-01-01")!), "2026-W53")
        XCTAssertEqual(LifeCalendar.isoWeekCode(LifeCalendar.parse("2026-08-24")!), "2026-W35")
        XCTAssertEqual(LifeCalendar.isoWeekCode(LifeCalendar.parse("2024-12-30")!), "2025-W01")
    }

    func testStartOfWeekIsMonday() {
        XCTAssertEqual(LifeCalendar.iso(LifeCalendar.startOfWeek(LifeCalendar.parse("2026-10-25")!)), "2026-10-19")
        XCTAssertEqual(LifeCalendar.iso(LifeCalendar.startOfWeek(LifeCalendar.parse("2026-10-19")!)), "2026-10-19")
    }

    func testMonthDatesCoverTheWholeMonth() {
        XCTAssertEqual(LifeCalendar.monthDates(LifeCalendar.parse("2024-02-10")!).count, 29)
        XCTAssertEqual(LifeCalendar.monthDates(LifeCalendar.parse("2026-10-31")!).count, 31)
    }

    func testDayStatusHasThreeRecordedStatesAndTwoCalendarOnes() {
        XCTAssertEqual(LifeCalendar.dayStatus(day("2026-10-20", verdict: "won"), date: "2026-10-20", today: "2026-10-29"), .won)
        XCTAssertEqual(LifeCalendar.dayStatus(day("2026-10-20", verdict: "lost"), date: "2026-10-20", today: "2026-10-29"), .lost)
        XCTAssertEqual(LifeCalendar.dayStatus(day("2026-10-20", verdict: nil), date: "2026-10-20", today: "2026-10-29"), .open)
        XCTAssertEqual(LifeCalendar.dayStatus(nil, date: "2026-10-20", today: "2026-10-29"), .empty)
        XCTAssertEqual(LifeCalendar.dayStatus(nil, date: "2026-10-30", today: "2026-10-29"), .future)
    }

    func testWeekIsWonWhenAnyDayWasAndLostOnlyWithoutAWin() {
        let monday = LifeCalendar.parse("2026-10-19")!
        let mixed = ["2026-10-19": day("2026-10-19", verdict: "lost"), "2026-10-20": day("2026-10-20", verdict: "won")]
        XCTAssertEqual(LifeCalendar.weekStatus(monday: monday, days: mixed, today: "2026-10-29"), .won)
        let lostOnly = ["2026-10-19": day("2026-10-19", verdict: "lost"), "2026-10-20": day("2026-10-20", verdict: nil)]
        XCTAssertEqual(LifeCalendar.weekStatus(monday: monday, days: lostOnly, today: "2026-10-29"), .lost)
        XCTAssertEqual(LifeCalendar.weekStatus(monday: monday, days: [:], today: "2026-10-29"), .empty)
        XCTAssertEqual(LifeCalendar.weekStatus(monday: LifeCalendar.parse("2026-11-02")!, days: [:], today: "2026-10-29"), .future)
        let tally = LifeCalendar.weekTally(monday: monday, days: mixed)
        XCTAssertEqual(tally.won, 1)
        XCTAssertEqual(tally.lost, 1)
    }

    func testCounterUsesTheArithmeticOfLifeHtml() {
        // Born 2000-05-11; 2026-10-29 is 9,667 days later = 1,381 whole weeks; 97 × 52.1775 rounds to 5,061.
        let counter = LifeCalendar.counter(frame: .standard, today: LifeCalendar.parse("2026-10-29")!)
        XCTAssertEqual(counter.years, 26)
        XCTAssertEqual(counter.weeksLived, 1381)
        XCTAssertEqual(counter.weeksTotal, 5061)
        XCTAssertEqual(counter.weeksLeft, 3680)
        XCTAssertEqual(counter.percent, 1381.0 / 5061.0 * 100, accuracy: 0.0001)
    }

    func testCounterNeverGoesNegativeOrPastHundred() {
        let old = LifeFrame(birth: "1900-01-01", targetYears: 10)
        let counter = LifeCalendar.counter(frame: old, today: LifeCalendar.parse("2026-10-29")!)
        XCTAssertEqual(counter.weeksLeft, 0)
        XCTAssertEqual(counter.percent, 100)
    }

    func testBirthdayNotYetReachedKeepsTheYounger() {
        let counter = LifeCalendar.counter(frame: LifeFrame(birth: "2000-12-31", targetYears: 97), today: LifeCalendar.parse("2026-10-29")!)
        XCTAssertEqual(counter.years, 25)
    }

    func testHistoryRangeIsThreeYearsBackToTheEndOfThisYear() {
        let range = LifeCalendar.historyRange(today: LifeCalendar.parse("2026-10-29")!)
        XCTAssertEqual(range.from, "2023-01-01")
        XCTAssertEqual(range.to, "2026-12-31")
    }
}
