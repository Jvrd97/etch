// [review:need-review] PHASE-03/229, PHASE-03/243, PHASE-03/261, PHASE-03/262
// summary: tests of the Week vocabulary (a day's outcome from the server's flags, the server's day cut at the day-start hour, a week that has ended since it was cached, a timeout that is a slow model and not a missing network) — minutes as hours, signed changes with the real minus, counts with Russian plurals, dates by hand, the note under an unfinished week, health values by unit, the emptiness test mirrored from the server, error and narrative texts by status
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

    /// The answer of a server that does not send the new fields, whatever the base fixture carries.
    private func legacy(_ object: inout [String: Any]) {
        object["verdict_line"] = nil
        var window = object["window"] as? [String: Any] ?? [:]
        window["today_counted"] = nil
        object["window"] = window
        object["health"] = (object["health"] as? [[String: Any]] ?? []).map { metric -> [String: Any] in
            var metric = metric
            metric["previous_days_with_data"] = nil
            return metric
        }
    }

    func testAnOpenTodayIsPromisedAfterClosing() throws {
        let window = try WeekFixtures.review { object in
            var window = object["window"] as? [String: Any] ?? [:]
            window["is_complete"] = false
            window["counted_days"] = 3
            window["compared_days"] = 3
            window["today_counted"] = false
            object["window"] = window
        }.window
        let note = try XCTUnwrap(WeekFormat.partialNote(window))
        XCTAssertTrue(note.contains("сегодняшний день войдёт после закрытия"))
    }

    func testAClosedTodayIsNotPromisedAgain() throws {
        let window = try WeekFixtures.review { object in
            var window = object["window"] as? [String: Any] ?? [:]
            window["is_complete"] = false
            window["counted_days"] = 3
            window["compared_days"] = 3
            window["today_counted"] = true
            object["window"] = window
        }.window
        XCTAssertEqual(window.todayCounted, true)
        let note = try XCTUnwrap(WeekFormat.partialNote(window))
        XCTAssertTrue(note.contains("учтено 3 из 7 дней"))
        XCTAssertFalse(note.contains("войдёт после закрытия"))
    }

    func testAnOldAnswerWithoutTheNewFieldsDecodesAsBefore() throws {
        let review = try WeekFixtures.review(patch: legacy)
        XCTAssertNil(review.window.todayCounted)
        XCTAssertNil(review.verdictLine)
        XCTAssertTrue(review.health.allSatisfy { $0.previousDaysWithData == nil })
    }

    func testTheServersVerdictLineWinsAndTheOwnTextIsTheFallback() throws {
        let said = try WeekFixtures.review { $0["verdict_line"] = "Неделя выиграна: нет (правило)." }
        XCTAssertEqual(WeekFormat.weekVerdict(said), "Неделя выиграна: нет (правило).")
        XCTAssertEqual(WeekFormat.serverVerdictLine(said), "Неделя выиграна: нет (правило).")
        let blank = try WeekFixtures.review { $0["verdict_line"] = "  " }
        XCTAssertEqual(WeekFormat.weekVerdict(blank), "Неделя не выиграна")
        XCTAssertNil(WeekFormat.serverVerdictLine(blank))
        let old = try WeekFixtures.review(patch: legacy)
        XCTAssertEqual(WeekFormat.weekVerdict(old), "Неделя не выиграна")
    }

    func testARunningWeekShowsTheServersUndecidedLineOrNothingAtAll() throws {
        let line = "Неделя выиграна: пока не решено, неделя идёт."
        let withLine = try WeekFixtures.review { object in
            object["is_won"] = NSNull()
            object["verdict_line"] = line
        }
        XCTAssertEqual(WeekFormat.weekVerdict(withLine), line)
        XCTAssertNil(WeekFormat.weekVerdict(try WeekFixtures.review { object in
            legacy(&object)
            object["is_won"] = NSNull()
        }))
    }

    func testIncompleteDataCaptionNamesTheDays() {
        XCTAssertEqual(WeekFormat.incompleteDataNote(countedDays: 5), "Неполные данные: 5 из 7 дней.")
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
        let lost = try WeekFixtures.review(patch: legacy)
        XCTAssertEqual(WeekFormat.weekVerdict(lost), "Неделя не выиграна")
        let won = try WeekFixtures.review { object in
            legacy(&object)
            object["is_won"] = true
        }
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
            "Модель отвечает долго. Повторите чуть позже.",
            "no answer within the budget is a slow model, not a missing network"
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

    // MARK: Outcome of a day

    func testADaysOutcomeAndItsShortWordComeFromTheServersFlags() throws {
        let days = try WeekFixtures.review().days
        let future = try WeekFixtures.review { object in
            var days = object["days"] as? [[String: Any]] ?? []
            days[6]["counted"] = false
            object["days"] = days
        }.days[6]

        XCTAssertEqual(WeekFormat.outcome(days[0]), .won)
        XCTAssertEqual(WeekFormat.outcome(days[1]), .lost)
        XCTAssertEqual(WeekFormat.outcome(days[3]), .open)
        XCTAssertEqual(WeekFormat.outcome(future), .notCounted)
        XCTAssertEqual(
            [days[0], days[1], days[3], future].map(WeekFormat.shortDayVerdict),
            ["выигр.", "проигр.", "открыт", "—"]
        )
    }

    // MARK: The week's clock

    private func moment(_ iso: String) throws -> Date {
        let formatter = ISO8601DateFormatter()
        return try XCTUnwrap(formatter.date(from: iso))
    }

    func testTheServersDayChangesAtTheDayStartHourOfTheWeeksOwnZone() throws {
        let window = try WeekFixtures.review().window
        XCTAssertEqual(window.timezone, "Europe/Berlin")
        XCTAssertEqual(window.dayStartHour, 4)

        // 03:30 in Berlin (summer time, UTC+2) is still the night of the 30th.
        XCTAssertEqual(WeekFormat.serverDay(try moment("2026-08-31T01:30:00Z"), in: window), "2026-08-30")
        XCTAssertEqual(WeekFormat.serverDay(try moment("2026-08-31T02:30:00Z"), in: window), "2026-08-31")
    }

    func testAWeekHasEndedOnlyWhenItsLastDayIsBehindTheServersDay() throws {
        let window = try WeekFixtures.review().window

        XCTAssertFalse(WeekFormat.hasEnded(window, at: try moment("2026-08-30T12:00:00Z")))
        XCTAssertFalse(WeekFormat.hasEnded(window, at: try moment("2026-08-31T01:30:00Z")), "the night after Sunday is Sunday")
        XCTAssertTrue(WeekFormat.hasEnded(window, at: try moment("2026-08-31T02:30:00Z")))
    }

    func testTheCalendarSaysWhichWeekIsRunningNotTheServersAsOf() throws {
        let running = try WeekFixtures.runningWeek().window
        let wednesday = try moment("2026-08-26T10:00:00Z")

        XCTAssertTrue(WeekFormat.isRunning(running, at: wednesday))
        XCTAssertFalse(WeekFormat.isRunning(try WeekFixtures.review().window, at: wednesday), "complete is never running")
        XCTAssertFalse(
            WeekFormat.isRunning(running, at: try moment("2026-08-31T02:30:00Z")),
            "the Sunday of the week is behind us"
        )
    }

    func testOnMondayAfterTheDayStartTheWeekIsRunningThoughNoDayIsCounted() throws {
        let monday = try WeekFixtures.unclosedWeek(iso: "2026-W35").window
        XCTAssertEqual(monday.countedDays, 0)
        XCTAssertNil(monday.asOf)

        // 10:00 in Berlin on Monday: running. 03:00 on Monday is still Sunday's night, so the week has not begun.
        XCTAssertTrue(WeekFormat.isRunning(monday, at: try moment("2026-08-24T08:00:00Z")))
        XCTAssertTrue(WeekFormat.isRunning(monday, at: try moment("2026-08-24T02:30:00Z")))
        XCTAssertFalse(WeekFormat.isRunning(monday, at: try moment("2026-08-24T01:59:00Z")), "03:59 is still Sunday")
        XCTAssertTrue(WeekFormat.isRunning(monday, at: try moment("2026-08-24T02:00:00Z")), "04:00 is Monday")
    }

    func testAWeekStartingInTheFutureIsNotRunning() throws {
        let future = try WeekFixtures.unclosedWeek(iso: "2026-W36").window

        XCTAssertEqual(future.startsOn, "2026-08-31")
        XCTAssertEqual(future.endsOn, "2026-09-06")
        XCTAssertFalse(WeekFormat.isRunning(future, at: try moment("2026-08-26T10:00:00Z")))
        XCTAssertTrue(WeekFormat.isRunning(future, at: try moment("2026-09-02T10:00:00Z")))
    }

    /// Berlin sprang forward at 01:00Z on 2026-03-29. The server cuts the day on the wall clock
    /// (`local - 4 h`), so 04:30 local that Sunday is 00:30 of the 29th, not 23:30 of the 28th.
    func testTheDayCutFollowsTheWallClockAcrossTheSpringChange() throws {
        let window = try WeekFixtures.review().window

        XCTAssertEqual(WeekFormat.serverDay(try moment("2026-03-29T02:30:00Z"), in: window), "2026-03-29")
        XCTAssertEqual(WeekFormat.serverDay(try moment("2026-03-29T01:30:00Z"), in: window), "2026-03-28", "03:30 local is still the night")
        XCTAssertEqual(WeekFormat.serverDay(try moment("2026-10-25T03:30:00Z"), in: window), "2026-10-25")
    }

    func testWeekFixtureDatesFollowTheIsoYear() throws {
        let newYear = try WeekFixtures.unclosedWeek(iso: "2027-W01").window
        XCTAssertEqual(newYear.startsOn, "2027-01-04")
        XCTAssertEqual(newYear.endsOn, "2027-01-10")
        let w53 = try WeekFixtures.unclosedWeek(iso: "2026-W53").window
        XCTAssertEqual(w53.startsOn, "2026-12-28")
        let previous = try WeekFixtures.unclosedWeek(iso: "2026-W34").window
        XCTAssertEqual(previous.startsOn, "2026-08-17")
    }
}
