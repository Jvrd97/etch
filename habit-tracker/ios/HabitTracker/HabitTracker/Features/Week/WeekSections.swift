// [review:need-review] PHASE-03/229, PHASE-03/243, PHASE-03/244
// summary: PHASE-03/244 adds the supplements block (taken of planned, «данных мало») and the «Совет» block (a button, states, the disclaimer visible before anything is asked)
// summary: the blocks of the Week screen — header with the period, the note under an unfinished week and the neighbour-week buttons, totals against the previous week, the seven days with the best and the worst named in words, role and category time, avoid streaks, health with "Метрика не подключена", and the AI narrative; every change is printed with its sign so colour never carries meaning alone
import SwiftUI

/// Sizes and weights of the screen, named so none of them is a bare number in a view.
private enum Layout {
    /// The smallest side of anything the finger must hit.
    static let minTap: CGFloat = 44
    static let titleScale: CGFloat = 0.6
    static let valueScale: CGFloat = 0.7
    static let statValueSize: CGFloat = 26
    static let healthValueSize: CGFloat = 22
    static let dayVerdictSize: CGFloat = 11
    static let dayMarkSize: CGFloat = 10
    static let noteFillOpacity = 0.1
    static let noteStrokeOpacity = 0.4
    static let wonBorderOpacity = 0.6
    static let lostBorderOpacity = 0.5
    static let narrativeLoaderHeight: CGFloat = 100
    static let disabledOpacity = 0.4
}

private func tone(_ trend: WeekFormat.Trend) -> Color {
    switch trend {
    case .up: return DS.Palette.lime
    case .down: return DS.Palette.danger
    case .flat: return DS.Palette.textSecondary
    }
}

private struct WeekSection<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.md) {
            Text(title)
                .font(DS.Typography.section)
                .foregroundStyle(DS.Palette.textPrimary)
                .accessibilityAddTraits(.isHeader)
            content
        }
    }
}

/// A change against the previous week: the sign is the text, the colour only repeats it.
private struct Change: View {
    let text: String?
    let delta: Int?

    var body: some View {
        if let text {
            Text(text).foregroundStyle(tone(WeekFormat.trend(delta)))
        } else {
            Text("—").foregroundStyle(DS.Palette.textDisabled)
        }
    }
}

private struct HintText: View {
    let text: String

    var body: some View {
        Text(text)
            .font(DS.Typography.body)
            .foregroundStyle(DS.Palette.textDisabled)
    }
}

/// One row of a list card: a name on the left, a figure and its change on the right.
private struct WeekRow<Detail: View, Figure: View>: View {
    let name: String
    @ViewBuilder let detail: Detail
    @ViewBuilder let figure: Figure

    var body: some View {
        HStack(alignment: .center, spacing: DS.Spacing.md) {
            VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                Text(name)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textPrimary)
                detail
            }
            Spacer(minLength: DS.Spacing.sm)
            VStack(alignment: .trailing, spacing: DS.Spacing.xs) { figure }
                .font(DS.Typography.caption)
                .foregroundStyle(DS.Palette.textSecondary)
                .monospacedDigit()
        }
        .padding(.vertical, DS.Spacing.sm)
        .accessibilityElement(children: .combine)
    }
}

// MARK: Header

struct WeekHeaderView: View {
    @ObservedObject var viewModel: WeekViewModel
    let window: WeekWindowDTO

    var body: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.md) {
            Text("Неделя \(window.isoCode)")
                .font(DS.Typography.h1)
                .foregroundStyle(DS.Palette.textPrimary)
                .minimumScaleFactor(Layout.titleScale)
                .lineLimit(1)
            Text("\(WeekFormat.period(window)) · сутки с \(window.dayStartHour):00, \(window.timezone)")
                .font(DS.Typography.caption)
                .foregroundStyle(DS.Palette.textSecondary)
            if let asOf = viewModel.offlineAsOf {
                WeekOfflineNote(updatedAt: asOf)
            }
            if let note = viewModel.partialNote {
                Text(note)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textPrimary)
                    .padding(DS.Spacing.md)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(DS.Palette.lime.opacity(Layout.noteFillOpacity))
                    .clipShape(RoundedRectangle(cornerRadius: DS.Radius.control, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: DS.Radius.control, style: .continuous)
                            .stroke(DS.Palette.lime.opacity(Layout.noteStrokeOpacity), lineWidth: 1)
                    )
            }
            if let message = viewModel.refreshError {
                Text("Не обновилось: \(message)")
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.danger)
            }
            WeekStepper(viewModel: viewModel, window: window)
        }
    }
}

