// [review:need-review] PHASE-01/274
// [review:need-review] PHASE-01/270 — links to Day and Week, VoiceOver week picking, canvas on cached statuses
// [review:need-review] PHASE-01/265
// summary: Life screen (More → Жизнь) — the weeks-lived counter with the birth date and frame, five views of one timeline (жизнь as a canvas of weeks, год, месяц, неделя, день), the legend; states: loading, error with retry, offline note with the cached moment, pull to refresh in place; no navigation stack of its own
// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 — the cached timeline is drawn before the first frame
import SwiftUI

struct LifeView: View {
    @StateObject private var viewModel: LifeViewModel

    /// Where a link to a day or a week goes: the Day tab and the Неделя screen.
    private let open: (AppDestination) -> Void

    /// The model builds its client with `.live()`.
    init(open: @escaping (AppDestination) -> Void = { _ in }) {
        _viewModel = StateObject(wrappedValue: .live())
        self.open = open
    }

    init(viewModel: LifeViewModel, open: @escaping (AppDestination) -> Void = { _ in }) {
        _viewModel = StateObject(wrappedValue: viewModel)
        self.open = open
    }

    var body: some View {
        content
            .navigationTitle(MoreDestination.life.title)
            .dsScreenBackground()
            .onAppear { viewModel.showCached() }
            .task { await viewModel.appear() }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .idle, .loading:
            NeonLoader(label: "Загрузка")
        case .failure(let message):
            DSErrorState(message: message) { Task { await viewModel.load() } }
        case .loaded:
            loaded
        }
    }

    private var loaded: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DS.Spacing.xl) {
                if let asOf = viewModel.offlineAsOf {
                    OfflineBanner(updatedAt: asOf)
                }
                if let refreshError = viewModel.refreshError {
                    Text(refreshError)
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.warning)
                }
                Text("Один квадрат — один день. Лаймовый — выигран, серый — проигран, пустой контур — не закрыт.")
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textSecondary)
                LifeCounterCard(viewModel: viewModel)
                LifeViewPicker(viewModel: viewModel)
                LifeBody(viewModel: viewModel, open: open)
                LifeLegend()
            }
            .padding(DS.Spacing.lg)
        }
        .refreshable { await viewModel.refresh() }
    }
}

private struct LifeCard<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        content
            .padding(DS.Spacing.lg)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(DS.Palette.card, in: RoundedRectangle(cornerRadius: DS.Radius.card))
            .overlay(RoundedRectangle(cornerRadius: DS.Radius.card).stroke(DS.Palette.cardStroke))
    }
}

private struct LifeCounterCard: View {
    @ObservedObject var viewModel: LifeViewModel
    @State private var birthDraft = ""
    @State private var birthInvalid = false

    var body: some View {
        LifeCard {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                if let counter = viewModel.counter {
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: DS.Spacing.md) {
                        figure("Возраст", "\(counter.years)")
                        figure("Прожито", String(format: "%.1f%%", counter.percent))
                        figure("Прожито недель", "\(counter.weeksLived)", suffix: "из \(counter.weeksTotal)")
                        figure("Осталось недель", "\(counter.weeksLeft)", accent: true)
                    }
                    ProgressView(value: counter.percent, total: 100)
                        .tint(DS.Palette.lime)
                }
                HStack {
                    Text("Дата рождения")
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                    Spacer()
                    TextField("ГГГГ-ММ-ДД", text: $birthDraft)
                        .keyboardType(.numbersAndPunctuation)
                        .multilineTextAlignment(.trailing)
                        .foregroundStyle(birthInvalid ? DS.Palette.danger : DS.Palette.textPrimary)
                        .frame(width: 130)
                        .onSubmit(commitBirth)
                        .onChange(of: birthDraft) { _, _ in commitBirth() }
                        .accessibilityIdentifier("life.birth")
                }
                Stepper(value: Binding(get: { viewModel.frame.targetYears }, set: { viewModel.setTargetYears($0) }), in: LifeFrame.yearsRange) {
                    Text("Рамка, лет: \(viewModel.frame.targetYears)")
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                }
                Text("Рамка — не прогноз, а линейка: она нужна, чтобы видеть масштаб, а не чтобы знать дату.")
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textDisabled)
            }
        }
        .onAppear { birthDraft = viewModel.frame.birth }
    }

    /// A date that does not parse is not saved; the field turns red until it does.
    private func commitBirth() {
        guard birthDraft != viewModel.frame.birth else { birthInvalid = false; return }
        birthInvalid = !viewModel.setBirth(birthDraft)
    }

    private func figure(_ title: String, _ value: String, suffix: String? = nil, accent: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(DS.Typography.caption).foregroundStyle(DS.Palette.textSecondary)
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(value)
                    .font(DS.Typography.section)
                    .foregroundStyle(accent ? DS.Palette.lime : DS.Palette.textPrimary)
                if let suffix {
                    Text(suffix).font(DS.Typography.caption).foregroundStyle(DS.Palette.textSecondary)
                }
            }
        }
    }
}

