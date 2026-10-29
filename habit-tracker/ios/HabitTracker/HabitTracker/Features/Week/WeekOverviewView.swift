// [review:need-review] PHASE-03/222
// summary: animated week overview opened from the Week screen — swipeable «итоги недели» slides as the entry and a feed of animated charts (plan and time by day, role shares) as the details; numbers count up and bars grow once, and with Reduce Motion the same figures stand still; states loading, failed, empty, unfinished week
import SwiftUI

private enum OverviewLayout {
    static let countDuration = 0.9
    static let barDuration = 0.8
    static let barStagger = 0.06
    static let barAreaHeight: CGFloat = 120
    static let barWidth: CGFloat = 26
    static let barRadius: CGFloat = 6
    static let slideFigureSize: CGFloat = 64
    static let slideMinHeight: CGFloat = 320
    static let roleBarHeight: CGFloat = 10
    static let trackOpacity = 0.15
    static let fullShare = 100.0
}

/// A number that counts from zero to its value; with `progress == 1` it is just the value.
private struct CountingText: View, Animatable {
    var progress: Double
    let target: Int
    let format: WeekOverviewFormat

    var animatableData: Double {
        get { progress }
        set { progress = newValue }
    }

    var body: some View {
        Text(format.text(Int((Double(target) * progress).rounded())))
    }
}

/// Drives the one-time motion; with Reduce Motion it starts finished and never animates.
private struct MotionProgress: ViewModifier {
    let reduceMotion: Bool
    let duration: Double
    let delay: Double
    @Binding var progress: Double

    func body(content: Content) -> some View {
        content.onAppear {
            guard !reduceMotion else { progress = 1; return }
            withAnimation(.easeOut(duration: duration).delay(delay)) { progress = 1 }
        }
    }
}

// MARK: Slides

struct WeekOverviewSlideView: View {
    let slide: WeekOverviewSlide
    let reduceMotion: Bool
    @State private var progress: Double

    init(slide: WeekOverviewSlide, reduceMotion: Bool) {
        self.slide = slide
        self.reduceMotion = reduceMotion
        _progress = State(initialValue: reduceMotion ? 1 : 0)
    }

    var body: some View {
        VStack(spacing: DS.Spacing.md) {
            Text(slide.title)
                .font(DS.Typography.section)
                .foregroundStyle(DS.Palette.textSecondary)
            if let figure = slide.figure {
                CountingText(progress: progress, target: figure, format: slide.format)
                    .font(.system(size: OverviewLayout.slideFigureSize, weight: .bold, design: .rounded))
                    .foregroundStyle(DS.Palette.lime)
                    .monospacedDigit()
                    .minimumScaleFactor(0.5)
                    .lineLimit(1)
            }
            Text(slide.caption)
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.textPrimary)
                .multilineTextAlignment(.center)
            if let change = slide.change {
                Text(change)
                    .font(DS.Typography.caption)
                    .foregroundStyle(color(slide.trend))
            }
        }
        .frame(maxWidth: .infinity, minHeight: OverviewLayout.slideMinHeight)
        .padding(DS.Spacing.lg)
        .modifier(MotionProgress(reduceMotion: reduceMotion, duration: OverviewLayout.countDuration, delay: 0, progress: $progress))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityText)
    }

    private var accessibilityText: String {
        [slide.title, slide.figureText, slide.caption.replacingOccurrences(of: "\n", with: ". "), slide.change]
            .compactMap { $0 }.joined(separator: ". ")
    }
}

private func color(_ trend: WeekFormat.Trend) -> Color {
    switch trend {
    case .up: return DS.Palette.lime
    case .down: return DS.Palette.danger
    case .flat: return DS.Palette.textSecondary
    }
}

struct WeekOverviewSlidesView: View {
    let slides: [WeekOverviewSlide]
    let reduceMotion: Bool

    var body: some View {
        TabView {
            ForEach(slides) { slide in
                Card { WeekOverviewSlideView(slide: slide, reduceMotion: reduceMotion) }
                    .padding(.horizontal, DS.Spacing.lg)
                    .padding(.bottom, DS.Spacing.xl)
            }
        }
        .tabViewStyle(.page(indexDisplayMode: .always))
        .frame(minHeight: OverviewLayout.slideMinHeight + DS.Spacing.xl * 3)
    }
}

// MARK: Feed

private struct GrowingBar: View {
    let fraction: Double
    let label: String
    let value: String
    let index: Int
    let reduceMotion: Bool
    @State private var progress: Double

    init(fraction: Double, label: String, value: String, index: Int, reduceMotion: Bool) {
        self.fraction = fraction
        self.label = label
        self.value = value
        self.index = index
        self.reduceMotion = reduceMotion
        _progress = State(initialValue: reduceMotion ? 1 : 0)
    }

    var body: some View {
        VStack(spacing: DS.Spacing.xs) {
            Text(value).font(DS.Typography.caption).foregroundStyle(DS.Palette.textSecondary).monospacedDigit()
                .minimumScaleFactor(0.6).lineLimit(1)
            ZStack(alignment: .bottom) {
                RoundedRectangle(cornerRadius: OverviewLayout.barRadius)
                    .fill(DS.Palette.lime.opacity(OverviewLayout.trackOpacity))
                    .frame(width: OverviewLayout.barWidth, height: OverviewLayout.barAreaHeight)
                RoundedRectangle(cornerRadius: OverviewLayout.barRadius)
                    .fill(DS.Palette.lime)
                    .frame(width: OverviewLayout.barWidth, height: OverviewLayout.barAreaHeight * fraction * progress)
            }
            Text(label).font(DS.Typography.caption).foregroundStyle(DS.Palette.textPrimary)
        }
        .frame(maxWidth: .infinity)
        .modifier(MotionProgress(
            reduceMotion: reduceMotion, duration: OverviewLayout.barDuration,
            delay: Double(index) * OverviewLayout.barStagger, progress: $progress
        ))
    }
}