/// «Нет связи · обновлено 27 окт., 09:41» — the last answer, with the moment it was fetched.
struct WeekOfflineNote: View {
    let updatedAt: Date

    var body: some View {
        Label("Нет связи · \(WeekFormat.updatedCaption(updatedAt))", systemImage: "wifi.slash")
            .font(DS.Typography.caption)
            .foregroundStyle(DS.Palette.textSecondary)
    }
}

private struct WeekStepper: View {
    @ObservedObject var viewModel: WeekViewModel
    let window: WeekWindowDTO

    var body: some View {
        HStack {
            Button {
                Task { await viewModel.showPrevious() }
            } label: {
                Label(window.previousIsoCode, systemImage: "chevron.left")
                    .stepperHitArea(alignment: .leading)
            }
            .accessibilityLabel("Неделя \(window.previousIsoCode)")
            Spacer(minLength: DS.Spacing.sm)
            if viewModel.showsCurrentButton {
                Button {
                    Task { await viewModel.showCurrent() }
                } label: {
                    Text("Текущая").stepperHitArea(alignment: .center)
                }
            }
            Spacer(minLength: DS.Spacing.sm)
            Button {
                Task { await viewModel.showNext() }
            } label: {
                HStack(spacing: DS.Spacing.xs) {
                    Text(window.nextIsoCode)
                    Image(systemName: "chevron.right")
                }
                .stepperHitArea(alignment: .trailing)
            }
            .accessibilityLabel("Неделя \(window.nextIsoCode)")
        }
        .font(DS.Typography.caption)
        .foregroundStyle(DS.Palette.lime)
        .buttonStyle(.plain)
    }
}

private extension View {
    /// The whole 44 pt box answers the finger, not just the glyphs inside it.
    func stepperHitArea(alignment: Alignment) -> some View {
        frame(minWidth: Layout.minTap, minHeight: Layout.minTap, alignment: alignment)
            .contentShape(Rectangle())
    }
}

// MARK: Totals

private struct StatCard: View {
    let label: String
    let value: String
    var hint: String?
    let change: AnyView

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                Text(label)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
                Text(value)
                    .font(.system(size: Layout.statValueSize, weight: .bold))
                    .foregroundStyle(DS.Palette.textPrimary)
                    .minimumScaleFactor(Layout.valueScale)
                    .lineLimit(1)
                if let hint {
                    Text(hint)
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                }
                change.font(DS.Typography.caption)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

struct WeekTotalsView: View {
    let review: WeekReviewDTO

    private var totals: WeekTotalsDTO { review.totals }
    private var delta: WeekDeltaDTO { review.delta }

    var body: some View {
        WeekSection(title: "Итог недели") {
            if let line = WeekFormat.serverVerdictLine(review) {
                // The server's line already carries the rule, the numbers and the debt.
                Text(line)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textSecondary)
            } else {
                if let verdict = WeekFormat.weekVerdict(review) {
                    Text(verdict)
                        .font(DS.Typography.card)
                        .foregroundStyle(review.isWon == true ? DS.Palette.lime : DS.Palette.textPrimary)
                }
                if let debt = WeekFormat.debtLine(review) {
                    Text(debt)
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.warning)
                }
            }
            LazyVGrid(
                columns: [GridItem(.flexible(), spacing: DS.Spacing.md), GridItem(.flexible())],
                spacing: DS.Spacing.md
            ) {
                StatCard(
                    label: "Выиграно дней",
                    value: WeekFormat.number(totals.wonDays),
                    hint: "из \(totals.closedDays) закрытых",
                    change: AnyView(
                        HStack(spacing: 0) {
                            Change(text: WeekFormat.deltaCount(delta.wonDays), delta: delta.wonDays)
                            Text(" · было \(review.previousTotals.wonDays)")
                                .foregroundStyle(DS.Palette.textDisabled)
                        }
                    )
                )
                StatCard(
                    label: "План",
                    value: totals.planPct.map { "\($0)%" } ?? "—",
                    hint: "\(totals.tasksDone) из \(totals.tasksTotal) задач",
                    change: AnyView(
                        Change(text: WeekFormat.deltaPoints(delta.planPct), delta: delta.planPct)
                    )
                )
                StatCard(
                    label: "Рабочее время",
                    value: totals.workMinutes.map(WeekFormat.minutes) ?? "—",
                    change: AnyView(
                        Change(
                            text: WeekFormat.deltaMinutes(delta.workMinutes), delta: delta.workMinutes
                        )
                    )
                )
                StatCard(
                    label: "Серия дней",
                    value: totals.dayStreakEnd.map(WeekFormat.number) ?? "—",
                    hint: totals.dayStreakEnd == nil ? nil : "на конец недели",
                    change: AnyView(
                        Text(
                            totals.anchorsTotal > 0
                                ? "Якоря: \(totals.anchorsDone) из \(totals.anchorsTotal)"
                                : "Якорей не было"
                        )
                        .foregroundStyle(DS.Palette.textSecondary)
                    )
                )
            }
        }
    }
}