private struct LifeViewPicker: View {
    @ObservedObject var viewModel: LifeViewModel

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: DS.Spacing.sm) {
                ForEach(LifeViewKind.allCases) { kind in
                    Button { viewModel.select(kind) } label: {
                        Text(kind.title)
                            .font(DS.Typography.caption)
                            .foregroundStyle(viewModel.view == kind ? Color.black : DS.Palette.textSecondary)
                            .padding(.horizontal, DS.Spacing.lg)
                            .padding(.vertical, DS.Spacing.sm)
                            .background(viewModel.view == kind ? DS.Palette.lime : DS.Palette.surface, in: Capsule())
                    }
                    .buttonStyle(.plain)
                        .accessibilityAddTraits(viewModel.view == kind ? .isSelected : [])
                }
            }
        }
    }
}

private struct LifeBody: View {
    @ObservedObject var viewModel: LifeViewModel
    let open: (AppDestination) -> Void

    var body: some View {
        if let cursor = viewModel.cursor, let today = viewModel.todayISO {
            switch viewModel.view {
            case .life: LifeWeeksCanvas(viewModel: viewModel)
            case .year: LifeYearView(viewModel: viewModel, cursor: cursor)
            case .month: LifeMonthView(viewModel: viewModel, cursor: cursor, today: today)
            case .week: LifeWeekView(viewModel: viewModel, cursor: cursor, open: open)
            case .day: LifeDayView(viewModel: viewModel, cursor: cursor, open: open)
            }
        }
    }
}

private struct LifeStepper: View {
    let title: String
    let onStep: (Int) -> Void

    var body: some View {
        HStack(spacing: DS.Spacing.md) {
            Button { onStep(-1) } label: { Image(systemName: "chevron.left") }
                .accessibilityLabel("Назад")
            Text(title).font(DS.Typography.card).foregroundStyle(DS.Palette.textPrimary)
            Button { onStep(1) } label: { Image(systemName: "chevron.right") }
                .accessibilityLabel("Вперёд")
            Spacer()
        }
        .tint(DS.Palette.lime)
    }
}

/// One row per year of life, one cell per week; a tap on a cell opens that week. VoiceOver walks the weeks
/// with the adjustable swipe (from the running week) and opens the one it stands on.
private struct LifeWeeksCanvas: View {
    @ObservedObject var viewModel: LifeViewModel
    @State private var spokenIndex: Int?
    /// Width of the row-number column, in cells.
    private let labelCells = 3.0

    var body: some View {
        let rows = viewModel.frame.targetYears
        let columns = Double(LifeCalendar.weeksPerRow) + labelCells
        let statuses = viewModel.weekStatuses
        Color.clear
            .aspectRatio(columns / Double(rows), contentMode: .fit)
            .overlay(
                GeometryReader { geometry in
                    let stride = geometry.size.width / columns
                    Canvas { context, _ in draw(context, stride: stride, rows: rows, statuses: statuses) }
                        .contentShape(Rectangle())
                        .gesture(SpatialTapGesture().onEnded { tap in
                            if let cell = LifeCalendar.gridCell(x: tap.location.x, y: tap.location.y, stride: stride, labelCells: labelCells, rows: rows),
                               let monday = viewModel.weekMonday(row: cell.row, column: cell.column) {
                                viewModel.pickWeek(monday)
                            }
                        })
                }
            )
            .accessibilityElement()
            .accessibilityLabel("Сетка жизни по неделям, \(rows) лет")
            .accessibilityValue(viewModel.weekSpeech(index: min(spokenIndex ?? viewModel.currentWeekIndex ?? 0, statuses.count - 1)) ?? "")
            .accessibilityHint("Листайте вверх и вниз, чтобы выбрать неделю, двойное касание открывает её")
            .accessibilityAdjustableAction { direction in
                let last = statuses.count - 1
                let current = min(spokenIndex ?? viewModel.currentWeekIndex ?? 0, last)
                switch direction {
                case .increment: spokenIndex = min(current + 1, last)
                case .decrement: spokenIndex = max(current - 1, 0)
                @unknown default: break
                }
            }
            .accessibilityAction {
                let index = min(spokenIndex ?? viewModel.currentWeekIndex ?? 0, statuses.count - 1)
                if let birth = LifeCalendar.parse(viewModel.frame.birth) {
                    viewModel.pickWeek(LifeCalendar.weekMonday(birth: birth, index: index))
                }
            }
    }

