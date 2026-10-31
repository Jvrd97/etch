// [review:need-review] PHASE-03/304
// summary: the lower cards of the dashboard — «Динамика тренировок» (bars by week scaled to the busiest, height capped; at accessibility text sizes the columns turn into rows with a horizontal bar, every week read aloud with count and minutes), the insight (the server's ready text, its moment, the way to the reports) and the «Питание · скоро» placeholder
import SwiftUI

// MARK: - Динамика тренировок

struct DashboardWorkoutsCard: View {
    let workouts: DashboardWorkoutsDTO
    @Environment(\.dynamicTypeSize) private var typeSize

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                DashboardCardHeader(title: DashboardFormat.workoutsTitle, aside: aside)
                if workouts.weeks.isEmpty {
                    DashboardEmptyLine(DashboardFormat.workoutsEmpty)
                } else if typeSize.isAccessibilitySize {
                    WeekRows(weeks: workouts.weeks)
                } else {
                    WeekColumns(weeks: workouts.weeks)
                }
            }
        }
    }

    /// «всего 3 · +1 к прошлому периоду»; empty when the window has nothing to compare.
    private var aside: String? {
        guard !workouts.weeks.isEmpty else { return nil }
        let parts = [
            workouts.total.map { "всего \($0)" },
            DashboardFormat.workoutChangeText(workouts.deltaVsPrevious),
        ].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private struct WeekColumns: View {
        let weeks: [DashboardWorkoutWeekDTO]
        /// The bars grow with the text, but a very large setting does not make a tower of them.
        @ScaledMetric(relativeTo: .body) private var barArea: CGFloat = 96
        private let maxBarArea: CGFloat = 140
        private let minBar: CGFloat = 3
        private let maxBarWidth: CGFloat = 40

        var body: some View {
            let fractions = DashboardFormat.workoutFractions(weeks)
            let area = min(barArea, maxBarArea)
            HStack(alignment: .bottom, spacing: DS.Spacing.md) {
                ForEach(Array(weeks.enumerated()), id: \.element.id) { index, week in
                    VStack(spacing: DS.Spacing.xs) {
                        Label("\(week.count)", systemImage: "dumbbell.fill")
                            .labelStyle(CountLabelStyle())
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(DS.Palette.textPrimary)
                        ZStack(alignment: .bottom) {
                            Color.clear
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(DashboardPalette.lime)
                                .frame(maxWidth: maxBarWidth)
                                .frame(height: max(minBar, area * fractions[index]))
                        }
                        .frame(height: area)
                        Text(HealthMetricsFormat.dayLabel(week.weekStart))
                            .font(.caption2)
                            .foregroundStyle(DS.Palette.textSecondary)
                            .lineLimit(1)
                            .minimumScaleFactor(0.7)
                        Text(HealthMetricsFormat.sleepDuration(Double(week.minutes)))
                            .font(.caption2)
                            .foregroundStyle(DS.Palette.textSecondary)
                            .lineLimit(2)
                            .multilineTextAlignment(.center)
                            .minimumScaleFactor(0.7)
                    }
                    .frame(maxWidth: .infinity)
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(DashboardFormat.workoutWeekLabel(week))
                }
            }
        }
    }

    private struct CountLabelStyle: LabelStyle {
        func makeBody(configuration: Configuration) -> some View {
            HStack(spacing: 4) {
                configuration.icon.foregroundStyle(DashboardPalette.lime).imageScale(.small)
                configuration.title
            }
        }
    }

    private struct WeekRows: View {
        let weeks: [DashboardWorkoutWeekDTO]
        private let barHeight: CGFloat = 10
        private let minBar: CGFloat = 4

        var body: some View {
            let fractions = DashboardFormat.workoutFractions(weeks)
            VStack(alignment: .leading, spacing: DS.Spacing.lg) {
                ForEach(Array(weeks.enumerated()), id: \.element.id) { index, week in
                    VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                        Text("С \(HealthMetricsFormat.dayLabel(week.weekStart))")
                            .font(.subheadline)
                            .foregroundStyle(DS.Palette.textSecondary)
                        Text("\(DashboardFormat.workoutCount(week.count)) · \(HealthMetricsFormat.sleepDuration(Double(week.minutes)))")
                            .font(.headline)
                            .foregroundStyle(DS.Palette.textPrimary)
                        GeometryReader { proxy in
                            RoundedRectangle(cornerRadius: barHeight / 2, style: .continuous)
                                .fill(DashboardPalette.lime)
                                .frame(width: max(minBar, proxy.size.width * fractions[index]), height: barHeight)
                        }
                        .frame(height: barHeight)
                    }
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(DashboardFormat.workoutWeekLabel(week))
                }
            }
        }
    }
}

// MARK: - Инсайт

struct DashboardInsightCard: View {
    let insight: DashboardInsightDTO?
    let period: DashboardPeriod
    let onOpenReports: () -> Void

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                Label {
                    Text(DashboardFormat.insightTitle(period))
                        .font(.headline)
                        .foregroundStyle(DS.Palette.textPrimary)
                } icon: {
                    Image(systemName: "sparkles").foregroundStyle(DashboardPalette.lime)
                }
                .accessibilityAddTraits(.isHeader)
                if let insight {
                    Text(insight.text)
                        .font(.body)
                        .foregroundStyle(DS.Palette.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                    if let madeAt = DashboardFormat.generatedAtText(insight.generatedAt) {
                        Text("Сформирован \(madeAt)")
                            .font(.footnote)
                            .foregroundStyle(DS.Palette.textSecondary)
                    }
                } else {
                    DashboardEmptyLine(DashboardFormat.insightEmpty)
                }
                Button(action: onOpenReports) {
                    Label(DashboardFormat.insightsLink, systemImage: "arrow.right")
                        .labelStyle(TrailingIconLabelStyle())
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(DashboardPalette.lime)
                        .frame(minHeight: DashboardMetrics.minTap, alignment: .leading)
                }
            }
        }
    }

    private struct TrailingIconLabelStyle: LabelStyle {
        func makeBody(configuration: Configuration) -> some View {
            HStack(spacing: DS.Spacing.xs) {
                configuration.title
                configuration.icon
            }
        }
    }
}

// MARK: - Питание · скоро

struct DashboardNutritionCard: View {
    @Environment(\.dynamicTypeSize) private var typeSize

    var body: some View {
        Card {
            let layout = typeSize.isAccessibilitySize
                ? AnyLayout(VStackLayout(alignment: .leading, spacing: DS.Spacing.md))
                : AnyLayout(HStackLayout(spacing: DS.Spacing.lg))
            layout {
                Image(systemName: "fork.knife")
                    .font(.title3)
                    .foregroundStyle(DS.Palette.textSecondary)
                    .frame(width: 44, height: 44)
                    .background(Color.white.opacity(0.06), in: RoundedRectangle(cornerRadius: DS.Radius.chip, style: .continuous))
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                    Text(DashboardFormat.nutritionTitle)
                        .font(.headline)
                        .foregroundStyle(DS.Palette.textSecondary)
                    Text(DashboardFormat.nutritionText)
                        .font(.subheadline)
                        .foregroundStyle(DS.Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .accessibilityElement(children: .combine)
    }
}