// MARK: Days

private struct DayCell: View {
    let day: WeekDayStatDTO
    let mark: String?

    private var verdict: String { WeekFormat.dayVerdict(day) }

    private var border: Color {
        switch WeekFormat.outcome(day) {
        case .won: return DS.Palette.lime.opacity(Layout.wonBorderOpacity)
        case .lost: return DS.Palette.danger.opacity(Layout.lostBorderOpacity)
        case .notCounted, .open: return DS.Palette.cardStroke
        }
    }

    var body: some View {
        VStack(spacing: DS.Spacing.xs) {
            Text(WeekFormat.weekdayShort(day.weekday))
                .foregroundStyle(DS.Palette.textDisabled)
            Text(WeekFormat.shortDate(day.date))
                .foregroundStyle(DS.Palette.textSecondary)
            Text(WeekFormat.shortDayVerdict(day))
                .font(.system(size: Layout.dayVerdictSize))
                .foregroundStyle(DS.Palette.textPrimary)
                .lineLimit(1)
                .minimumScaleFactor(Layout.valueScale)
            Text(day.counted && day.tasksTotal > 0 ? "\(day.tasksDone)/\(day.tasksTotal)" : "·")
                .foregroundStyle(DS.Palette.textSecondary)
            Text(mark ?? " ")
                .font(.system(size: Layout.dayMarkSize, weight: .semibold))
                .foregroundStyle(DS.Palette.lime)
                .lineLimit(1)
                .minimumScaleFactor(Layout.valueScale)
        }
        .font(DS.Typography.caption)
        .monospacedDigit()
        .padding(.vertical, DS.Spacing.sm)
        .frame(maxWidth: .infinity)
        .background(DS.Palette.card)
        .clipShape(RoundedRectangle(cornerRadius: DS.Radius.chip, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: DS.Radius.chip, style: .continuous)
                .stroke(border, lineWidth: 1)
        )
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityText)
    }

    private var accessibilityText: String {
        var text = "\(WeekFormat.weekdayShort(day.weekday)) \(WeekFormat.shortDate(day.date)), \(verdict)"
        if day.counted && day.tasksTotal > 0 { text += ", \(day.tasksDone) из \(day.tasksTotal) задач" }
        if let mark { text += ", \(mark) день" }
        return text
    }
}

struct WeekDaysView: View {
    let review: WeekReviewDTO

    var body: some View {
        WeekSection(title: "Дни") {
            HStack(spacing: DS.Spacing.xs) {
                ForEach(review.days) { day in
                    DayCell(day: day, mark: mark(for: day))
                }
            }
            if let best = WeekFormat.highlight(title: "Лучший день", date: review.bestDay, in: review.days) {
                Text(best).font(DS.Typography.body).foregroundStyle(DS.Palette.textPrimary)
            }
            if let worst = WeekFormat.highlight(title: "Худший день", date: review.worstDay, in: review.days) {
                Text(worst).font(DS.Typography.body).foregroundStyle(DS.Palette.textPrimary)
            }
            if review.bestDay == nil {
                HintText(text: "Закрытых дней пока нет: лучшего и худшего нет.")
            }
        }
    }

    private func mark(for day: WeekDayStatDTO) -> String? {
        if day.date == review.bestDay { return "лучший" }
        if day.date == review.worstDay { return "худший" }
        return nil
    }
}

// MARK: Roles, categories, streaks

struct WeekRolesView: View {
    let review: WeekReviewDTO

