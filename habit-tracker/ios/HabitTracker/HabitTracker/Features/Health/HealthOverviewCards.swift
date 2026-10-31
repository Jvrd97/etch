// [review:need-review] PHASE-03/305
// summary: the five cards of the Health tab on `Card` — «Состояние сегодня» (server index in a two-arc ring), steps and energy tiles with a mini sparkline, «Сон по ночам», «Отклонение от вашей нормы», «Тренировки» for 30 days; every card has its own empty line, colours never carry a meaning alone, layouts fall back to one column at accessibility sizes
import SwiftUI

private extension View {
    func cardTitle() -> some View {
        font(.headline).foregroundStyle(DS.Palette.textPrimary)
    }

    func secondaryNote() -> some View {
        font(.footnote).foregroundStyle(DS.Palette.textSecondary)
    }
}

private struct LegendDot: View {
    let color: Color
    let text: String

    var body: some View {
        HStack(spacing: DS.Spacing.xs) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(text).font(.caption).foregroundStyle(DS.Palette.textSecondary)
        }
        .accessibilityElement(children: .combine)
    }
}

// MARK: - Состояние сегодня

struct HealthStateCard: View {
    let score: HealthScoreDTO
    let metrics: [HealthMetricSeriesDTO]
    @Environment(\.dynamicTypeSize) private var typeSize

    var body: some View {
        let share = HealthOverview.normShare(metrics)
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                Text(HealthOverview.stateTitle).cardTitle()
                let layout = typeSize.isAccessibilitySize
                    ? AnyLayout(VStackLayout(alignment: .leading, spacing: DS.Spacing.lg))
                    : AnyLayout(HStackLayout(spacing: DS.Spacing.xl))
                layout {
                    HealthStateRing(
                        index: score.value.map { Double($0) / Double(HealthOverview.indexScale) },
                        norm: share.fraction,
                        centerText: score.value.map(String.init) ?? "—"
                    )
                    VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                        if let value = score.value {
                            if let word = HealthOverview.stateWord(score.label) {
                                Text(word)
                                    .font(.system(.title2, design: .rounded).weight(.bold))
                                    .foregroundStyle(DS.Palette.textPrimary)
                            }
                            Text(HealthOverview.indexText(value))
                                .font(.headline).monospacedDigit()
                                .foregroundStyle(HealthPalette.lime)
                            Text(HealthOverview.basisText(score.basisDays)).secondaryNote()
                        } else {
                            Text(HealthOverview.stateTooLittleText).secondaryNote()
                        }
                        VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                            LegendDot(color: HealthPalette.lime, text: "Индекс состояния")
                            if share.judged > 0 {
                                LegendDot(color: HealthPalette.sky, text: "В норме: \(share.inNorm) из \(share.judged) метрик")
                            }
                        }
                        .padding(.top, DS.Spacing.xs)
                    }
                }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Self.spoken(score, share: share))
    }

    static func spoken(_ score: HealthScoreDTO, share: HealthOverview.NormShare) -> String {
        guard let value = score.value else { return "\(HealthOverview.stateTitle). \(HealthOverview.stateTooLittleText)" }
        let word = HealthOverview.stateWord(score.label).map { "\($0). " } ?? ""
        let norm = share.judged > 0 ? ". В норме \(share.inNorm) из \(share.judged) метрик" : ""
        return "\(HealthOverview.stateTitle). \(word)\(HealthOverview.indexText(value)), \(HealthOverview.basisText(score.basisDays))\(norm)"
    }
}

// MARK: - Плитки

struct HealthTilesRow: View {
    let metrics: [HealthMetricSeriesDTO]
    let today: String
    @Environment(\.dynamicTypeSize) private var typeSize

    private struct Spec {
        let identifier: String
        let fallbackTitle: String
        let color: Color
    }

    private static let specs = [
        Spec(identifier: HealthOverview.stepCount, fallbackTitle: "Шаги", color: HealthPalette.lime),
        Spec(identifier: HealthOverview.activeEnergy, fallbackTitle: "Активная энергия", color: HealthPalette.sky),
    ]

    /// A tile shows when the catalogue holds the metric; one the phone never filled says so in its own tile.
    var body: some View {
        let tiles = Self.specs.compactMap { spec -> (Spec, HealthMetricSeriesDTO)? in
            metrics.first { $0.identifier == spec.identifier }.map { (spec, $0) }
        }
        if !tiles.isEmpty {
            let layout = typeSize.isAccessibilitySize
                ? AnyLayout(VStackLayout(spacing: DS.Spacing.md))
                : AnyLayout(HStackLayout(alignment: .top, spacing: DS.Spacing.md))
            layout {
                ForEach(tiles, id: \.0.identifier) { spec, metric in
                    HealthTile(
                        tile: HealthOverview.tile(metric, today: today, higherIsBetter: HealthOverview.isHigherBetter(spec.identifier) ?? true),
                        fallbackTitle: metric.displayName.isEmpty ? spec.fallbackTitle : metric.displayName,
                        color: spec.color
                    )
                }
            }
            .fixedSize(horizontal: false, vertical: true)
        }
    }
}

