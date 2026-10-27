// [review:need-review] PHASE-03/229
// summary: tests of the Week vocabulary — minutes as hours, signed changes with the real minus, counts with Russian plurals, dates by hand, the note under an unfinished week, health values by unit, the emptiness test mirrored from the server, error and narrative texts by status
import XCTest
@testable import HabitTracker

final class WeekFormatTests: XCTestCase {
    /// Group separators differ in the non-breaking kind between systems; the test reads them as a plain space.
    private func plain(_ text: String) -> String {
        text.replacingOccurrences(of: "\u{00A0}", with: " ").replacingOccurrences(of: "\u{202F}", with: " ")
    }

    func testMinutesSayHoursAndDropAnEmptyTail() {
        XCTAssertEqual(WeekFormat.minutes(45), "45 мин")
        XCTAssertEqual(WeekFormat.minutes(120), "2 ч")
        XCTAssertEqual(WeekFormat.minutes(75), "1 ч 15 мин")
        XCTAssertEqual(WeekFormat.minutes(65), "1 ч 05 мин")
        XCTAssertEqual(WeekFormat.minutes(0), "0 мин")
        XCTAssertEqual(WeekFormat.minutes(-5), "0 мин")
    }

    func testBigHoursGetTheLocalGroupSeparator() {
        XCTAssertEqual(plain(WeekFormat.minutes(1_200 * 60)), "1 200 ч")
    }

    func testChangesCarryTheirSign() {
        XCTAssertEqual(WeekFormat.deltaMinutes(80), "+1 ч 20 мин")
        XCTAssertEqual(WeekFormat.deltaMinutes(-45), "−45 мин")
        XCTAssertEqual(WeekFormat.deltaMinutes(0), "без изменений")
        XCTAssertNil(WeekFormat.deltaMinutes(nil))
        XCTAssertEqual(WeekFormat.deltaCount(2), "+2")
        XCTAssertEqual(WeekFormat.deltaCount(-1), "−1")
        XCTAssertEqual(WeekFormat.deltaPoints(29), "+29 п.п.")
        XCTAssertEqual(WeekFormat.deltaPoints(-3), "−3 п.п.")
        XCTAssertNil(WeekFormat.deltaPoints(nil))
    }

    func testTrendIsFlatWithoutAComparison() {
        XCTAssertEqual(WeekFormat.trend(5), .up)
        XCTAssertEqual(WeekFormat.trend(-5), .down)
        XCTAssertEqual(WeekFormat.trend(0), .flat)
        XCTAssertEqual(WeekFormat.trend(nil as Int?), .flat)
        XCTAssertEqual(WeekFormat.trend(0.4), .up)
    }

    func testCountsAgreeWithTheirWord() {
        XCTAssertEqual(WeekFormat.days(1), "1 день")
        XCTAssertEqual(WeekFormat.days(2), "2 дня")
        XCTAssertEqual(WeekFormat.days(5), "5 дней")
        XCTAssertEqual(WeekFormat.days(11), "11 дней")
        XCTAssertEqual(WeekFormat.days(21), "21 день")
        XCTAssertEqual(WeekFormat.days(22), "22 дня")
        XCTAssertEqual(WeekFormat.relapses(1), "1 срыв")
        XCTAssertEqual(WeekFormat.relapses(3), "3 срыва")
        XCTAssertEqual(WeekFormat.relapses(7), "7 срывов")
    }

    func testDatesAreCutByHandSoNoZoneMovesTheDay() {
        XCTAssertEqual(WeekFormat.shortDate("2026-08-24"), "24.08")
        XCTAssertEqual(WeekFormat.weekdayShort(0), "Пн")
        XCTAssertEqual(WeekFormat.weekdayShort(6), "Вс")
        XCTAssertEqual(WeekFormat.weekdayShort(9), "")
    }

    func testPeriodNamesBothEnds() throws {
        XCTAssertEqual(WeekFormat.period(try WeekFixtures.review().window), "24.08 — 30.08")
    }

    func testAFinishedWeekNeedsNoNote() throws {
        XCTAssertNil(WeekFormat.partialNote(try WeekFixtures.review().window))
    }

    func testARunningWeekNamesBothCounts() throws {
        let note = try XCTUnwrap(WeekFormat.partialNote(try WeekFixtures.runningWeek().window))

        XCTAssertTrue(note.contains("учтено 3 из 7 дней"))
        XCTAssertTrue(note.contains("первыми 3 днями прошлой недели"))
    }

    func testAWeekWithNoCountedDaySaysSo() throws {
        let window = try WeekFixtures.review { object in
            var window = object["window"] as? [String: Any] ?? [:]
            window["is_complete"] = false
            window["counted_days"] = 0
            object["window"] = window
        }.window

        XCTAssertEqual(WeekFormat.partialNote(window), WeekFormat.noCountedDaysText)
    }

    func testHealthValuesFollowTheirUnit() {
        XCTAssertEqual(plain(WeekFormat.healthValue(unit: "count", 12_000)), "12 000")
        XCTAssertEqual(WeekFormat.healthValue(unit: "min", 90), "1 ч 30 мин")
        XCTAssertEqual(WeekFormat.healthValue(unit: "kg", 72.5), "72,5 kg")
        XCTAssertEqual(WeekFormat.healthValue(unit: nil, 3), "3")
    }

