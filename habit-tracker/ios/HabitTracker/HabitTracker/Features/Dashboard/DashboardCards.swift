// [review:need-review] PHASE-03/304
// summary: the four upper cards of the dashboard on `Card` — «Общий показатель» (three rings, one column at accessibility text sizes), «Серии» (five rows, the rest on request, dots and lengths), «Состояние здоровья» (distance from the personal norm with an arrow and the words «лучше нормы» / «хуже нормы»), «Лучшее за …» (the day and the «Рекорд» mark); each has its own empty line
import SwiftUI

// MARK: - Общий показатель

struct DashboardRingsCard: View {
    let scores: DashboardScoresDTO
    @Environment(\.dynamicTypeSize) private var typeSize

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.lg) {
                DashboardCardHeader(title: DashboardFormat.ringsTitle)
                let layout = typeSize.isAccessibilitySize
                    ? AnyLayout(VStackLayout(alignment: .leading, spacing: DS.Spacing.xl))
                    : AnyLayout(HStackLayout(alignment: .top, spacing: DS.Spacing.sm))
                layout {
                    ForEach(DashboardFormat.rings(scores)) { ring in
                        RingColumn(ring: ring)
                    }
                }
            }
        }
    }

    private struct RingColumn: View {
        let ring: DashboardRing

        var body: some View {
            VStack(spacing: DS.Spacing.sm) {
                DashboardRingShape(fraction: ring.fraction, centre: ring.centre, color: DashboardPalette.color(ring.kind))
                Text(ring.title)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(DS.Palette.textPrimary)
                Text(ring.caption)
                    .font(.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(ring.spoken)
        }
    }
}

// MARK: - Серии

struct DashboardStreaksCard: View {
    let streaks: [DashboardStreakDTO]
    @State private var expanded = false

    /// The owner's mock-up draws five rows.
    static let collapsedCount = 5

    var body: some View {
        let shown = expanded ? streaks : Array(streaks.prefix(Self.collapsedCount))
        let hidden = streaks.count - shown.count
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                DashboardCardHeader(title: DashboardFormat.streaksTitle)
                if streaks.isEmpty {
                    DashboardEmptyLine(DashboardFormat.streaksEmpty)
                } else {
                    ForEach(Array(shown.enumerated()), id: \.element.id) { index, streak in
                        if index > 0 { Divider().overlay(DS.Palette.cardStroke) }
                        StreakRow(streak: streak)
                    }
                    if streaks.count > Self.collapsedCount {
                        Button {
                            expanded.toggle()
                        } label: {
                            Text(expanded ? "Свернуть" : "Показать все (ещё \(hidden))")
                                .font(.subheadline.weight(.medium))
                                .foregroundStyle(DashboardPalette.lime)
                                .frame(minHeight: DashboardMetrics.minTap, alignment: .leading)
                        }
                        .accessibilityHint(expanded ? "Оставить пять серий" : "Показать остальные серии")
                    }
                }
            }
        }
    }

    private struct StreakRow: View {
        let streak: DashboardStreakDTO
        @Environment(\.dynamicTypeSize) private var typeSize

        var body: some View {
            VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                let layout = typeSize.isAccessibilitySize
                    ? AnyLayout(VStackLayout(alignment: .leading, spacing: DS.Spacing.xs))
                    : AnyLayout(HStackLayout(alignment: .firstTextBaseline, spacing: DS.Spacing.md))
                layout {
                    HStack(spacing: DS.Spacing.sm) {
                        Text(streak.name)
                            .font(.body.weight(.medium))
                            .foregroundStyle(DS.Palette.textPrimary)
                        if streak.isAvoid {
                            Text(DashboardFormat.avoidBadge)
                                .font(.caption2)
                                .foregroundStyle(DS.Palette.textSecondary)
                                .padding(.horizontal, DS.Spacing.sm)
                                .padding(.vertical, 2)
                                .background(Color.white.opacity(0.08), in: Capsule())
                        }
                    }
                    if !typeSize.isAccessibilitySize { Spacer(minLength: DS.Spacing.sm) }
                    Label {
                        Text(DashboardFormat.days(streak.current))
                    } icon: {
                        Image(systemName: "flame.fill").foregroundStyle(DashboardPalette.lime)
                    }
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(DS.Palette.textPrimary)
                }
                Text(DashboardFormat.bestStreakText(streak.best))
                    .font(.footnote)
                    .foregroundStyle(DS.Palette.textSecondary)
                DashboardDayDots(days: streak.days)
                    .padding(.top, DS.Spacing.xs)
            }
            .padding(.vertical, DS.Spacing.xs)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(
                "\(streak.name). Серия \(DashboardFormat.days(streak.current)), \(DashboardFormat.bestStreakText(streak.best)). \(DashboardFormat.dotsLabel(streak))"
            )
        }
    }
}

// MARK: - Состояние здоровья

struct DashboardHealthCard: View {
    let metrics: [DashboardHealthMetricDTO]

