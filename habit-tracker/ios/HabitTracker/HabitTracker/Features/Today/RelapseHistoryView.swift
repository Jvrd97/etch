// [review:need-review] PHASE-01/210
// summary: relapse history of an avoid category (pushed from the streak card) — current and best streak, last relapse, relapse days in the last 7 and 30 days from the server's today, average gap, trend against the month before, a Swift Charts history for the chosen period, the weekday split and the latest relapse days
import Charts
import SwiftUI

struct RelapseHistoryView: View {
    let category: CategoryDTO
    @StateObject private var viewModel: RelapseHistoryViewModel

    init(category: CategoryDTO, viewModel: @autoclosure @escaping () -> RelapseHistoryViewModel) {
        self.category = category
        _viewModel = StateObject(wrappedValue: viewModel())
    }

    var body: some View {
        content
            .navigationTitle(category.name)
            .navigationBarTitleDisplayMode(.inline)
            .dsScreenBackground()
            .task { await viewModel.load() }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .idle, .loading:
            NeonLoader(label: "Loading")
        case .failure(let message):
            DSErrorState(message: message) {
                Task { await viewModel.load() }
            }
        case .loaded:
            if let history = viewModel.history, let summary = viewModel.summary {
                ScrollView {
                    VStack(alignment: .leading, spacing: DS.Spacing.lg) {
                        statsCard(history: history, summary: summary)
                        trendLine(summary.trend)
                        chartCard
                        weekdayCard(summary: summary)
                        recentCard
                    }
                    .padding(DS.Spacing.lg)
                }
                .refreshable { await viewModel.load() }
            }
        }
    }

    // MARK: Numbers

    private func statsCard(history: RelapseHistoryDTO, summary: RelapseSummary) -> some View {
        let stats: [(String, String)] = [
            ("Текущая серия", RelapseAnalysis.formatDayCount(history.currentStreak)),
            ("Лучшая серия", RelapseAnalysis.formatDayCount(history.bestStreak)),
            (
                "Последний срыв",
                history.lastRelapseDate.map(RelapseAnalysis.formatDay) ?? "не было"
            ),
            ("Срывов за \(RelapseAnalysis.weekDays) дней", String(summary.lastWeek)),
            ("Срывов за \(RelapseAnalysis.monthDays) дней", String(summary.lastMonth)),
            (
                "Средний промежуток",
                summary.averageGapDays.map(RelapseAnalysis.formatGap) ?? "—"
            ),
        ]
        return Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                LazyVGrid(
                    columns: [GridItem(.flexible()), GridItem(.flexible())],
                    alignment: .leading, spacing: DS.Spacing.lg
                ) {
                    ForEach(stats, id: \.0) { stat in
                        VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                            Text(stat.0)
                                .font(DS.Typography.caption)
                                .foregroundStyle(DS.Palette.textSecondary)
                            Text(stat.1)
                                .font(DS.Typography.section)
                                .foregroundStyle(DS.Palette.textPrimary)
                                .monospacedDigit()
                        }
                    }
                }
                Text("Срыв считается по дням: несколько за один день — один день со срывом.")
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
            }
        }
    }

    @ViewBuilder
    private func trendLine(_ trend: RelapseTrend) -> some View {
        switch trend {
        case .notEnoughData:
            Text("Тренд появится, когда история охватит \(RelapseAnalysis.monthDays * 2) дней.")
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.textSecondary)
        case .fewer(let current, let previous):
            Label("Реже, чем месяц назад: \(current) против \(previous)", systemImage: "arrow.down.right")
                .foregroundStyle(DS.Palette.success)
        case .more(let current, let previous):
            Label("Чаще, чем месяц назад: \(current) против \(previous)", systemImage: "arrow.up.right")
                .foregroundStyle(DS.Palette.danger)
        case .same(let current, _):
            Label("Так же, как месяц назад: \(current)", systemImage: "equal")
                .foregroundStyle(DS.Palette.textSecondary)
        }
    }

    // MARK: Chart

    private var chartCard: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                Picker("Период", selection: $viewModel.period) {
                    ForEach(RelapsePeriod.allCases) { period in
                        Text(period.title).tag(period)
                    }
                }
                .pickerStyle(.segmented)
                if let timeline = viewModel.timeline {
                    Chart(timeline.buckets) { bucket in
                        BarMark(
                            x: .value("Дата", Self.date(of: bucket.start), unit: unit(of: timeline)),
                            y: .value("Дней со срывом", bucket.relapseDays)
                        )
                        .foregroundStyle(DS.Palette.danger)
                    }
                    .chartYAxis {
                        AxisMarks(values: .automatic(desiredCount: 3)) { _ in
                            AxisGridLine()
                            AxisValueLabel()
                        }
                    }
                    .frame(height: 160)
                    .accessibilityLabel(chartSummary(timeline))
                }
            }
        }
    }

    private func unit(of timeline: RelapseTimeline) -> Calendar.Component {
        timeline.granularity == .day ? .day : .weekOfYear
    }

    private func chartSummary(_ timeline: RelapseTimeline) -> String {
        let total = timeline.buckets.map(\.relapseDays).reduce(0, +)
        return "График срывов, \(viewModel.period.title): \(total) дней со срывом"
    }

    /// A bucket's first day at UTC noon: the chart groups by calendar unit and noon keeps the day
    /// away from a midnight edge in any zone.
    private static func date(of iso: String) -> Date {
        let seconds = RelapseAnalysis.dayNumber(of: iso) * 86_400 + 43_200
        return Date(timeIntervalSince1970: TimeInterval(seconds))
    }

    // MARK: Weekdays and latest days

    private func weekdayCard(summary: RelapseSummary) -> some View {
        let busiest = max(1, summary.weekdays.max() ?? 1)
        return Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                Text("По дням недели")
                    .font(DS.Typography.card)
                    .foregroundStyle(DS.Palette.textPrimary)
                ForEach(Array(RelapseAnalysis.weekdayLabels.enumerated()), id: \.offset) { index, label in
                    let count = summary.weekdays[index]
                    HStack(spacing: DS.Spacing.md) {
                        Text(label)
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.textSecondary)
                            .frame(width: 28, alignment: .leading)
                        GeometryReader { proxy in
                            Capsule()
                                .fill(DS.Palette.danger)
                                .frame(width: proxy.size.width * CGFloat(count) / CGFloat(busiest))
                        }
                        .frame(height: 8)
                        Text("\(count)")
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.textPrimary)
                            .monospacedDigit()
                            .frame(width: 28, alignment: .trailing)
                    }
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel("\(label): \(count)")
                }
            }
        }
    }

    private var recentCard: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.sm) {
                Text("Последние срывы")
                    .font(DS.Typography.card)
                    .foregroundStyle(DS.Palette.textPrimary)
                if viewModel.recentDays.isEmpty {
                    Text("Срывов не было")
                        .foregroundStyle(DS.Palette.textSecondary)
                } else {
                    ForEach(viewModel.recentDays, id: \.self) { day in
                        Text("\(RelapseAnalysis.formatDay(day)), \(RelapseAnalysis.formatWeekday(day))")
                            .font(DS.Typography.body)
                            .foregroundStyle(DS.Palette.textPrimary)
                    }
                }
            }
        }
    }
}
