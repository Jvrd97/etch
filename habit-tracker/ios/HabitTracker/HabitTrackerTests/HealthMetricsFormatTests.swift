// [review:need-review] PHASE-01/268
// summary: tests of the Health screens' vocabulary — units in Russian (no `count`, `count/min`; cadence is «об/мин»), values, deviation text, calendar-day arithmetic, the 24 hour slots, sparkline gaps, sleep and workout lines, and the sync/lag verdict (under an hour, N hours, a day-old warning, interrupted run, never synced, failed run)
import XCTest
@testable import HabitTracker

final class HealthMetricsFormatTests: XCTestCase {
    private func baseline(deviation: Double, day: String = "2026-10-29", outside: Bool = false) -> HealthBaselineDTO {
        HealthBaselineDTO(mean: 10, stddev: 2, days: 20, day: day, deviation: deviation, outsideTypical: outside)
    }

    func testUnitsNeverShowRawHealthKitWords() {
        let steps = "HKQuantityTypeIdentifierStepCount"
        XCTAssertEqual(HealthMetricsFormat.formatQuantity(identifier: steps, value: 4321, unit: "count"), "4321 шагов")
        XCTAssertEqual(HealthMetricsFormat.unitLabel(identifier: "HKQuantityTypeIdentifierHeartRate", unit: "count/min"), "уд/мин")
        XCTAssertEqual(HealthMetricsFormat.unitLabel(identifier: "HKQuantityTypeIdentifierRespiratoryRate", unit: "count/min"), "дых/мин")
        XCTAssertEqual(HealthMetricsFormat.unitLabel(identifier: "HKQuantityTypeIdentifierCyclingCadence", unit: "count/min"), "об/мин")
        XCTAssertEqual(HealthMetricsFormat.formatQuantity(identifier: "HKQuantityTypeIdentifierNumberOfTimesFallen", value: 3, unit: "count"), "3")
        XCTAssertEqual(HealthMetricsFormat.formatQuantity(identifier: "x", value: 67.34, unit: "kg"), "67.3 кг")
        XCTAssertEqual(HealthMetricsFormat.unitLabel(identifier: "x", unit: "W"), "Вт")
    }

    func testValueKeepsOneDecimalAtMost() {
        XCTAssertEqual(HealthMetricsFormat.formatValue(5), "5")
        XCTAssertEqual(HealthMetricsFormat.formatValue(5.04), "5")
        XCTAssertEqual(HealthMetricsFormat.formatValue(5.26), "5.3")
    }

    func testDeviationNamesDirectionUnitAndSitsOnMean() {
        XCTAssertEqual(HealthMetricsFormat.deviationText(baseline(deviation: 0.4), identifier: "x", unit: "kg"), "+0.4 кг к обычному")
        XCTAssertEqual(HealthMetricsFormat.deviationText(baseline(deviation: -1200), identifier: "HKQuantityTypeIdentifierStepCount", unit: "count"), "−1200 шагов к обычному")
        XCTAssertEqual(HealthMetricsFormat.deviationText(baseline(deviation: 0.02), identifier: "x", unit: "kg"), "как обычно")
        XCTAssertEqual(HealthMetricsFormat.deviationText(baseline(deviation: 3), identifier: "HKQuantityTypeIdentifierNumberOfTimesFallen", unit: "count"), "+3 к обычному")
    }

    func testDatesShiftOnTheCalendarAndPrintInRussian() {
        XCTAssertEqual(HealthMetricsFormat.shiftDate("2026-03-01", by: -1), "2026-02-28")
        XCTAssertEqual(HealthMetricsFormat.shiftDate("2026-10-29", by: -29), "2026-09-30")
        XCTAssertEqual(HealthMetricsFormat.dayLabel("2026-10-20"), "20 окт.")
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Europe/Moscow")!
        // 2026-10-29 22:30 UTC is already the 30th in Moscow.
        let moment = Date(timeIntervalSince1970: 1_793_313_000)
        XCTAssertEqual(HealthMetricsFormat.localDate(moment, calendar: calendar), "2026-10-30")
    }