private struct DayBarsCard: View {
    let title: String
    let days: [WeekDayStatDTO]
    let value: (WeekDayStatDTO) -> Double?
    let text: (Double) -> String
    let reduceMotion: Bool

    var body: some View {
        let peak = max(days.compactMap(value).max() ?? 0, 1)
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                Text(title).font(DS.Typography.section).foregroundStyle(DS.Palette.textPrimary)
                    .accessibilityAddTraits(.isHeader)
                HStack(alignment: .bottom, spacing: DS.Spacing.xs) {
                    ForEach(Array(days.enumerated()), id: \.element.id) { index, day in
                        let amount = value(day)
                        GrowingBar(
                            fraction: (amount ?? 0) / peak, label: WeekFormat.weekdayShort(day.weekday),
                            value: amount.map(text) ?? "—", index: index, reduceMotion: reduceMotion
                        )
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel(
                            "\(WeekFormat.weekdayShort(day.weekday)): \(amount.map(text) ?? WeekFormat.noData)"
                        )
                    }
                }
            }
        }
    }
}

private struct RoleShareRow: View {
    let role: WeekRoleSliceDTO
    let index: Int
    let reduceMotion: Bool
    @State private var progress: Double

    init(role: WeekRoleSliceDTO, index: Int, reduceMotion: Bool) {
        self.role = role
        self.index = index
        self.reduceMotion = reduceMotion
        _progress = State(initialValue: reduceMotion ? 1 : 0)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.xs) {
            HStack {
                Text(role.title).font(DS.Typography.body).foregroundStyle(DS.Palette.textPrimary)
                Spacer()
                Text("\(role.sharePct)% · \(WeekFormat.minutes(role.minutes))")
                    .font(DS.Typography.caption).foregroundStyle(DS.Palette.textSecondary).monospacedDigit()
            }
            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule().fill(DS.Palette.lime.opacity(OverviewLayout.trackOpacity))
                    Capsule().fill(DS.Palette.lime)
                        .frame(width: proxy.size.width * Double(role.sharePct) / OverviewLayout.fullShare * progress)
                }
            }
            .frame(height: OverviewLayout.roleBarHeight)
        }
        .accessibilityElement(children: .combine)
        .modifier(MotionProgress(
            reduceMotion: reduceMotion, duration: OverviewLayout.barDuration,
            delay: Double(index) * OverviewLayout.barStagger, progress: $progress
        ))
    }
}

struct WeekOverviewFeedView: View {
    let review: WeekReviewDTO
    let reduceMotion: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.lg) {
            DayBarsCard(
                title: "План по дням", days: review.days,
                value: { $0.planPct.map(Double.init) }, text: { "\(Int($0))%" }, reduceMotion: reduceMotion
            )
            DayBarsCard(
                title: "Время по дням", days: review.days,
                value: { $0.roleMinutes > 0 ? Double($0.roleMinutes) : nil },
                text: { WeekFormat.minutes(Int($0)) }, reduceMotion: reduceMotion
            )
            if !review.roles.isEmpty {
                Card {
                    VStack(alignment: .leading, spacing: DS.Spacing.md) {
                        Text("Роли").font(DS.Typography.section).foregroundStyle(DS.Palette.textPrimary)
                            .accessibilityAddTraits(.isHeader)
                        ForEach(Array(review.roles.enumerated()), id: \.element.id) { index, role in
                            RoleShareRow(role: role, index: index, reduceMotion: reduceMotion)
                        }
                    }
                }
            }
        }
    }
}

// MARK: Screen

/// The sheet: slides first, the feed under them.
struct WeekOverviewView: View {
    @ObservedObject var viewModel: WeekViewModel
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            content
                .navigationTitle("Итоги недели")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { Button("Закрыть") { dismiss() } }
                .dsScreenBackground()
        }
    }

    private var state: WeekOverviewState {
        WeekOverview.state(loadState: viewModel.state, review: viewModel.review, note: viewModel.partialNote)
    }

    @ViewBuilder
    private var content: some View {
        switch state {
        case .loading:
            NeonLoader(label: "Загрузка")
        case .failed(let message):
            DSErrorState(message: message) { Task { await viewModel.load() } }
        case .empty:
            Text(WeekOverview.emptyText)
                .font(DS.Typography.body).foregroundStyle(DS.Palette.textSecondary)
                .padding(DS.Spacing.lg)
        case .ready(let slides, let note):
            ScrollView {
                VStack(alignment: .leading, spacing: DS.Spacing.lg) {
                    if let note {
                        Text(note).font(DS.Typography.body).foregroundStyle(DS.Palette.textPrimary)
                            .padding(.horizontal, DS.Spacing.lg)
                    }
                    WeekOverviewSlidesView(slides: slides, reduceMotion: systemReduceMotion)
                    if let review = viewModel.review {
                        Text("Подробности").font(DS.Typography.section).foregroundStyle(DS.Palette.textPrimary)
                            .padding(.horizontal, DS.Spacing.lg)
                            .accessibilityAddTraits(.isHeader)
                        WeekOverviewFeedView(review: review, reduceMotion: systemReduceMotion)
                            .padding(.horizontal, DS.Spacing.lg)
                    }
                }
                .padding(.vertical, DS.Spacing.lg)
            }
        }
    }
}
