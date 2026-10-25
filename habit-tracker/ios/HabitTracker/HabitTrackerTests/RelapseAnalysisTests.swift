// [review:need-review] PHASE-01/210
// summary: tests for the Swift port of the relapse analysis (#207) — trailing week/month counts, average gap, Monday-first weekday split, month-over-month trend, day/week buckets, labels; the cases mirror frontend/lib/relapse-analysis.test.ts
import XCTest
@testable import HabitTracker

final class RelapseAnalysisTests: XCTestCase {
    // A Saturday, so the weekday maths has something to get wrong.
    private let today = "2026-10-24"

    func testCountsRelapseDaysInTheTrailingWeekAndMonthTodayIncluded() {
        let summary = RelapseAnalysis.summarize(
            relapseDates: ["2026-09-24", "2026-09-25", "2026-10-18", "2026-10-24"],
            trackedSince: "2026-01-01",
            today: today
        )

        // 09-24 is 30 days before today and falls out; 09-25 is the first day in.
        XCTAssertEqual(summary.lastMonth, 3)
        // 10-18 is the first day of the week window.
        XCTAssertEqual(summary.lastWeek, 2)
    }

    func testCountsADayOnceHoweverManyRelapsesItHeld() {
        let summary = RelapseAnalysis.summarize(
            relapseDates: ["2026-10-24", "2026-10-24"], trackedSince: "2026-10-01", today: today
        )

        XCTAssertEqual(summary.lastWeek, 1)
        XCTAssertEqual(summary.weekdays.reduce(0, +), 1)
    }

    func testAveragesTheGapsBetweenConsecutiveRelapseDays() {
        let summary = RelapseAnalysis.summarize(
            relapseDates: ["2026-10-10", "2026-10-01", "2026-10-04"], trackedSince: nil, today: today
        )

        XCTAssertEqual(summary.averageGapDays, 4.5)
    }

    func testHasNoAverageGapBelowTwoRelapseDays() {
        XCTAssertNil(
            RelapseAnalysis.summarize(relapseDates: [], trackedSince: nil, today: today)
                .averageGapDays
        )
        XCTAssertNil(
            RelapseAnalysis.summarize(
                relapseDates: ["2026-10-01"], trackedSince: nil, today: today
            ).averageGapDays
        )
    }

    func testSplitsRelapseDaysByWeekdayMondayFirst() {
        // 2026-10-19 is a Monday, 10-24 a Saturday, 10-25 a Sunday, 10-12 a Monday.
        let summary = RelapseAnalysis.summarize(
            relapseDates: ["2026-10-19", "2026-10-24", "2026-10-25", "2026-10-12"],
            trackedSince: nil,
            today: "2026-10-25"
        )

        XCTAssertEqual(summary.weekdays, [2, 0, 0, 0, 0, 1, 1])
    }

    func testTrendSaysFewerMoreAndSame() {
        XCTAssertEqual(
            RelapseAnalysis.summarize(
                relapseDates: ["2026-08-30", "2026-09-01", "2026-09-10", "2026-10-20"],
                trackedSince: "2026-08-01",
                today: today
            ).trend,
            .fewer(current: 1, previous: 3)
        )
        XCTAssertEqual(
            RelapseAnalysis.summarize(
                relapseDates: ["2026-10-01", "2026-10-02"], trackedSince: "2026-08-01", today: today
            ).trend,
            .more(current: 2, previous: 0)
        )
        XCTAssertEqual(
            RelapseAnalysis.summarize(
                relapseDates: [], trackedSince: "2026-08-01", today: today
            ).trend,
            .same(current: 0, previous: 0)
        )
    }

    func testRefusesATrendUntilTheHistoryCoversTheMonthBeforeToo() {
        // The previous window starts on 2026-08-26; tracking began a day later.
        XCTAssertEqual(
            RelapseAnalysis.summarize(
                relapseDates: ["2026-10-01"], trackedSince: "2026-08-27", today: today
            ).trend,
            .notEnoughData
        )
        XCTAssertEqual(
            RelapseAnalysis.summarize(
                relapseDates: ["2026-10-01"], trackedSince: "2026-08-26", today: today
            ).trend,
            .more(current: 1, previous: 0)
        )
        XCTAssertEqual(
            RelapseAnalysis.summarize(relapseDates: [], trackedSince: nil, today: today).trend,
            .notEnoughData
        )
    }

