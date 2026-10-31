// [review:need-review] PHASE-03/304
// summary: tests of the dashboard's words and arithmetic — the three rings in all their states (honest empties: «Мало данных», «Нормы пока нет», «План не задан», «Челленджей нет»), the tone of a distance from the norm by the server's direction and always as a word, values and deltas with units, the server's day for «сегодня», the server's wall clock of the insight, day-strip tallies, bar fractions, Russian errors
import XCTest
@testable import HabitTracker

final class DashboardFormatTests: XCTestCase {
    private func scores(
        health: HealthScoreDTO = HealthScoreDTO(value: nil, label: nil, basisDays: 0),
        habits: DashboardScoresDTO.Habits = .init(value: nil, done: nil, total: nil),
        challenges: DashboardScoresDTO.Challenges = .init(done: nil, total: nil)
    ) -> DashboardScoresDTO {
        DashboardScoresDTO(health: health, habits: habits, challenges: challenges)
    }

    // MARK: Rings

    func testAFullHealthRingShowsTheIndexItsWordAndTheDays() {
        let ring = DashboardFormat.rings(scores(health: HealthScoreDTO(value: 78, label: "good", basisDays: 7)))[0]
        XCTAssertEqual(ring.title, "Здоровье")
        XCTAssertEqual(ring.fraction, 0.78)
        XCTAssertEqual(ring.centre, "78")
        XCTAssertEqual(ring.caption, "Хорошо · за 7 дней")
    }

    func testTheHealthWordsFollowTheServersLabel() {
        func caption(_ label: String?) -> String {
            DashboardFormat.rings(scores(health: HealthScoreDTO(value: 40, label: label, basisDays: 1)))[0].caption
        }
        XCTAssertEqual(caption("fair"), "Средне · за 1 день")
        XCTAssertEqual(caption("poor"), "Ниже нормы · за 1 день")
        XCTAssertEqual(caption("odd"), "за 1 день")
        XCTAssertEqual(caption(nil), "за 1 день")
    }

    func testAHealthRingUnderThreeDaysSaysThereIsTooLittleData() {
        let ring = DashboardFormat.rings(scores(health: HealthScoreDTO(value: nil, label: nil, basisDays: 2)))[0]
        XCTAssertNil(ring.fraction)
        XCTAssertEqual(ring.centre, "—")
        XCTAssertEqual(ring.caption, "Мало данных: 2 из 3 дн.")
    }

    func testAHealthRingWithEnoughDaysButNoIndexSaysTheNormIsMissing() {
        let ring = DashboardFormat.rings(scores(health: HealthScoreDTO(value: nil, label: nil, basisDays: 3)))[0]
        XCTAssertNil(ring.fraction)
        XCTAssertEqual(ring.caption, "Нормы пока нет")
    }

    func testTheHabitsRingShowsThePercentAndTheMarks() {
        let ring = DashboardFormat.rings(scores(habits: .init(value: 64, done: 45, total: 70)))[1]
        XCTAssertEqual(ring.title, "Привычки")
        XCTAssertEqual(ring.fraction, 0.64)
        XCTAssertEqual(ring.centre, "64%")
        XCTAssertEqual(ring.caption, "45 из 70 отметок")
    }

    func testTheHabitsRingWithoutAPlanSaysSoAndIsNotZero() {
        for habits in [DashboardScoresDTO.Habits(value: nil, done: nil, total: nil), .init(value: nil, done: 0, total: 0)] {
            let ring = DashboardFormat.rings(scores(habits: habits))[1]
            XCTAssertNil(ring.fraction)
            XCTAssertEqual(ring.centre, "—")
            XCTAssertEqual(ring.caption, "План не задан")
        }
    }

    func testTheHabitsRingWithAPlanButNoShareSaysThereIsNoData() {
        let ring = DashboardFormat.rings(scores(habits: .init(value: nil, done: nil, total: 4)))[1]
        XCTAssertNil(ring.fraction)
        XCTAssertEqual(ring.caption, "Нет данных")
    }

    func testTheChallengesRingShowsDoneOfTotal() {
        let ring = DashboardFormat.rings(scores(challenges: .init(done: 3, total: 5)))[2]
        XCTAssertEqual(ring.title, "Челленджи")
        XCTAssertEqual(ring.fraction, 0.6)
        XCTAssertEqual(ring.centre, "3/5")
        XCTAssertEqual(ring.caption, "выполнено")
    }

    func testTheChallengesRingWithNoneSaysThereAreNone() {
        for challenges in [DashboardScoresDTO.Challenges(done: nil, total: nil), .init(done: 0, total: 0)] {
            let ring = DashboardFormat.rings(scores(challenges: challenges))[2]
            XCTAssertNil(ring.fraction)
            XCTAssertEqual(ring.caption, "Челленджей нет")
        }
    }