    private var rows: [WeekRoleSliceDTO] {
        review.roles.filter { $0.minutes > 0 || $0.previousMinutes > 0 }
    }

    var body: some View {
        WeekSection(title: "Время по ролям") {
            if rows.isEmpty {
                HintText(text: "Минуты по ролям не записаны.")
            } else {
                Card {
                    VStack(spacing: 0) {
                        ForEach(rows) { role in
                            WeekRow(name: role.title) {
                                EmptyView()
                            } figure: {
                                Text("\(WeekFormat.minutes(role.minutes)) · \(role.sharePct)%")
                                Change(
                                    text: WeekFormat.deltaMinutes(role.deltaMinutes), delta: role.deltaMinutes
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

struct WeekCategoriesView: View {
    let review: WeekReviewDTO

    var body: some View {
        WeekSection(title: "Время по категориям") {
            if review.categories.isEmpty {
                HintText(text: "Записей со временем нет.")
            } else {
                Card {
                    VStack(spacing: 0) {
                        ForEach(review.categories) { category in
                            WeekRow(name: category.name) {
                                Text("\(WeekFormat.days(category.entryDays)) с записью")
                                    .font(DS.Typography.caption)
                                    .foregroundStyle(DS.Palette.textDisabled)
                            } figure: {
                                Text(WeekFormat.minutes(category.minutes))
                                Change(
                                    text: WeekFormat.deltaMinutes(category.deltaMinutes),
                                    delta: category.deltaMinutes
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

struct WeekStreaksView: View {
    let review: WeekReviewDTO

    var body: some View {
        WeekSection(title: "Серии привычек") {
            if review.habitStreaks.isEmpty {
                HintText(text: "Привычек «избегать» с историей нет.")
            } else {
                Card {
                    VStack(spacing: 0) {
                        ForEach(review.habitStreaks) { streak in
                            WeekRow(name: streak.name) {
                                EmptyView()
                            } figure: {
                                Text(WeekFormat.days(streak.currentStreak))
                                Text(
                                    streak.relapses > 0
                                        ? "\(WeekFormat.relapses(streak.relapses)) за неделю" : "без срывов"
                                )
                                .foregroundStyle(
                                    streak.relapses > 0 ? DS.Palette.danger : DS.Palette.textDisabled
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

// MARK: Health

private struct HealthCard: View {
    let metric: WeekHealthMetricDTO

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                Text(metric.name)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
                if !metric.available {
                    HintText(text: WeekFormat.metricMissing)
                } else if let average = metric.avgPerDay {
                    Text("\(WeekFormat.healthValue(unit: metric.unit, average)) в день")
                        .font(.system(size: Layout.healthValueSize, weight: .bold))
                        .foregroundStyle(DS.Palette.textPrimary)
                        .minimumScaleFactor(Layout.valueScale)
                        .lineLimit(1)
                    HStack(spacing: 0) {
                        if let change = WeekFormat.healthDelta(metric) {
                            Text(change).foregroundStyle(tone(WeekFormat.trend(metric.deltaAvgPerDay)))
                        } else {
                            Text("—").foregroundStyle(DS.Palette.textDisabled)
                        }
                        Text(" · \(WeekFormat.days(metric.daysWithData)) с данными")
                            .foregroundStyle(DS.Palette.textDisabled)
                    }
                    .font(DS.Typography.caption)
                } else {
                    HintText(text: WeekFormat.noData)
                }
            }
        }
        .accessibilityElement(children: .combine)
    }
}

struct WeekHealthView: View {
    let review: WeekReviewDTO

    var body: some View {
        WeekSection(title: "Здоровье") {
            VStack(spacing: DS.Spacing.md) {
                ForEach(review.health) { HealthCard(metric: $0) }
            }
        }
    }
}

// MARK: Narrative

struct WeekNarrativeView: View {
    @ObservedObject var viewModel: WeekViewModel
    let review: WeekReviewDTO

    private var buttonTitle: String {
        if case .ready = viewModel.narrative { return "Написать заново" }
        return "Написать итог недели"
    }

    var body: some View {
        WeekSection(title: "Итог от ИИ") {
            switch viewModel.narrative {
            case .ready(let text):
                Card {
                    VStack(alignment: .leading, spacing: DS.Spacing.md) {
                        Text(text)
                            .font(DS.Typography.body)
                            .foregroundStyle(DS.Palette.textPrimary)
                            .textSelection(.enabled)
                        Text("Текст написан моделью по цифрам выше и не сохраняется.")
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.textDisabled)
                    }
                }
            case .failure(let message):
                Text(message)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.danger)
            case .writing:
                NeonLoader(label: "Пишу итог…").frame(height: Layout.narrativeLoaderHeight)
            case .idle:
                EmptyView()
            }
            if WeekFormat.isEmpty(review) {
                HintText(text: "Итог можно написать, когда в неделе появятся данные.")
            } else {
                Button {
                    Task { await viewModel.writeNarrative() }
                } label: {
                    Text(viewModel.narrative == .writing ? "Пишу итог…" : buttonTitle)
                }
                .buttonStyle(LimeButtonStyle())
                .disabled(!viewModel.canWriteNarrative)
                .opacity(viewModel.canWriteNarrative ? 1 : Layout.disabledOpacity)
            }
        }
        .accessibilityElement(children: .contain)
    }
}

// MARK: Supplements (#244)

struct WeekSupplementsView: View {
    let adherence: WeekAdherenceDTO

    var body: some View {
        WeekSection(title: "Добавки") {
            Card {
                VStack(alignment: .leading, spacing: DS.Spacing.sm) {
                    HStack(alignment: .firstTextBaseline, spacing: DS.Spacing.md) {
                        Text("\(adherence.taken) из \(adherence.planned)")
                            .font(.system(size: Layout.statValueSize, weight: .bold))
                            .foregroundStyle(DS.Palette.textPrimary)
                        if adherence.enoughData, let pct = adherence.pct {
                            Text("\(pct)%")
                                .font(DS.Typography.body)
                                .foregroundStyle(DS.Palette.textSecondary)
                        }
                    }
                    if !adherence.enoughData {
                        HintText(text: WeekFormat.supplementsFewDays)
                    }
                    ForEach(adherence.supplements) { item in
                        HStack {
                            Text(item.name)
                                .font(DS.Typography.body)
                                .foregroundStyle(DS.Palette.textPrimary)
                            Spacer(minLength: DS.Spacing.md)
                            Text("\(item.takenDays) из \(item.plannedDays) дн.")
                                .font(DS.Typography.caption)
                                .foregroundStyle(DS.Palette.textSecondary)
                        }
                    }
                }
            }
        }
        .accessibilityElement(children: .contain)
    }
}

// MARK: Advice (#244)

struct WeekAdviceView: View {
    @ObservedObject var viewModel: WeekViewModel

    private var buttonTitle: String {
        switch viewModel.advice {
        case .writing: return "Пишу совет…"
        case .ready: return "Написать заново"
        case .idle, .notEnoughData, .failure: return "Написать совет"
        }
    }

    var body: some View {
        WeekSection(title: "Совет") {
            HintText(text: "Сон, спорт и добавки за последние 7 дней против 7 дней до них.")
            Text(WeekFormat.adviceDisclaimer)
                .font(DS.Typography.body.weight(.medium))
                .foregroundStyle(DS.Palette.textPrimary)
            switch viewModel.advice {
            case .ready(let advice):
                Card {
                    VStack(alignment: .leading, spacing: DS.Spacing.md) {
                        Text(advice.text)
                            .font(DS.Typography.body)
                            .foregroundStyle(DS.Palette.textPrimary)
                            .textSelection(.enabled)
                        Text("За \(WeekFormat.shortDate(advice.startsOn)) — \(WeekFormat.shortDate(advice.endsOn)) "
                            + "(\(advice.days) дн.). Текст написан моделью по цифрам и не сохраняется.")
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.textDisabled)
                    }
                }
            case .notEnoughData:
                HintText(text: WeekFormat.adviceNotEnoughData)
            case .failure(let message):
                Text(message)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.danger)
            case .writing:
                NeonLoader(label: "Пишу совет…").frame(height: Layout.narrativeLoaderHeight)
            case .idle:
                EmptyView()
            }
            Button {
                Task { await viewModel.writeAdvice() }
            } label: {
                Text(buttonTitle)
            }
            .buttonStyle(LimeButtonStyle())
            .disabled(!viewModel.canWriteAdvice)
            .opacity(viewModel.canWriteAdvice ? 1 : Layout.disabledOpacity)
        }
        .accessibilityElement(children: .contain)
    }
}