    func testTimelineDrawsOneBarPerDayUpToNinetyDaysEndingToday() {
        let timeline = RelapseAnalysis.timeline(
            relapseDates: ["2026-10-01", "2026-10-24", "2026-09-01"],
            trackedSince: nil,
            today: today,
            period: .days30
        )

        XCTAssertEqual(timeline.granularity, .day)
        XCTAssertEqual(timeline.buckets.count, 30)
        XCTAssertEqual(timeline.buckets.first?.start, "2026-09-25")
        XCTAssertEqual(
            timeline.buckets.last, RelapseBucket(start: today, end: today, relapseDays: 1)
        )
        XCTAssertEqual(
            timeline.buckets.filter { $0.relapseDays > 0 }.map(\.start),
            ["2026-10-01", "2026-10-24"]
        )
    }

    func testTimelineSwitchesToMondayWeeksPastNinetyDaysAndCountsOnlyDaysOfThePeriod() {
        let timeline = RelapseAnalysis.timeline(
            relapseDates: ["2025-10-24", "2025-10-25", "2026-10-19", "2026-10-20", "2026-10-24"],
            trackedSince: nil,
            today: today,
            period: .days365
        )

        XCTAssertEqual(timeline.granularity, .week)
        // The period starts on Saturday 2025-10-25: the first week starts on Monday 10-20 and
        // holds only 10-25, because 10-24 is a day before the period.
        XCTAssertEqual(
            timeline.buckets.first,
            RelapseBucket(start: "2025-10-20", end: "2025-10-26", relapseDays: 1)
        )
        XCTAssertEqual(
            timeline.buckets.last,
            RelapseBucket(start: "2026-10-19", end: "2026-10-25", relapseDays: 3)
        )
        XCTAssertEqual(timeline.buckets.map(\.relapseDays).reduce(0, +), 4)
    }

    func testTimelineForAllTimeStartsAtTheFirstTrackedDayOrTheFirstRelapse() {
        let fromTracking = RelapseAnalysis.timeline(
            relapseDates: ["2026-10-20"], trackedSince: "2026-10-10", today: today, period: .all
        )
        XCTAssertEqual(fromTracking.buckets.first?.start, "2026-10-10")
        XCTAssertEqual(fromTracking.buckets.count, 15)

        let fromRelapse = RelapseAnalysis.timeline(
            relapseDates: ["2026-10-05"], trackedSince: "2026-10-10", today: today, period: .all
        )
        XCTAssertEqual(fromRelapse.buckets.first?.start, "2026-10-05")

        let empty = RelapseAnalysis.timeline(
            relapseDates: [], trackedSince: nil, today: today, period: .all
        )
        XCTAssertEqual(empty.buckets, [RelapseBucket(start: today, end: today, relapseDays: 0)])
    }

    func testLabelsReadTheSameOnEveryMachine() {
        XCTAssertEqual(RelapseAnalysis.formatDay("2026-10-05"), "5 окт 2026")
        XCTAssertEqual(RelapseAnalysis.formatWeekday("2026-10-05"), "Пн")
        XCTAssertEqual(RelapseAnalysis.formatWeekday("2026-10-04"), "Вс")
        XCTAssertEqual(RelapseAnalysis.formatDayCount(1), "1 день")
        XCTAssertEqual(RelapseAnalysis.formatDayCount(4), "4 дня")
        XCTAssertEqual(RelapseAnalysis.formatDayCount(11), "11 дней")
        XCTAssertEqual(RelapseAnalysis.formatDayCount(21), "21 день")
        XCTAssertEqual(RelapseAnalysis.formatGap(17), "17 дней")
        XCTAssertEqual(RelapseAnalysis.formatGap(4.5), "4,5 дня")
    }

    func testDayNumbersRoundTripAcrossLeapYearsAndTheEpoch() {
        for iso in ["1970-01-01", "2024-02-29", "2026-10-25", "2027-03-01"] {
            XCTAssertEqual(RelapseAnalysis.isoDate(of: RelapseAnalysis.dayNumber(of: iso)), iso)
        }
        XCTAssertEqual(RelapseAnalysis.dayNumber(of: "1970-01-02"), 1)
    }
}