    func testAZeroOfFiveChallengesIsARealZeroNotAnEmptyRing() {
        let ring = DashboardFormat.rings(scores(challenges: .init(done: 0, total: 5)))[2]
        XCTAssertEqual(ring.fraction, 0)
        XCTAssertEqual(ring.centre, "0/5")
    }

    func testEveryRingIsReadAloudAsOneSentence() {
        let rings = DashboardFormat.rings(scores(
            health: HealthScoreDTO(value: 78, label: "good", basisDays: 7), challenges: .init(done: 3, total: 5)
        ))
        XCTAssertEqual(rings[0].spoken, "Здоровье: 78. Хорошо · за 7 дней")
        XCTAssertEqual(rings[1].spoken, "Привычки: нет значения. План не задан")
        XCTAssertEqual(rings[2].spoken, "Челленджи: 3 из 5. выполнено")
    }

    // MARK: Tone

    func testTheToneFollowsTheServersDirectionOfBetter() {
        XCTAssertEqual(DashboardFormat.tone(delta: -2, higherIsBetter: false), .better)
        XCTAssertEqual(DashboardFormat.tone(delta: 2, higherIsBetter: false), .worse)
        XCTAssertEqual(DashboardFormat.tone(delta: 300, higherIsBetter: true), .better)
        XCTAssertEqual(DashboardFormat.tone(delta: -300, higherIsBetter: true), .worse)
    }

    func testNoNormAndNoDistanceAreNeitherBetterNorWorse() {
        XCTAssertEqual(DashboardFormat.tone(delta: nil, higherIsBetter: true), .same)
        XCTAssertEqual(DashboardFormat.tone(delta: 0, higherIsBetter: false), .same)
        XCTAssertNil(DashboardFormat.toneWord(.same))
        XCTAssertEqual(DashboardFormat.toneWord(.better), "лучше нормы")
        XCTAssertEqual(DashboardFormat.toneWord(.worse), "хуже нормы")
    }

    // MARK: Values and distances

    func testValuesCarryTheirUnitsInRussian() {
        XCTAssertEqual(DashboardFormat.value(identifier: "HKQuantityTypeIdentifierRestingHeartRate", value: 58, unit: "count/min"), "58 уд/мин")
        XCTAssertEqual(DashboardFormat.value(identifier: "HKQuantityTypeIdentifierStepCount", value: 7200, unit: "count"), "7\u{00A0}200 шагов")
        XCTAssertEqual(DashboardFormat.value(identifier: "HKQuantityTypeIdentifierActiveEnergyBurned", value: 410, unit: "kcal"), "410 ккал")
        XCTAssertEqual(DashboardFormat.value(identifier: "HKQuantityTypeIdentifierHeartRateVariabilitySDNN", value: 42, unit: "ms"), "42 мс")
        XCTAssertEqual(DashboardFormat.value(identifier: "HKCategoryTypeIdentifierSleepAnalysis", value: 435, unit: "min"), "7 ч 15 мин")
    }

    func testTheDistanceFromTheNormIsSignedAndInWords() throws {
        let metrics = try DashboardFixtures.week().health
        XCTAssertEqual(DashboardFormat.deltaText(metrics[0]), "−2 уд/мин от вашей нормы")
        XCTAssertEqual(DashboardFormat.deltaText(metrics[1]), "−1\u{00A0}200 шагов от вашей нормы")
        XCTAssertEqual(DashboardFormat.deltaText(metrics[2]), "нормы пока нет")
    }

    func testAZeroDistanceReadsAsOnTheNorm() throws {
        let metric = try DashboardFixtures.week().health[0]
        let onNorm = DashboardHealthMetricDTO(
            identifier: metric.identifier, label: metric.label, value: metric.value, unit: metric.unit,
            baselineDelta: 0, higherIsBetter: false
        )
        XCTAssertEqual(DashboardFormat.deltaText(onNorm), "на уровне нормы")
    }

    func testAPositiveSleepDistanceIsPrintedInHours() {
        let sleep = DashboardHealthMetricDTO(
            identifier: "HKCategoryTypeIdentifierSleepAnalysis", label: "Сон", value: 480, unit: "min",
            baselineDelta: 45, higherIsBetter: true
        )
        XCTAssertEqual(DashboardFormat.deltaText(sleep), "+45 мин от вашей нормы")
    }

    // MARK: Dates

    func testTheServersDayDecidesWhatTodayAndYesterdayAre() {
        XCTAssertEqual(DashboardFormat.bestDayText("2026-10-31", today: "2026-10-31"), "сегодня")
        XCTAssertEqual(DashboardFormat.bestDayText("2026-10-30", today: "2026-10-31"), "вчера")
        XCTAssertEqual(DashboardFormat.bestDayText("2026-10-28", today: "2026-10-31"), "28 окт.")
        XCTAssertEqual(DashboardFormat.bestDayText("2026-10-31", today: "2026-11-01"), "вчера")
    }