    /// The server lists the key metrics; a longer list is cut rather than stretching the card.
    static let maxMetrics = 5

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                DashboardCardHeader(title: DashboardFormat.healthTitle, aside: DashboardFormat.healthAside)
                if metrics.isEmpty {
                    DashboardEmptyLine(DashboardFormat.healthEmpty)
                } else {
                    ForEach(Array(metrics.prefix(Self.maxMetrics).enumerated()), id: \.element.id) { index, metric in
                        if index > 0 { Divider().overlay(DS.Palette.cardStroke) }
                        MetricRow(metric: metric)
                    }
                }
            }
        }
    }

    private struct MetricRow: View {
        let metric: DashboardHealthMetricDTO
        @Environment(\.dynamicTypeSize) private var typeSize

        private var tone: DashboardTone {
            DashboardFormat.tone(delta: metric.baselineDelta, higherIsBetter: metric.higherIsBetter)
        }

        private var arrow: String {
            guard let delta = metric.baselineDelta, delta != 0 else { return "minus" }
            return delta > 0 ? "arrow.up.right" : "arrow.down.right"
        }

        var body: some View {
            let layout = typeSize.isAccessibilitySize
                ? AnyLayout(VStackLayout(alignment: .leading, spacing: DS.Spacing.sm))
                : AnyLayout(HStackLayout(alignment: .center, spacing: DS.Spacing.md))
            let value = DashboardFormat.value(identifier: metric.identifier, value: metric.value, unit: metric.unit)
            let delta = DashboardFormat.deltaText(metric)
            let word = DashboardFormat.toneWord(tone)
            layout {
                VStack(alignment: .leading, spacing: 2) {
                    Text(metric.label)
                        .font(.footnote)
                        .foregroundStyle(DS.Palette.textSecondary)
                    Text(value)
                        .font(.title3.weight(.bold))
                        .foregroundStyle(DS.Palette.textPrimary)
                }
                if !typeSize.isAccessibilitySize { Spacer(minLength: DS.Spacing.sm) }
                VStack(alignment: typeSize.isAccessibilitySize ? .leading : .trailing, spacing: 2) {
                    Label(delta, systemImage: arrow)
                        .font(.footnote)
                        .foregroundStyle(DashboardPalette.color(tone))
                    if let word {
                        Text(word)
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(DashboardPalette.color(tone))
                    }
                }
                .multilineTextAlignment(typeSize.isAccessibilitySize ? .leading : .trailing)
            }
            .padding(.vertical, DS.Spacing.xs)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("\(metric.label): \(value). \(delta)\(word.map { ", \($0)" } ?? "")")
        }
    }
}

// MARK: - Лучшее

struct DashboardBestsCard: View {
    let bests: [DashboardBestDTO]
    let period: DashboardPeriod
    /// The server's day, for «сегодня» and «вчера».
    let today: String

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                DashboardCardHeader(title: DashboardFormat.bestsTitle(period))
                if bests.isEmpty {
                    DashboardEmptyLine(DashboardFormat.bestsEmpty)
                } else {
                    ForEach(Array(bests.enumerated()), id: \.element.id) { index, best in
                        if index > 0 { Divider().overlay(DS.Palette.cardStroke) }
                        BestRow(best: best, today: today)
                    }
                }
            }
        }
    }

    private struct BestRow: View {
        let best: DashboardBestDTO
        let today: String
        @Environment(\.dynamicTypeSize) private var typeSize

        var body: some View {
            let layout = typeSize.isAccessibilitySize
                ? AnyLayout(VStackLayout(alignment: .leading, spacing: DS.Spacing.sm))
                : AnyLayout(HStackLayout(alignment: .center, spacing: DS.Spacing.md))
            let value = DashboardFormat.value(identifier: best.identifier, value: best.value, unit: best.unit)
            let day = DashboardFormat.bestDayText(best.date, today: today)
            layout {
                VStack(alignment: .leading, spacing: 2) {
                    Text(best.label)
                        .font(.footnote)
                        .foregroundStyle(DS.Palette.textSecondary)
                    Text(value)
                        .font(.title3.weight(.bold))
                        .foregroundStyle(DS.Palette.textPrimary)
                }
                if !typeSize.isAccessibilitySize { Spacer(minLength: DS.Spacing.sm) }
                VStack(alignment: typeSize.isAccessibilitySize ? .leading : .trailing, spacing: DS.Spacing.xs) {
                    Text(day)
                        .font(.footnote)
                        .foregroundStyle(DS.Palette.textSecondary)
                    if best.isRecord {
                        Label(DashboardFormat.recordWord, systemImage: "trophy.fill")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(DashboardPalette.lime)
                            .padding(.horizontal, DS.Spacing.sm)
                            .padding(.vertical, 2)
                            .background(DashboardPalette.lime.opacity(0.12), in: Capsule())
                    }
                }
            }
            .padding(.vertical, DS.Spacing.xs)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("\(best.label): \(value), \(day)\(best.isRecord ? ". \(DashboardFormat.recordWord)" : "")")
        }
    }
}
