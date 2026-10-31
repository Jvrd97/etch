// [review:need-review] PHASE-03/305
// summary: tests of what the Health screen shows from data it already has — the words of the index, tone of a deviation by the direction of «better», the share of key metrics not worse than the norm, deviation bars around zero, 7-night sleep bars with a gap kept as a gap and the best night, tiles, workouts grouped by type with only the numbers HealthKit held
import XCTest
@testable import HabitTracker

final class HealthOverviewTests: XCTestCase {
    private let rhr = "HKQuantityTypeIdentifierRestingHeartRate"
    private let hrv = "HKQuantityTypeIdentifierHeartRateVariabilitySDNN"
    private let breathing = "HKQuantityTypeIdentifierRespiratoryRate"
    private let steps = "HKQuantityTypeIdentifierStepCount"
    private let energy = "HKQuantityTypeIdentifierActiveEnergyBurned"

    private func metric(
        _ id: String, name: String = "M", unit: String = "count", mean: Double = 100, deviation: Double?,
        days: [(String, Double)] = [("2026-10-29", 1)]
    ) -> HealthMetricSeriesDTO {
        HealthMetricSeriesDTO(
            identifier: id, displayName: name, group: "heart", kind: "discrete", canonicalUnit: unit,
            days: days.map { HealthDayValueDTO(date: $0.0, value: $0.1) },
            baseline: deviation.map {
                HealthBaselineDTO(mean: mean, stddev: 1, days: 20, day: "2026-10-29", deviation: $0, outsideTypical: false)
            }
        )
    }

    // MARK: State words

    func testTheIndexIsNamedByTheServersLabel() {
        XCTAssertEqual(HealthOverview.stateWord("good"), "Хорошее")
        XCTAssertEqual(HealthOverview.stateWord("fair"), "Среднее")
        XCTAssertEqual(HealthOverview.stateWord("poor"), "Низкое")
        XCTAssertNil(HealthOverview.stateWord("brand-new"), "an unknown label shows no word instead of a guess")
        XCTAssertNil(HealthOverview.stateWord(nil))
    }

    func testTheIndexAndItsBasisAreHonestAboutDays() {
        XCTAssertEqual(HealthOverview.indexText(78), "78 из 100")
        XCTAssertEqual(HealthOverview.basisText(1), "по 1 дню")
        XCTAssertEqual(HealthOverview.basisText(3), "по 3 дням")
        XCTAssertEqual(HealthOverview.basisText(7), "по 7 дням")
        XCTAssertEqual(HealthOverview.basisText(11), "по 11 дням")
        XCTAssertEqual(HealthOverview.basisText(21), "по 21 дню")
    }

    // MARK: Tone and share in the norm

    func testToneFollowsTheDirectionOfBetter() {
        XCTAssertEqual(HealthOverview.tone(deviation: -2, higherIsBetter: false), .better, "a lower resting pulse is better")
        XCTAssertEqual(HealthOverview.tone(deviation: 2, higherIsBetter: false), .worse)
        XCTAssertEqual(HealthOverview.tone(deviation: 5, higherIsBetter: true), .better)
        XCTAssertEqual(HealthOverview.tone(deviation: -5, higherIsBetter: true), .worse)
        XCTAssertEqual(HealthOverview.tone(deviation: 0.04, higherIsBetter: true), .same, "it prints as «как обычно»")
    }

    func testTheShareInTheNormCountsOnlyMetricsWithABaselineAndNotWorse() {
        let metrics = [
            metric(rhr, deviation: -2),                 // better
            metric(hrv, deviation: -6),                 // worse
            metric(steps, deviation: 0),                // same: not worse
            metric(energy, deviation: nil),             // no baseline: not judged
            metric("HKQuantityTypeIdentifierBodyMass", deviation: 3), // not a key metric
        ]
        let share = HealthOverview.normShare(metrics)
        XCTAssertEqual(share.inNorm, 2)
        XCTAssertEqual(share.judged, 3)
    }

    func testNoJudgedMetricsMeansNoShare() {
        let share = HealthOverview.normShare([metric(rhr, deviation: nil)])
        XCTAssertEqual(share.judged, 0)
        XCTAssertNil(share.fraction)
    }

    // MARK: Deviation bars

    func testDeviationBarsAreFixedMetricsInOrderWithTheirTone() {
        let metrics = [
            metric(hrv, name: "ВСР", unit: "ms", mean: 50, deviation: 5),
            metric(rhr, name: "Пульс покоя", unit: "count/min", mean: 60, deviation: 3),
            metric(breathing, name: "Дыхание", mean: 15, deviation: -0.5),
            metric(steps, deviation: 100),
        ]
        let bars = HealthOverview.deviationBars(metrics)
        XCTAssertEqual(bars.map(\.title), ["Пульс покоя", "ВСР", "Дыхание"])
        XCTAssertEqual(bars.map(\.tone), [.worse, .better, .better])
        XCTAssertEqual(bars[0].text, "+3 уд/мин к обычному")
        XCTAssertEqual(bars[1].share, 0.1 / HealthOverview.deviationAxis, accuracy: 1e-9, "5 on a norm of 50 is 10 %")
        XCTAssertLessThan(bars[2].share, 0)
    }

    func testABarNeverLeavesTheAxisAndSkipsAMetricWithoutANorm() {
        let metrics = [
            metric(rhr, mean: 60, deviation: 60),
            metric(hrv, deviation: nil),
            metric(breathing, mean: 0, deviation: 1),
        ]
        let bars = HealthOverview.deviationBars(metrics)
        XCTAssertEqual(bars.count, 1)
        XCTAssertEqual(bars[0].share, 1)
    }