    private func draw(_ context: GraphicsContext, stride: CGFloat, rows: Int, statuses: [LifeStatus]) {
        guard viewModel.todayISO != nil else { return }
        let gap = max(0.5, stride * 0.18)
        let current = viewModel.currentWeekIndex
        for row in 0..<rows {
            if row % 5 == 0 {
                context.draw(
                    Text("\(row)").font(.system(size: max(6, stride * 0.9))).foregroundColor(DS.Palette.textDisabled),
                    at: CGPoint(x: stride * (labelCells - 0.4), y: (CGFloat(row) + 0.5) * stride), anchor: .trailing
                )
            }
            for column in 0..<LifeCalendar.weeksPerRow {
                let index = row * LifeCalendar.weeksPerRow + column
                guard index < statuses.count else { continue }
                let status = statuses[index]
                let rect = CGRect(
                    x: (labelCells + CGFloat(column)) * stride + gap / 2, y: CGFloat(row) * stride + gap / 2,
                    width: stride - gap, height: stride - gap
                )
                let path = Path(roundedRect: rect, cornerRadius: stride * 0.15)
                context.fill(path, with: .color(status.fill))
                context.stroke(path, with: .color(status.stroke), style: StrokeStyle(lineWidth: 0.6, dash: status.dash.map { $0 / 3 }))
                if index == current {
                    context.stroke(Path(roundedRect: rect.insetBy(dx: -1, dy: -1), cornerRadius: stride * 0.2), with: .color(.white.opacity(0.8)), lineWidth: 1)
                }
            }
        }
    }
}

private struct LifeYearView: View {
    @ObservedObject var viewModel: LifeViewModel
    let cursor: Date

