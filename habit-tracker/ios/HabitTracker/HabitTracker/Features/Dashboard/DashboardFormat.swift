// [review:need-review] PHASE-03/304
// summary: the dashboard's words and arithmetic, no view in it — the three rings with honest empty states, the tone of a distance from the personal norm by the server's `higher_is_better` (always a word, never colour alone), values with Russian units, «сегодня»/«вчера» by the server's day, the insight moment read off the server's string, day-strip tallies, bar fractions, Russian errors
import Foundation

/// Whether a value against the personal norm is good news. Drives the colour and never stands alone: a word always goes beside it.
enum DashboardTone: Equatable {
    case better
    case worse
    case same
}

/// One of the three rings, ready to draw: what fills it, what sits in the middle, what is written under it.
struct DashboardRing: Equatable, Identifiable {
    enum Kind: Equatable {
        case health
        case habits
        case challenges
    }

    let kind: Kind
    let title: String
    /// 0...1; `nil` draws an empty track, which is «no data» and never a zero.
    let fraction: Double?
    let centre: String
    let caption: String
    /// The ring as one sentence for VoiceOver.
    let spoken: String

    var id: Kind { kind }
}

enum DashboardFormat {
    // MARK: Titles

    static func periodTitle(_ period: DashboardPeriod) -> String {
        period == .week ? "Неделя" : "Месяц"
    }

    static func bestsTitle(_ period: DashboardPeriod) -> String {
        period == .week ? "Лучшее за неделю" : "Лучшее за месяц"
    }

    static func insightTitle(_ period: DashboardPeriod) -> String {
        period == .week ? "Инсайт недели" : "Инсайт периода"
    }

    static let ringsTitle = "Общий показатель"
    static let streaksTitle = "Серии"
    static let healthTitle = "Состояние здоровья"
    static let healthAside = "среднее за период"
    static let workoutsTitle = "Динамика тренировок"
    static let nutritionTitle = "Питание · скоро"
    static let nutritionText = "Калории, белки и рацион появятся здесь позже. Пока блок только держит место."
    static let insightsLink = "Разборы и запуск нового"
    static let recordWord = "Рекорд"
    static let avoidBadge = "без срывов"

    // MARK: Empty lines

    static let streaksEmpty = "Серий пока нет: данных мало. Отметьте привычку, и серия начнётся."
    static let healthEmpty = "Данных мало: показатели здоровья придут из Apple Health."
    static let bestsEmpty = "Данных мало: лучшие значения появятся после первых дней записи."
    static let workoutsEmpty = "Данных мало: тренировок в этом окне не записано."
    static let insightEmpty = "Данных мало: инсайт появится, когда накопится неделя записей."

    // MARK: Rings

    /// Days of data under which the server gives no health index.
    static let minimumHealthDays = 3
    private static let percent = 100.0
    private static let noValue = "—"
    private static let spokenNoValue = "нет значения"

    static func rings(_ scores: DashboardScoresDTO) -> [DashboardRing] {
        [healthRing(scores.health), habitsRing(scores.habits), challengesRing(scores.challenges)]
    }

    private static func ring(
        _ kind: DashboardRing.Kind, title: String, fraction: Double?, centre: String, spokenValue: String, caption: String
    ) -> DashboardRing {
        DashboardRing(
            kind: kind, title: title, fraction: fraction.map { min(max($0, 0), 1) }, centre: centre, caption: caption,
            spoken: "\(title): \(spokenValue). \(caption)"
        )
    }

    private static func healthRing(_ health: HealthScoreDTO) -> DashboardRing {
        guard let value = health.value else {
            // Enough days and still no index: the personal norm has not formed.
            let caption = health.basisDays >= minimumHealthDays
                ? "Нормы пока нет"
                : "Мало данных: \(health.basisDays) из \(minimumHealthDays) дн."
            return ring(.health, title: "Здоровье", fraction: nil, centre: noValue, spokenValue: spokenNoValue, caption: caption)
        }
        let span = "за \(days(health.basisDays))"
        let caption = healthWord(health.label).map { "\($0) · \(span)" } ?? span
        return ring(
            .health, title: "Здоровье", fraction: Double(value) / percent, centre: String(value), spokenValue: String(value),
            caption: caption
        )
    }