    func testHealthChangeIsSignedInTheSameUnit() throws {
        let steps = try XCTUnwrap(try WeekFixtures.review().health.first { $0.key == "steps" })
        let workouts = try XCTUnwrap(try WeekFixtures.review().health.first { $0.key == "workouts" })

        XCTAssertEqual(plain(try XCTUnwrap(WeekFormat.healthDelta(steps))), "+3 000")
        XCTAssertNil(WeekFormat.healthDelta(workouts))
    }

    func testOnlyAWeekWithNothingInItIsEmpty() throws {
        XCTAssertFalse(WeekFormat.isEmpty(try WeekFixtures.review()))
        XCTAssertTrue(WeekFormat.isEmpty(try WeekFixtures.emptyWeek()))
    }

    func testAnyOneSignOfLifeMakesTheWeekNonEmpty() throws {
        let withHealth = try WeekFixtures.emptyWeek(healthDays: 1)

        XCTAssertFalse(WeekFormat.isEmpty(withHealth))
    }

    func testDaysAreNamedByTheirVerdict() throws {
        let days = try WeekFixtures.review().days

        XCTAssertEqual(WeekFormat.dayVerdict(days[0]), "выигран")
        XCTAssertEqual(WeekFormat.dayVerdict(days[1]), "проигран")
        XCTAssertEqual(WeekFormat.dayVerdict(days[3]), "не закрыт")
        let future = try WeekFixtures.review { object in
            var days = object["days"] as? [[String: Any]] ?? []
            days[6]["counted"] = false
            object["days"] = days
        }.days[6]
        XCTAssertEqual(WeekFormat.dayVerdict(future), "не учтён")
    }

    func testBestAndWorstDayAreOneLineEach() throws {
        let week = try WeekFixtures.review()

        XCTAssertEqual(
            WeekFormat.highlight(title: "Лучший день", date: week.bestDay, in: week.days),
            "Лучший день: Пн 24.08 · 4 из 4 задач, 100%"
        )
        XCTAssertEqual(
            WeekFormat.highlight(title: "Худший день", date: week.worstDay, in: week.days),
            "Худший день: Вт 25.08 · 1 из 4 задач, 25%"
        )
        XCTAssertNil(WeekFormat.highlight(title: "Худший день", date: nil, in: week.days))
        XCTAssertNil(WeekFormat.highlight(title: "Худший день", date: "2030-01-01", in: week.days))
    }

    func testTheWeekVerdictIsSaidOnlyWhenDecided() throws {
        XCTAssertEqual(WeekFormat.weekVerdict(try WeekFixtures.review()), "Неделя не выиграна")
        XCTAssertNil(WeekFormat.weekVerdict(try WeekFixtures.runningWeek()))
        let won = try WeekFixtures.review { $0["is_won"] = true }
        XCTAssertEqual(WeekFormat.weekVerdict(won), "Неделя выиграна")
    }

    func testDebtIsNamedOnlyWhenThereIsSome() throws {
        XCTAssertNil(WeekFormat.debtLine(try WeekFixtures.review()))
        let owing = try WeekFixtures.review { $0["debt_minutes"] = 80 }
        XCTAssertEqual(WeekFormat.debtLine(owing), "Долг переработки: 1 ч 20 мин")
    }

    func testLoadErrorsAreInRussian() {
        XCTAssertEqual(WeekFormat.message(for: .unauthorized), "Неверный ключ API (401)")
        XCTAssertEqual(WeekFormat.message(for: .timeout), "Сервер не ответил вовремя")
        XCTAssertEqual(WeekFormat.message(for: .transport(code: -1009)), "Нет связи с сервером")
        XCTAssertEqual(WeekFormat.message(for: .unexpectedStatus(500)), "Сервер ответил ошибкой 500")
    }

    func testNarrativeErrorsAreByStatusAndNetworkNeedsTheNetwork() {
        XCTAssertEqual(WeekFormat.narrativeMessage(for: .unexpectedStatus(422)), "В этой неделе нет данных для итога.")
        XCTAssertEqual(WeekFormat.narrativeMessage(for: .unexpectedStatus(502)), "Модель не ответила. Повторите позже.")
        XCTAssertEqual(
            WeekFormat.narrativeMessage(for: .unexpectedStatus(503)),
            "Итог от ИИ выключен: на сервере не настроена модель."
        )
        XCTAssertEqual(
            WeekFormat.narrativeMessage(for: .transport(code: -1009)),
            "Итог пишется на сервере: нужна сеть. Проверьте соединение и повторите."
        )
        XCTAssertEqual(
            WeekFormat.narrativeMessage(for: .timeout),
            "Итог пишется на сервере: нужна сеть. Проверьте соединение и повторите."
        )
        XCTAssertEqual(WeekFormat.narrativeMessage(for: .unexpectedStatus(500)), "Не удалось написать итог недели.")
    }

    func testUpdatedCaptionIsRussianAndNamesTheMoment() {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let moment = calendar.date(from: DateComponents(year: 2026, month: 10, day: 27, hour: 9, minute: 41))!

        let caption = WeekFormat.updatedCaption(moment, timeZone: calendar.timeZone)

        XCTAssertTrue(caption.hasPrefix("обновлено "), caption)
        XCTAssertTrue(caption.contains("27"), caption)
        XCTAssertTrue(caption.contains("9:41") || caption.contains("09:41"), caption)
    }
}