    func testSparklineKeepsAGapAsAGapAndIsEmptyWithoutDays() {
        let days = [HealthDayValueDTO(date: "2026-10-27", value: 1), HealthDayValueDTO(date: "2026-10-29", value: 3)]
        XCTAssertEqual(HealthMetricsFormat.sparklinePoints(days, endDate: "2026-10-29", count: 4), [nil, 1, nil, 3])
        XCTAssertEqual(HealthMetricsFormat.sparklinePoints([], endDate: "2026-10-29"), [])
        XCTAssertEqual(HealthMetricsFormat.sparklinePoints(days, endDate: "2026-10-29").count, 30)
    }

    func testHoursFillTwentyFourSlotsWithNilForAnHourWithoutData() {
        let eight = HealthHourValueDTO(hour: 8, value: 5, min: 5, max: 5, sampleCount: 1)
        let eighteen = HealthHourValueDTO(hour: 18, value: 55, min: 50, max: 60, sampleCount: 4)
        let slots = HealthMetricsFormat.hourSlots([eighteen, eight])
        XCTAssertEqual(slots.count, 24)
        XCTAssertEqual(slots[8], eight)
        XCTAssertEqual(slots[18], eighteen)
        XCTAssertNil(slots[9])
        XCTAssertEqual(HealthMetricsFormat.hourLabel(8), "08:00")
        XCTAssertNil(HealthMetricsFormat.hourRange(eight))
        XCTAssertEqual(HealthMetricsFormat.hourRange(eighteen), "50–60")
    }

    func testSleepAndWorkoutLines() {
        XCTAssertEqual(HealthMetricsFormat.sleepDuration(430), "7 ч 10 мин")
        XCTAssertEqual(HealthMetricsFormat.sleepDuration(420), "7 ч")
        XCTAssertEqual(HealthMetricsFormat.sleepDuration(45), "45 мин")
        XCTAssertEqual(HealthMetricsFormat.wallClock("2026-10-29T23:40:00-04:00"), "23:40")
        XCTAssertEqual(HealthMetricsFormat.workoutDistance(7200), "7,2 км")
        XCTAssertEqual(HealthMetricsFormat.workoutDistance(850), "850 м")
        let workout = HealthWorkoutRecordDTO(
            id: "w", activityType: "running", activityLabel: "Бег", date: "2026-10-29",
            start: "2026-10-29T18:00:00+03:00", end: "2026-10-29T18:40:00+03:00", durationMin: 40,
            energyKcal: 320.4, distanceM: 7200, avgHeartRate: nil, maxHeartRate: 171
        )
        XCTAssertEqual(HealthMetricsFormat.workoutDetails(workout), ["7,2 км", "320 ккал", "макс. 171"])
    }

    func testSleepStagesLeaveZeroRowsOut() {
        let night = HealthSleepNightDTO(
            date: "2026-10-29", bedtime: "2026-10-28T23:10:00+03:00", wakeTime: "2026-10-29T07:00:00+03:00",
            inBedMin: 0, asleepMin: 430, awakeMin: 20, coreMin: 250, deepMin: 90, remMin: 90, unspecifiedMin: 0
        )
        XCTAssertEqual(HealthMetricsFormat.sleepStages(night).map(\.label), ["Основной", "Глубокий", "REM", "Бодрствование"])
    }

    // MARK: Sync block

    private func run(status: String = "ok", failure: String? = nil) -> HealthSyncRunDTO {
        HealthSyncRunDTO(
            syncRunId: "r", kind: "rolling", status: status, interrupted: false, failureKind: failure,
            startedAt: "2026-10-29T10:00:00Z", finishedAt: nil, samplesReceived: 0, bucketsWritten: 0, chunksDone: 0, chunksTotal: nil
        )
    }

    private func status(lag: Double?, interrupted: Bool = false, runs: [HealthSyncRunDTO] = []) -> HealthSyncStatusDTO {
        HealthSyncStatusDTO(lastRuns: runs, lastSuccessAt: nil, lagHours: lag, interrupted: interrupted)
    }