    private static func habitsRing(_ habits: DashboardScoresDTO.Habits) -> DashboardRing {
        guard let total = habits.total, total > 0 else {
            return ring(.habits, title: "Привычки", fraction: nil, centre: noValue, spokenValue: spokenNoValue, caption: "План не задан")
        }
        guard let value = habits.value, let done = habits.done else {
            return ring(.habits, title: "Привычки", fraction: nil, centre: noValue, spokenValue: spokenNoValue, caption: "Нет данных")
        }
        return ring(
            .habits, title: "Привычки", fraction: Double(value) / percent, centre: "\(value)%", spokenValue: "\(value)%",
            caption: "\(done) из \(total) отметок"
        )
    }

    private static func challengesRing(_ challenges: DashboardScoresDTO.Challenges) -> DashboardRing {
        guard let total = challenges.total, total > 0, let done = challenges.done else {
            return ring(
                .challenges, title: "Челленджи", fraction: nil, centre: noValue, spokenValue: spokenNoValue, caption: "Челленджей нет"
            )
        }
        return ring(
            .challenges, title: "Челленджи", fraction: Double(done) / Double(total), centre: "\(done)/\(total)",
            spokenValue: "\(done) из \(total)", caption: "выполнено"
        )
    }

    /// The server's `good`/`fair`/`poor`; a word the app does not know yet shows no label.
    static func healthWord(_ label: String?) -> String? {
        switch label {
        case "good": return "Хорошо"
        case "fair": return "Средне"
        case "poor": return "Ниже нормы"
        default: return nil
        }
    }

    // MARK: Tone

    static func tone(delta: Int?, higherIsBetter: Bool) -> DashboardTone {
        guard let delta, delta != 0 else { return .same }
        return (delta > 0) == higherIsBetter ? .better : .worse
    }

    static func toneWord(_ tone: DashboardTone) -> String? {
        switch tone {
        case .better: return "лучше нормы"
        case .worse: return "хуже нормы"
        case .same: return nil
        }
    }

    // MARK: Values

    private static let minutesUnit = "min"
    private static let minus = "\u{2212}"
    private static let noBreakSpace: Character = "\u{00A0}"
    private static let digitsPerGroup = 3

    /// `7 200`, with a no-break space between thousands so a number never wraps in the middle.
    private static func grouped(_ number: Int) -> String {
        var out: [Character] = []
        for (index, digit) in String(abs(number)).reversed().enumerated() {
            if index > 0, index % digitsPerGroup == 0 { out.append(noBreakSpace) }
            out.append(digit)
        }
        return (number < 0 ? minus : "") + String(out.reversed())
    }

    /// `58 уд/мин`, `7 200 шагов`, `7 ч 15 мин` for minutes.
    static func value(identifier: String, value: Int, unit: String) -> String {
        if unit == minutesUnit { return HealthMetricsFormat.sleepDuration(Double(value)) }
        let label = HealthMetricsFormat.unitLabel(identifier: identifier, unit: unit)
        return label.isEmpty ? grouped(value) : "\(grouped(value)) \(label)"
    }

    /// The distance from the personal norm: signed, in the metric's own unit.
    static func deltaText(_ metric: DashboardHealthMetricDTO) -> String {
        guard let delta = metric.baselineDelta else { return "нормы пока нет" }
        if delta == 0 { return "на уровне нормы" }
        let magnitude = value(identifier: metric.identifier, value: abs(delta), unit: metric.unit)
        return "\(delta > 0 ? "+" : minus)\(magnitude) от вашей нормы"
    }

    // MARK: Dates

    /// «сегодня» and «вчера» by the server's day, `d MMM` otherwise.
    static func bestDayText(_ date: String, today: String) -> String {
        if date == today { return "сегодня" }
        if date == HealthMetricsFormat.shiftDate(today, by: -1) { return "вчера" }
        return HealthMetricsFormat.dayLabel(date)
    }

    private static let isoDayLength = 10
    private static let isoClockRange = 11..<16

    /// «31 окт., 09:00» out of `2026-10-31T09:00:00+03:00`. The offset is dropped on purpose: the text was made in the server's day, and a conversion could move it to another date.
    static func generatedAtText(_ iso: String) -> String? {
        let characters = Array(iso)
        guard characters.count >= isoClockRange.upperBound, characters[isoDayLength] == "T" else { return nil }
        let day = String(characters[0..<isoDayLength])
        let clock = String(characters[isoClockRange])
        guard day.split(separator: "-").count == 3, clock.split(separator: ":").count == 2 else { return nil }
        return "\(HealthMetricsFormat.dayLabel(day)), \(clock)"
    }