    var body: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.lg) {
            LifeStepper(title: String(LifeCalendar.year(cursor))) { viewModel.step($0) }
            LazyVGrid(columns: [GridItem(.flexible(), spacing: DS.Spacing.md), GridItem(.flexible())], spacing: DS.Spacing.md) {
                ForEach(1...12, id: \.self) { month in
                    let first = LifeCalendar.date(year: LifeCalendar.year(cursor), month: month)
                    LifeCard {
                        VStack(alignment: .leading, spacing: DS.Spacing.sm) {
                            Button(LifeCalendar.monthName(month)) { viewModel.pickMonth(first) }
                                .font(DS.Typography.caption)
                                .foregroundStyle(DS.Palette.textSecondary)
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 12, maximum: 12), spacing: 3)], alignment: .leading, spacing: 3) {
                                ForEach(LifeCalendar.monthDates(first), id: \.self) { date in
                                    daySquare(viewModel, date, size: 12)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

private struct LifeMonthView: View {
    @ObservedObject var viewModel: LifeViewModel
    let cursor: Date
    let today: String

    var body: some View {
        let weeks = Dictionary(grouping: LifeCalendar.monthDates(cursor)) { LifeCalendar.iso(LifeCalendar.startOfWeek($0)) }
        VStack(alignment: .leading, spacing: DS.Spacing.lg) {
            LifeStepper(title: "\(LifeCalendar.monthName(LifeCalendar.month(cursor))) \(LifeCalendar.year(cursor))") { viewModel.step($0) }
            ForEach(weeks.keys.sorted(), id: \.self) { key in
                HStack(spacing: DS.Spacing.md) {
                    let monday = LifeCalendar.parse(key) ?? cursor
                    Button(LifeCalendar.isoWeekCode(monday)) { viewModel.pickWeek(monday) }
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textDisabled)
                        .frame(width: 84, alignment: .leading)
                    HStack(spacing: 6) {
                        ForEach(weeks[key] ?? [], id: \.self) { date in
                            daySquare(viewModel, date, size: 28)
                        }
                    }
                }
            }
        }
    }
}

private struct LifeWeekView: View {
    @ObservedObject var viewModel: LifeViewModel
    let cursor: Date
    let open: (AppDestination) -> Void

    var body: some View {
        let monday = LifeCalendar.startOfWeek(cursor)
        VStack(alignment: .leading, spacing: DS.Spacing.lg) {
            LifeStepper(title: LifeCalendar.isoWeekCode(monday)) { viewModel.step($0) }
            Button("Открыть неделю \(LifeCalendar.isoWeekCode(monday)) с ретро") {
                open(.week(LifeCalendar.isoWeekCode(monday)))
            }
            .buttonStyle(LimeButtonStyle(prominent: false))
            VStack(spacing: DS.Spacing.sm) {
                ForEach(0..<LifeCalendar.daysInWeek, id: \.self) { offset in
                    let date = LifeCalendar.addDays(monday, offset)
                    let day = viewModel.days[LifeCalendar.iso(date)]
                    LifeCard {
                        HStack(spacing: DS.Spacing.md) {
                            daySquare(viewModel, date, size: 32)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("\(LifeCalendar.weekdayShort[offset]) \(LifeCalendar.dayOfMonth(date))")
                                    .font(DS.Typography.caption)
                                    .foregroundStyle(DS.Palette.textDisabled)
                                Text((day?.title).flatMap { $0.isEmpty ? nil : $0 } ?? "—")
                                    .font(DS.Typography.body)
                                    .foregroundStyle(DS.Palette.textSecondary)
                                    .lineLimit(2)
                            }
                            Spacer()
                        }
                    }
                }
            }
        }
    }
}

private struct LifeDayView: View {
    @ObservedObject var viewModel: LifeViewModel
    let cursor: Date
    let open: (AppDestination) -> Void

    var body: some View {
        let iso = LifeCalendar.iso(cursor)
        let day = viewModel.days[iso]
        VStack(alignment: .leading, spacing: DS.Spacing.lg) {
            LifeStepper(title: iso) { viewModel.step($0) }
            LifeCard {
                VStack(alignment: .leading, spacing: DS.Spacing.sm) {
                    HStack {
                        daySquare(viewModel, cursor, size: 36)
                        Text(viewModel.status(of: cursor).label)
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.textSecondary)
                    }
                    Text(day.flatMap { $0.title.isEmpty ? nil : $0.title } ?? "Плана нет")
                        .font(DS.Typography.card)
                        .foregroundStyle(DS.Palette.textPrimary)
                    Text(summary(day))
                        .font(DS.Typography.body)
                        .foregroundStyle(DS.Palette.textSecondary)
                    Button("Открыть день \(iso)") { open(.day(iso)) }
                        .buttonStyle(LimeButtonStyle(prominent: false))
                }
            }
        }
    }

    private func summary(_ day: LifeDayDTO?) -> String {
        guard let day else { return "Записи об этом дне нет." }
        let verdict: String
        if let value = day.verdict {
            let origin = LifeCalendar.verdictOriginLabel(day.verdictOrigin)
            verdict = origin.isEmpty ? "Вердикт: \(value)." : "Вердикт: \(value) (\(origin))."
        } else {
            verdict = "День не закрыт."
        }
        return "Задачи \(day.done) из \(day.total). \(verdict)"
    }
}

/// A tappable square of one date; the tap opens the day view.
@MainActor
private func daySquare(_ viewModel: LifeViewModel, _ date: Date, size: CGFloat) -> some View {
    let iso = LifeCalendar.iso(date)
    let status = viewModel.status(of: date)
    return Button { viewModel.pickDay(date) } label: {
        LifeSquare(status: status, size: size, isToday: iso == viewModel.todayISO)
    }
    .buttonStyle(.plain)
    .accessibilityLabel("\(iso) — \(status.label)")
}