    func testLagUnderAnHourIsNotAWarning() {
        let verdict = HealthMetricsFormat.syncVerdict(status(lag: 0.4, runs: [run()]))
        XCTAssertEqual(verdict, .init(text: "Последний синк: меньше часа назад", detail: nil, warn: false))
    }

    func testLagInWholeHoursAndAWarningFromADay() {
        XCTAssertEqual(HealthMetricsFormat.syncVerdict(status(lag: 5.9)).text, "Последний синк: отставание 5 ч")
        XCTAssertFalse(HealthMetricsFormat.syncVerdict(status(lag: 5.9)).warn)
        let day = HealthMetricsFormat.syncVerdict(status(lag: 24.2))
        XCTAssertEqual(day.text, "Последний синк: отставание 24 ч")
        XCTAssertTrue(day.warn)
    }

    func testAnInterruptedRunIsNamedAsAbandoned() {
        let verdict = HealthMetricsFormat.syncVerdict(status(lag: 3, interrupted: true))
        XCTAssertEqual(verdict.text, "Последний синк оборван — отставание 3 ч")
        XCTAssertTrue(verdict.warn)
        XCTAssertNotNil(verdict.detail)
    }

    func testNeverSyncedAndAFailedRunAreWarningsWithTheClassOfFailure() {
        let never = HealthMetricsFormat.syncVerdict(status(lag: nil, runs: [run(status: "failed", failure: "network")]))
        XCTAssertEqual(never.text, "Синк ещё не проходил")
        XCTAssertEqual(never.detail, "Последний прогон не удался: нет связи с сервером")
        XCTAssertTrue(never.warn)
        let failed = HealthMetricsFormat.syncVerdict(status(lag: 2, runs: [run(status: "failed", failure: nil)]))
        XCTAssertEqual(failed.detail, "Последний прогон не удался: причина неизвестна")
        XCTAssertTrue(failed.warn)
    }

    // MARK: Groups and rows

    private func metric(_ id: String, group: String, days: [HealthDayValueDTO] = [], baseline: HealthBaselineDTO? = nil, unit: String = "kg") -> HealthMetricSeriesDTO {
        HealthMetricSeriesDTO(identifier: id, displayName: id, group: group, kind: "discrete", canonicalUnit: unit, days: days, baseline: baseline)
    }

    func testAGroupTheAppDoesNotKnowIsFiledUnderOther() {
        let all = [metric("a", group: "body"), metric("b", group: "other"), metric("c", group: "future")]
        XCTAssertEqual(HealthMetricsFormat.metrics(of: "other", in: all).map(\.identifier), ["b", "c"])
        XCTAssertEqual(HealthMetricsFormat.metrics(of: "body", in: all).map(\.identifier), ["a"])
    }

    func testRowSaysNoDataForAMetricWithoutDays() {
        XCTAssertNil(HealthMetricRowText(metric("a", group: "body"), today: "2026-10-29"))
    }

    func testRowNamesTheDayWhenItIsNotTodayAndTheBaselineDayWhenItDiffers() {
        let days = [HealthDayValueDTO(date: "2026-10-27", value: 68.4)]
        let row = HealthMetricRowText(
            metric("a", group: "body", days: days, baseline: baseline(deviation: 0.4, day: "2026-10-26", outside: true)),
            today: "2026-10-29"
        )
        XCTAssertEqual(row?.value, "68.4 кг")
        XCTAssertEqual(row?.dateNote, "27 окт.")
        XCTAssertEqual(row?.deviation, "26 окт.: +0.4 кг к обычному, вне обычного")
        XCTAssertEqual(row?.outsideTypical, true)
    }

    func testRowOfTodayHasNoDateNoteAndNoBaselineNoDeviation() {
        let days = [HealthDayValueDTO(date: "2026-10-29", value: 3)]
        let row = HealthMetricRowText(metric("a", group: "body", days: days), today: "2026-10-29")
        XCTAssertNil(row?.dateNote)
        XCTAssertNil(row?.deviation)
    }
}
