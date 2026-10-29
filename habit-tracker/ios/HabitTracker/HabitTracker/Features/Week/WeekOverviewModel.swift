// [review:need-review] PHASE-03/222
// summary: pure model of the animated week overview — the slides («итоги недели») and the screen state (loading, failed, empty, ready with an unfinished-week note) built only from the GET /week-review answer; no requests, no animation here
import Foundation

/// How a slide's number is printed; the animated count and the static one use the same function.
enum WeekOverviewFormat: Equatable {
    case number
    case minutes
    case percent

    func text(_ value: Int) -> String {
        switch self {
        case .number: return WeekFormat.number(value)
        case .minutes: return WeekFormat.minutes(value)
        case .percent: return "\(value)%"
        }
    }
}

struct WeekOverviewSlide: Equatable, Identifiable {
    enum Kind: String, Equatable {
        case verdict, tasks, time, days, streak
    }

    let kind: Kind
    let title: String
    /// The number that counts up; `nil` for a slide that is only words.
    let figure: Int?
    let format: WeekOverviewFormat
    let caption: String
    /// Change against the previous week, printed with its sign.
    let change: String?
    let trend: WeekFormat.Trend

    var id: Kind { kind }

    /// The number as it stands when the motion is over.
    var figureText: String? { figure.map { format.text($0) } }
}

enum WeekOverviewState: Equatable {
    case loading
    case failed(String)
    case empty
    case ready(slides: [WeekOverviewSlide], note: String?)
}

enum WeekOverview {
    static let emptyText = WeekFormat.emptyWeekText

    static func state(
        loadState: WeekViewModel.LoadState, review: WeekReviewDTO?, note: String?
    ) -> WeekOverviewState {
        switch loadState {
        case .idle, .loading:
            return .loading
        case .failure(let message):
            return .failed(message)
        case .loaded:
            guard let review else { return .loading }
            if WeekFormat.isEmpty(review) { return .empty }
            return .ready(slides: slides(review), note: note)
        }
    }

    static func slides(_ review: WeekReviewDTO) -> [WeekOverviewSlide] {
        var result: [WeekOverviewSlide] = [verdictSlide(review)]
        if review.totals.tasksTotal > 0 { result.append(tasksSlide(review)) }
        if let time = timeSlide(review) { result.append(time) }
        if let days = daysSlide(review) { result.append(days) }
        if let streak = streakSlide(review) { result.append(streak) }
        return result
    }

    private static func verdictSlide(_ review: WeekReviewDTO) -> WeekOverviewSlide {
        let totals = review.totals
        var caption = "выигранных дней из \(totals.closedDays) закрытых"
        if let verdict = WeekFormat.weekVerdict(review) { caption = "\(verdict)\n\(caption)" }
        let change = WeekFormat.deltaCount(review.delta.wonDays)
        return WeekOverviewSlide(
            kind: .verdict, title: "Итог недели", figure: totals.wonDays, format: .number,
            caption: caption, change: "\(change) к прошлой неделе", trend: WeekFormat.trend(review.delta.wonDays)
        )
    }

    private static func tasksSlide(_ review: WeekReviewDTO) -> WeekOverviewSlide {
        let totals = review.totals
        var caption = "задач выполнено из \(WeekFormat.number(totals.tasksTotal))"
        if let pct = totals.planPct { caption += ", план \(pct)%" }
        return WeekOverviewSlide(
            kind: .tasks, title: "Задачи", figure: totals.tasksDone, format: .number, caption: caption,
            change: "\(WeekFormat.deltaCount(review.delta.tasksDone)) к прошлой неделе",
            trend: WeekFormat.trend(review.delta.tasksDone)
        )
    }

    private static func timeSlide(_ review: WeekReviewDTO) -> WeekOverviewSlide? {
        let totals = review.totals
        guard totals.roleMinutes > 0 || (totals.workMinutes ?? 0) > 0 else { return nil }
        let useWork = (totals.workMinutes ?? 0) > 0
        let minutes = useWork ? (totals.workMinutes ?? 0) : totals.roleMinutes
        let delta = useWork ? review.delta.workMinutes : review.delta.roleMinutes
        return WeekOverviewSlide(
            kind: .time, title: useWork ? "Время работы" : "Время по ролям", figure: minutes,
            format: .minutes, caption: "за \(WeekFormat.days(review.window.countedDays))",
            change: WeekFormat.deltaMinutes(delta).map { "\($0) к прошлой неделе" },
            trend: WeekFormat.trend(delta)
        )
    }

    private static func daysSlide(_ review: WeekReviewDTO) -> WeekOverviewSlide? {
        let lines = [
            WeekFormat.highlight(title: "Лучший день", date: review.bestDay, in: review.days),
            WeekFormat.highlight(title: "Худший день", date: review.worstDay, in: review.days),
        ].compactMap { $0 }
        guard !lines.isEmpty else { return nil }
        return WeekOverviewSlide(
            kind: .days, title: "Дни недели", figure: nil, format: .number,
            caption: lines.joined(separator: "\n"), change: nil, trend: .flat
        )
    }

    private static func streakSlide(_ review: WeekReviewDTO) -> WeekOverviewSlide? {
        guard let top = review.habitStreaks.max(by: { $0.currentStreak < $1.currentStreak }) else { return nil }
        return WeekOverviewSlide(
            kind: .streak, title: "Серия без срывов", figure: top.currentStreak, format: .number,
            caption: "дн. подряд · \(top.name)",
            change: nil, trend: .flat
        )
    }
}