    // MARK: Sleep bars

    private func night(_ date: String, asleep: Double, deep: Double = 0, rem: Double = 0) -> HealthSleepNightDTO {
        HealthSleepNightDTO(
            date: date, bedtime: "\(date)T00:10:00+03:00", wakeTime: "\(date)T07:20:00+03:00",
            inBedMin: 0, asleepMin: asleep, awakeMin: 0, coreMin: asleep - deep - rem, deepMin: deep, remMin: rem, unspecifiedMin: 0
        )
    }

    func testSevenNightsEndingTodayKeepAMissingNightAsAGap() {
        let nights = [night("2026-10-23", asleep: 400), night("2026-10-25", asleep: 480, deep: 60, rem: 90), night("2026-10-29", asleep: 420)]
        let bars = HealthOverview.sleepBars(nights, today: "2026-10-29")
        XCTAssertEqual(bars.map(\.date), (23...29).map { "2026-10-\($0)" })
        XCTAssertEqual(bars.map(\.hasData), [true, false, true, false, false, false, true])
        XCTAssertEqual(bars[2].deepRemMin, 150)
        XCTAssertEqual(bars[2].lightMin, 330)
        XCTAssertEqual(bars.map(\.weekday), ["пт", "сб", "вс", "пн", "вт", "ср", "чт"])
    }

    func testTheBestNightIsTheLongestAndTheLaterOneWinsATie() {
        let nights = [night("2026-10-26", asleep: 450), night("2026-10-27", asleep: 450), night("2026-10-28", asleep: 300)]
        let bars = HealthOverview.sleepBars(nights, today: "2026-10-29")
        XCTAssertEqual(bars.filter(\.isBest).map(\.date), ["2026-10-27"])
    }

    func testNoNightsMeansNoBestAndNoData() {
        let bars = HealthOverview.sleepBars([], today: "2026-10-29")
        XCTAssertEqual(bars.count, 7)
        XCTAssertTrue(bars.allSatisfy { !$0.hasData && !$0.isBest })
    }

    func testStageMinutesNeverExceedTheNightWhenTheStagesAreMissing() {
        let bars = HealthOverview.sleepBars([night("2026-10-29", asleep: 400)], today: "2026-10-29")
        XCTAssertEqual(bars[6].deepRemMin, 0)
        XCTAssertEqual(bars[6].lightMin, 400)
    }

    // MARK: Tiles

    func testATileHoldsTheLatestValueTheNormNoteAndAGapKeepingLine() {
        let steps = metric(
            steps, name: "Шаги", mean: 8000, deviation: 1200,
            days: [("2026-10-27", 7000), ("2026-10-29", 9200)]
        )
        let tile = HealthOverview.tile(steps, today: "2026-10-29", higherIsBetter: true)
        XCTAssertEqual(tile?.title, "Шаги")
        XCTAssertEqual(tile?.value, "9200 шагов")
        XCTAssertEqual(tile?.note, "+1200 шагов к обычному")
        XCTAssertEqual(tile?.tone, .better)
        XCTAssertEqual(tile?.points.count, HealthMetricsFormat.sparklineDays)
        XCTAssertNil(tile?.points[tile!.points.count - 2], "the day nothing arrived for is a gap, not zero")
        XCTAssertEqual(tile?.points.last ?? nil, 9200)
    }

    func testATileWithoutDaysIsNotShown() {
        XCTAssertNil(HealthOverview.tile(metric(steps, deviation: nil, days: []), today: "2026-10-29", higherIsBetter: true))
    }

    // MARK: Workouts

    private func workout(
        _ id: String, type: String = "running", label: String = "Бег", minutes: Double, kcal: Double? = nil, meters: Double? = nil
    ) -> HealthWorkoutRecordDTO {
        HealthWorkoutRecordDTO(
            id: id, activityType: type, activityLabel: label, date: "2026-10-20", start: "2026-10-20T07:00:00+03:00",
            end: "2026-10-20T07:30:00+03:00", durationMin: minutes, energyKcal: kcal, distanceM: meters, avgHeartRate: nil, maxHeartRate: nil
        )
    }

    func testWorkoutsGroupByTypeLongestTimeFirstAndSumOnlyHeldNumbers() {
        let groups = HealthOverview.workoutGroups([
            workout("1", minutes: 30, kcal: 300, meters: 5000),
            workout("2", type: "yoga", label: "Йога", minutes: 60),
            workout("3", minutes: 20, kcal: nil, meters: 3200),
        ])
        XCTAssertEqual(groups.map(\.label), ["Йога", "Бег"])
        XCTAssertEqual(groups[1].count, 2)
        XCTAssertEqual(groups[1].minutes, 50)
        XCTAssertEqual(groups[1].kcal, 300)
        XCTAssertEqual(groups[1].meters, 8200)
        XCTAssertNil(groups[0].kcal, "no kcal held — not zero")
        XCTAssertNil(groups[0].meters)
        XCTAssertEqual(groups[1].details, ["2 раза", "50 мин", "300 ккал", "8,2 км"])
        XCTAssertEqual(groups[0].details, ["1 раз", "1 ч"])
    }

    func testTheWorkoutsHeadlineCountsAndSumsTime() {
        XCTAssertNil(HealthOverview.workoutsHeadline([]))
        XCTAssertEqual(
            HealthOverview.workoutsHeadline([workout("1", minutes: 30), workout("2", minutes: 45)]),
            "2 тренировки · 1 ч 15 мин"
        )
        XCTAssertEqual(HealthOverview.workoutsHeadline([workout("1", minutes: 30)]), "1 тренировка · 30 мин")
    }
}