    func testTheInsightMomentIsReadOffTheStringWithoutMovingZones() {
        XCTAssertEqual(DashboardFormat.generatedAtText("2026-10-31T09:00:00+03:00"), "31 окт., 09:00")
        XCTAssertEqual(DashboardFormat.generatedAtText("2026-10-31T23:30:00-08:00"), "31 окт., 23:30")
        XCTAssertNil(DashboardFormat.generatedAtText("вчера"))
    }

    func testTheRangeIsTwoShortDates() {
        XCTAssertEqual(DashboardFormat.rangeText(from: "2026-10-25", to: "2026-10-31"), "25 окт. — 31 окт.")
    }

    // MARK: Streaks and workouts

    func testTheDayStripIsTalliedAndReadAloudWithoutColour() throws {
        let streaks = try DashboardFixtures.week().streaks
        XCTAssertEqual(DashboardFormat.tally(streaks[0].days), DashboardFormat.DayTally(done: 5, missed: 1, unknown: 1))
        XCTAssertEqual(DashboardFormat.dotsLabel(streaks[0]), "Последние 7 дней: выполнено 5, пропущено 1, нет данных 1")
        XCTAssertEqual(DashboardFormat.dotsLabel(streaks[1]), "Последние 7 дней: без срыва 7, срывов 0, нет данных 0")
    }

    func testBarsAreScaledToTheBusiestWeekAndAnEmptyWindowStaysFlat() {
        let weeks = [
            DashboardWorkoutWeekDTO(weekStart: "2026-10-19", count: 2, minutes: 90),
            DashboardWorkoutWeekDTO(weekStart: "2026-10-26", count: 4, minutes: 150),
        ]
        XCTAssertEqual(DashboardFormat.workoutFractions(weeks), [0.5, 1])
        let idle = weeks.map { DashboardWorkoutWeekDTO(weekStart: $0.weekStart, count: 0, minutes: 0) }
        XCTAssertEqual(DashboardFormat.workoutFractions(idle), [0, 0])
    }

    func testTheChangeAgainstThePreviousPeriodIsSignedOrAbsent() {
        XCTAssertEqual(DashboardFormat.workoutChangeText(1), "+1 к прошлому периоду")
        XCTAssertEqual(DashboardFormat.workoutChangeText(-2), "−2 к прошлому периоду")
        XCTAssertEqual(DashboardFormat.workoutChangeText(0), "столько же, сколько в прошлом периоде")
        XCTAssertNil(DashboardFormat.workoutChangeText(nil))
    }

    func testAWeeksBarIsReadAloudWithItsCountAndMinutes() {
        let week = DashboardWorkoutWeekDTO(weekStart: "2026-10-26", count: 3, minutes: 150)
        XCTAssertEqual(DashboardFormat.workoutWeekLabel(week), "Неделя с 26 окт.: 3 тренировки, 2 ч 30 мин")
    }

    func testRussianPlurals() {
        XCTAssertEqual(DashboardFormat.days(1), "1 день")
        XCTAssertEqual(DashboardFormat.days(2), "2 дня")
        XCTAssertEqual(DashboardFormat.days(5), "5 дней")
        XCTAssertEqual(DashboardFormat.days(11), "11 дней")
        XCTAssertEqual(DashboardFormat.days(21), "21 день")
        XCTAssertEqual(DashboardFormat.days(0), "0 дней")
    }

    // MARK: Words

    func testTitlesFollowThePeriod() {
        XCTAssertEqual(DashboardFormat.bestsTitle(.week), "Лучшее за неделю")
        XCTAssertEqual(DashboardFormat.bestsTitle(.month), "Лучшее за месяц")
        XCTAssertEqual(DashboardFormat.insightTitle(.week), "Инсайт недели")
        XCTAssertEqual(DashboardFormat.insightTitle(.month), "Инсайт периода")
        XCTAssertEqual(DashboardFormat.periodTitle(.week), "Неделя")
        XCTAssertEqual(DashboardFormat.periodTitle(.month), "Месяц")
    }

    func testErrorsAreInRussianAndNeverTheEnglishFallback() {
        let all: [APIClientError] = [
            .invalidBaseURL, .unauthorized, .timeout, .transport(code: -1009),
            .unexpectedStatus(500), .unexpectedStatus(404), .invalidResponse,
        ]
        for error in all {
            let text = DashboardFormat.message(for: error)
            XCTAssertFalse(text.contains("Something went wrong"), text)
            XCTAssertNil(text.range(of: "[A-Za-z]{4,}", options: .regularExpression), text)
        }
        XCTAssertEqual(DashboardFormat.message(for: .unexpectedStatus(500)), "Сервер не смог собрать сводку. Попробуйте ещё раз через минуту.")
    }

    func testTheStaleNoteNamesTheMomentTheDataIsFrom() {
        let moment = Date(timeIntervalSince1970: 1_800_000_000)
        let zone = TimeZone(identifier: "UTC")!
        XCTAssertTrue(DashboardFormat.staleText(moment, timeZone: zone).hasPrefix("Не обновлено · по данным на "))
    }
}