private struct HealthTile: View {
    let tile: HealthOverview.Tile?
    let fallbackTitle: String
    let color: Color

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.sm) {
                Text(tile?.title ?? fallbackTitle).secondaryNote()
                if let tile {
                    Text(tile.value)
                        .font(.system(.title3, design: .rounded).weight(.bold))
                        .monospacedDigit()
                        .foregroundStyle(DS.Palette.textPrimary)
                        .minimumScaleFactor(0.7)
                    if let dateNote = tile.dateNote { Text(dateNote).font(.caption).foregroundStyle(DS.Palette.textSecondary) }
                    HealthMiniSparkline(points: tile.points, color: color)
                    if let note = tile.note {
                        Text(note).font(.caption).foregroundStyle(HealthPalette.color(tile.tone))
                    }
                } else {
                    Text(HealthMetricRowText.noDataText).font(.body).foregroundStyle(DS.Palette.textSecondary)
                }
            }
            // Two tiles side by side stand at one height.
            .frame(maxHeight: .infinity, alignment: .topLeading)
        }
        .accessibilityElement(children: .combine)
    }
}

// MARK: - Сон по ночам

struct HealthSleepChartCard: View {
    let nights: [HealthSleepNightDTO]
    let today: String
    /// Leads to the screen with every night; `nil` hides the link.
    var onAllNights: (() -> Void)?

    var body: some View {
        let bars = HealthOverview.sleepBars(nights, today: today)
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                HStack {
                    Text(HealthOverview.sleepTitle).cardTitle()
                    Spacer(minLength: DS.Spacing.sm)
                    if let onAllNights, nights.isEmpty == false {
                        Button("Все ночи", action: onAllNights)
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(HealthPalette.lime)
                            .buttonStyle(.borderless)
                    }
                }
                if let last = nights.last {
                    HealthSleepColumns(bars: bars)
                    FlowLegend {
                        LegendDot(color: HealthPalette.sky, text: "Глубокий + REM")
                        LegendDot(color: HealthPalette.muted, text: "Лёгкий")
                        LegendDot(color: HealthPalette.lime, text: "Лучшая ночь")
                    }
                    Text("Последняя ночь: \(HealthMetricsFormat.sleepDuration(last.asleepMin)), отбой \(HealthMetricsFormat.wallClock(last.bedtime)), подъём \(HealthMetricsFormat.wallClock(last.wakeTime))")
                        .secondaryNote()
                } else {
                    Text(HealthMetricsFormat.sleepEmptyText).secondaryNote()
                }
            }
        }
    }
}

/// Legend items that wrap to the next line instead of squeezing when the text grows.
private struct FlowLegend<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: DS.Spacing.lg) { content }
            VStack(alignment: .leading, spacing: DS.Spacing.xs) { content }
        }
    }
}

// MARK: - Отклонение от нормы

struct HealthDeviationCard: View {
    let metrics: [HealthMetricSeriesDTO]

    private static func toneWord(_ tone: HealthTone) -> String {
        switch tone {
        case .better: return "лучше нормы"
        case .worse: return "хуже нормы"
        case .same: return "как обычно"
        }
    }

    var body: some View {
        let bars = HealthOverview.deviationBars(metrics)
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                Text("Отклонение от вашей нормы").cardTitle()
                if bars.isEmpty {
                    Text("Личная норма считается, когда накопилось хотя бы 7 дней данных.").secondaryNote()
                } else {
                    ForEach(bars) { bar in
                        VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                            Text(bar.title).font(.subheadline.weight(.medium)).foregroundStyle(DS.Palette.textPrimary)
                            Text("\(bar.text) · \(Self.toneWord(bar.tone))")
                                .font(.caption).foregroundStyle(HealthPalette.color(bar.tone))
                            HealthDeviationBar(share: bar.share, tone: bar.tone)
                        }
                        .accessibilityElement(children: .combine)
                    }
                    FlowLegend {
                        LegendDot(color: HealthPalette.lime, text: "Лучше нормы")
                        LegendDot(color: HealthPalette.amber, text: "Хуже нормы")
                    }
                    Text("Полоса — до \(Int(HealthOverview.deviationAxis * 100)) % от вашей обычной величины в каждую сторону.").secondaryNote()
                }
            }
        }
    }
}

// MARK: - Тренировки

struct HealthWorkoutsCard: View {
    let workouts: [HealthWorkoutRecordDTO]

    var body: some View {
        let groups = HealthOverview.workoutGroups(workouts)
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                Text(HealthOverview.workoutsTitle).cardTitle()
                if let headline = HealthOverview.workoutsHeadline(workouts) {
                    Text(headline)
                        .font(.system(.title3, design: .rounded).weight(.bold))
                        .foregroundStyle(HealthPalette.lime)
                    ForEach(groups) { group in
                        VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                            Text(group.label).font(.subheadline.weight(.semibold)).foregroundStyle(DS.Palette.textPrimary)
                            Text(group.details.joined(separator: " · ")).secondaryNote()
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .accessibilityElement(children: .combine)
                    }
                } else {
                    Text(HealthMetricsFormat.workoutsEmptyText).secondaryNote()
                }
            }
        }
    }
}
