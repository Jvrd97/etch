// [review:need-review] PHASE-03/229, PHASE-03/243
// summary: pure vocabulary of the Week screen — minutes as hours, signed changes with a real minus, Russian plurals, dates cut by hand, the note under an unfinished week (which week runs now, decided by the calendar and not by the server's «as of», and whether a cached answer's week has since ended), the outcome of a day by the server's flags, health values by unit, the emptiness test mirrored from the server, and error texts by HTTP status (a slow model is not a missing network)
import Foundation

enum WeekFormat {
    private static let minutesPerHour = 60
    static let daysInWeek = 7
    private static let minus = "−"
    private static let secondsPerHour = 3600

    static let noChange = "без изменений"
    static let noData = "Нет данных"
    static let notClosed = "не закрыт"
    static let metricMissing = "Метрика не подключена"
    static let emptyWeekText = "За эту неделю данных пока нет."
    static let noCountedDaysText =
        "Пока нет ни одного учтённого дня: неделя не началась или её первый день ещё не закрыт."

    // MARK: Numbers

    private static let russian = Locale(identifier: "ru_RU")

    private static let wholeFormatter: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.locale = russian
        formatter.numberStyle = .decimal
        formatter.maximumFractionDigits = 0
        return formatter
    }()

    private static let tenthsFormatter: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.locale = russian
        formatter.numberStyle = .decimal
        formatter.maximumFractionDigits = 1
        return formatter
    }()

    /// `12000` as «12 000» with the locale's own separator.
    static func number(_ value: Int) -> String {
        wholeFormatter.string(from: NSNumber(value: value)) ?? String(value)
    }

    /// `75` minutes as «1 ч 15 мин»; a bare hour has no «0 мин» tail.
    static func minutes(_ minutes: Int) -> String {
        let total = max(0, minutes)
        let hours = total / minutesPerHour
        let rest = total % minutesPerHour
        if hours == 0 { return "\(rest) мин" }
        if rest == 0 { return "\(number(hours)) ч" }
        return "\(number(hours)) ч \(String(format: "%02d", rest)) мин"
    }

    // MARK: Changes

    /// Whether a change is for the better, the worse, or neither. Colour repeats it, never carries it.
    enum Trend: Equatable {
        case up, down, flat
    }

    static func trend<Value: Numeric & Comparable>(_ delta: Value?) -> Trend {
        guard let delta, delta != 0 else { return .flat }
        return delta > 0 ? .up : .down
    }

    private static func signed(_ value: Int, _ text: (Int) -> String) -> String {
        if value == 0 { return noChange }
        return (value > 0 ? "+" : minus) + text(abs(value))
    }

    /// «+1 ч 20 мин», «−45 мин»; nil when there is nothing to compare.
    static func deltaMinutes(_ delta: Int?) -> String? {
        delta.map { signed($0, minutes) }
    }

    /// «+2», «−1».
    static func deltaCount(_ delta: Int) -> String {
        signed(delta, number)
    }

    /// A share in percentage points: «+29 п.п.».
    static func deltaPoints(_ delta: Int?) -> String? {
        delta.map { signed($0) { "\(number($0)) п.п." } }
    }

    // MARK: Words

    /// `count` with the form of the word Russian wants: 1 день, 2 дня, 5 дней, 21 день.
    static func plural(_ count: Int, one: String, few: String, many: String) -> String {
        let lastTwo = abs(count) % 100
        let last = abs(count) % 10
        let word: String
        if (11...14).contains(lastTwo) {
            word = many
        } else if last == 1 {
            word = one
        } else if (2...4).contains(last) {
            word = few
        } else {
            word = many
        }
        return "\(number(count)) \(word)"
    }

    static func days(_ count: Int) -> String {
        plural(count, one: "день", few: "дня", many: "дней")
    }

    static func relapses(_ count: Int) -> String {
        plural(count, one: "срыв", few: "срыва", many: "срывов")
    }

    // MARK: Dates

    private static let weekdayNames = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    static func weekdayShort(_ weekday: Int) -> String {
        weekdayNames.indices.contains(weekday) ? weekdayNames[weekday] : ""
    }

    /// `yyyy-MM-dd` as «24.08», cut by hand so no time zone can move the day.
    static func shortDate(_ iso: String) -> String {
        let parts = iso.split(separator: "-")
        guard parts.count == 3 else { return iso }
        return "\(parts[2]).\(parts[1])"
    }

    static func period(_ window: WeekWindowDTO) -> String {
        "\(shortDate(window.startsOn)) — \(shortDate(window.endsOn))"
    }

    /// «обновлено 27 окт., 09:41» — absolute, so it stays honest while the screen sits open.
    static func updatedCaption(_ date: Date, timeZone: TimeZone = .current) -> String {
        let formatter = DateFormatter()
        formatter.locale = russian
        formatter.timeZone = timeZone
        formatter.setLocalizedDateFormatFromTemplate("dMMMHHmm")
        return "обновлено \(formatter.string(from: date))"
    }

    // MARK: Unfinished week

    /// The line under the title of a week that has not ended; nil for a finished one.
    /// It names both counts: the comparison covers the same number of days of the previous
    /// week, and a reader who sees «−3 задачи» must know the week is short.
    static func partialNote(_ window: WeekWindowDTO) -> String? {
        if window.isComplete { return nil }
        if window.countedDays == 0 { return noCountedDaysText }
        return "Неделя не закончилась: учтено \(window.countedDays) из \(daysInWeek) дней — закрытые и прошедшие, "
            + "сегодняшний день войдёт после закрытия. "
            + "Сравнение — с первыми \(window.comparedDays) днями прошлой недели."
    }

    /// The week is the one running at `date`: not complete, begun, and its last day not behind us. Decided by
    /// the calendar, not by `as_of`: the server sends no «as of» while no day is closed, and that is also
    /// what a Monday looks like before Monday closes.
    static func isRunning(_ window: WeekWindowDTO, at date: Date) -> Bool {
        let today = serverDay(date, in: window)
        return !window.isComplete && window.startsOn <= today && window.endsOn >= today
    }

    /// The server's day for `date`: the clock of the week's own time zone, cut at the day-start hour.
    /// The cut subtracts whole hours of absolute time, so in the hour after a clock change it can differ
    /// from the server's own cut; that hour moves neither the end of a week nor the start of one by a day
    /// in a way a reader of this screen can see.
    static func serverDay(_ date: Date, in window: WeekWindowDTO) -> String {
        let zone = TimeZone(identifier: window.timezone) ?? .current
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        let shifted = date.addingTimeInterval(-TimeInterval(window.dayStartHour * secondsPerHour))
        let parts = calendar.dateComponents([.year, .month, .day], from: shifted)
        return String(format: "%04d-%02d-%02d", parts.year ?? 0, parts.month ?? 0, parts.day ?? 0)
    }

    /// The last day of the week is behind `date`. A cached answer of a week that was running when it
    /// was kept says «не закончилась» for as long as it sits on disk; this is how the screen knows better.
    static func hasEnded(_ window: WeekWindowDTO, at date: Date) -> Bool {
        window.endsOn < serverDay(date, in: window)
    }

    // MARK: Health

    /// A value in the unit the catalog gave: minutes as hours, counts as whole numbers.
    static func healthValue(unit: String?, _ value: Double) -> String {
        switch unit {
        case "min": return minutes(Int(value.rounded()))
        case "count": return number(Int(value.rounded()))
        case let unit?: return "\(tenths(value)) \(unit)"
        case nil: return tenths(value)
        }
    }

    private static func tenths(_ value: Double) -> String {
        tenthsFormatter.string(from: NSNumber(value: value)) ?? String(value)
    }

    /// The change of the daily average in the same unit; nil when there is nothing to compare.
    static func healthDelta(_ metric: WeekHealthMetricDTO) -> String? {
        guard let delta = metric.deltaAvgPerDay else { return nil }
        if delta == 0 { return noChange }
        let sign = delta > 0 ? "+" : minus
        return sign + healthValue(unit: metric.unit, abs(delta))
    }

    // MARK: Days and the verdict

    /// Where a day stands, read from the server's flags and nowhere else.
    enum DayOutcome: Equatable {
        case notCounted, won, lost, open
    }

    static func outcome(_ day: WeekDayStatDTO) -> DayOutcome {
        if !day.counted { return .notCounted }
        switch day.verdict {
        case "won": return .won
        case "lost": return .lost
        default: return .open
        }
    }

    /// The state of a day in words, for VoiceOver.
    static func dayVerdict(_ day: WeekDayStatDTO) -> String {
        switch outcome(day) {
        case .notCounted: return "не учтён"
        case .won: return "выигран"
        case .lost: return "проигран"
        case .open: return notClosed
        }
    }

    /// The same, short enough for a cell of seven.
    static func shortDayVerdict(_ day: WeekDayStatDTO) -> String {
        switch outcome(day) {
        case .notCounted: return "—"
        case .won: return "выигр."
        case .lost: return "проигр."
        case .open: return "открыт"
        }
    }

    /// «Лучший день: Пн 24.08 · 4 из 4 задач, 100%»; nil when the server names none.
    static func highlight(title: String, date: String?, in days: [WeekDayStatDTO]) -> String? {
        guard let date, let day = days.first(where: { $0.date == date }) else { return nil }
        var line = "\(title): \(weekdayShort(day.weekday)) \(shortDate(day.date))"
        if day.tasksTotal > 0 {
            line += " · \(day.tasksDone) из \(day.tasksTotal) задач"
            if let pct = day.planPct { line += ", \(pct)%" }
        }
        return line
    }

    /// The week's verdict; nil while the week runs and nothing is decided.
    static func weekVerdict(_ review: WeekReviewDTO) -> String? {
        guard let isWon = review.isWon else { return nil }
        return isWon ? "Неделя выиграна" : "Неделя не выиграна"
    }

    /// Overwork that has not come back yet; nil when there is none.
    static func debtLine(_ review: WeekReviewDTO) -> String? {
        review.debtMinutes > 0 ? "Долг переработки: \(minutes(review.debtMinutes))" : nil
    }

    // MARK: Emptiness

    /// The server's emptiness test, repeated so the button is off exactly when the server would refuse (422).
    static func isEmpty(_ review: WeekReviewDTO) -> Bool {
        review.totals.closedDays == 0
            && review.totals.tasksTotal == 0
            && review.totals.roleMinutes == 0
            && review.categories.isEmpty
            && review.habitStreaks.isEmpty
            && review.health.allSatisfy { $0.daysWithData == 0 }
    }

    // MARK: Errors

    static let notConfiguredMessage = "Укажите адрес сервера в More → Settings"
    static let narrativeNeedsNetwork = "Итог пишется на сервере: нужна сеть. Проверьте соединение и повторите."
    static let narrativeFallback = "Не удалось написать итог недели."
    static let narrativeSlow = "Модель отвечает долго. Повторите чуть позже."
    static let loadFailedMessage = "Не удалось загрузить неделю"

    static func message(for error: APIClientError) -> String {
        switch error {
        case .invalidBaseURL: return "Неверный адрес сервера"
        case .unauthorized: return "Неверный ключ API (401)"
        case .timeout: return "Сервер не ответил вовремя"
        case .transport: return "Нет связи с сервером"
        case .unexpectedStatus(let status): return "Сервер ответил ошибкой \(status)"
        case .invalidResponse: return "Сервер вернул непонятный ответ"
        }
    }

    /// The narrative's refusals by HTTP status, and a clear word when the network is the problem.
    /// A timeout is the model taking its time, not the network missing: the request left and nothing came back.
    static func narrativeMessage(for error: APIClientError) -> String {
        if case .timeout = error { return narrativeSlow }
        if error.isConnectivity { return narrativeNeedsNetwork }
        switch error {
        case .unexpectedStatus(422): return "В этой неделе нет данных для итога."
        case .unexpectedStatus(502): return "Модель не ответила. Повторите позже."
        case .unexpectedStatus(503): return "Итог от ИИ выключен: на сервере не настроена модель."
        case .unauthorized, .invalidBaseURL: return message(for: error)
        case .timeout, .transport, .unexpectedStatus, .invalidResponse: return narrativeFallback
        }
    }
}