    static func rangeText(from: String, to: String) -> String {
        "\(HealthMetricsFormat.dayLabel(from)) — \(HealthMetricsFormat.dayLabel(to))"
    }

    // MARK: Streaks

    struct DayTally: Equatable {
        let done: Int
        let missed: Int
        let unknown: Int
    }

    static func tally(_ days: [Bool?]) -> DayTally {
        DayTally(
            done: days.filter { $0 == true }.count,
            missed: days.filter { $0 == false }.count,
            unknown: days.filter { $0 == nil }.count
        )
    }

    /// What the strip of dots means in words, since the dots alone are only colour and shape.
    static func dotsLabel(_ streak: DashboardStreakDTO) -> String {
        let counts = tally(streak.days)
        let doneWord = streak.isAvoid ? "без срыва" : "выполнено"
        let missedWord = streak.isAvoid ? "срывов" : "пропущено"
        return "Последние \(days(streak.days.count)): \(doneWord) \(counts.done), \(missedWord) \(counts.missed), нет данных \(counts.unknown)"
    }

    static func bestStreakText(_ count: Int) -> String { "лучшая серия \(days(count))" }

    // MARK: Workouts

    /// Bar heights in 0...1, scaled to the busiest week; a window with no workout stays flat.
    static func workoutFractions(_ weeks: [DashboardWorkoutWeekDTO]) -> [Double] {
        let busiest = weeks.map(\.count).max() ?? 0
        return weeks.map { busiest == 0 ? 0 : Double($0.count) / Double(busiest) }
    }

    static func workoutChangeText(_ delta: Int?) -> String? {
        guard let delta else { return nil }
        if delta == 0 { return "столько же, сколько в прошлом периоде" }
        return "\(delta > 0 ? "+" : minus)\(abs(delta)) к прошлому периоду"
    }

    static func workoutCount(_ count: Int) -> String {
        "\(count) \(plural(count, one: "тренировка", few: "тренировки", many: "тренировок"))"
    }

    static func workoutWeekLabel(_ week: DashboardWorkoutWeekDTO) -> String {
        "Неделя с \(HealthMetricsFormat.dayLabel(week.weekStart)): \(workoutCount(week.count)), \(HealthMetricsFormat.sleepDuration(Double(week.minutes)))"
    }

    // MARK: Plurals

    private static func plural(_ count: Int, one: String, few: String, many: String) -> String {
        let tail = count % 100
        if (11...14).contains(tail) { return many }
        switch count % 10 {
        case 1: return one
        case 2...4: return few
        default: return many
        }
    }

    /// `1 день`, `2 дня`, `5 дней`.
    static func days(_ count: Int) -> String {
        "\(count) \(plural(count, one: "день", few: "дня", many: "дней"))"
    }

    // MARK: States in words

    static let notConfiguredMessage = "Укажите адрес сервера в More → Settings"
    static let loadFailedMessage = "Не удалось загрузить сводку"
    static let serverFailedMessage = "Сервер не смог собрать сводку. Попробуйте ещё раз через минуту."
    static let offlineEmptyMessage = "Нет связи с сервером. Сохранённой сводки пока нет: подключитесь и повторите."
    static let retryTitle = "Повторить"

    private static let serverErrorFrom = 500

    static func message(for error: APIClientError) -> String {
        switch error {
        case .invalidBaseURL: return "Неверный адрес сервера"
        case .unauthorized: return "Неверный ключ API (401)"
        case .timeout: return "Сервер не ответил вовремя"
        case .transport: return offlineEmptyMessage
        case .unexpectedStatus(let status) where status >= serverErrorFrom: return serverFailedMessage
        case .unexpectedStatus(let status): return "Сервер ответил ошибкой \(status)"
        case .invalidResponse: return "Сервер вернул непонятный ответ"
        }
    }

    /// The summary on screen came from the read cache because the server did not answer.
    static func staleText(_ date: Date, timeZone: TimeZone = .current) -> String {
        "Не обновлено · по данным на \(HealthMetricsFormat.asOfText(date, timeZone: timeZone))"
    }
}
