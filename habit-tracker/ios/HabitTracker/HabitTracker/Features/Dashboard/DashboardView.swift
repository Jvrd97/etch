// [review:need-review] PHASE-03/304
// summary: Dashboard screen by the accepted mock-up — the Неделя/Месяц switch, the window's dates, the cached-answer note, then the three rings, streaks, health state, bests, workout dynamics, insight and the nutrition placeholder; loading, a Russian error with «Повторить», pull to refresh in place
import SwiftUI

struct DashboardView: View {
    @StateObject private var viewModel: DashboardViewModel

    /// The insight card leads to the reports under More.
    private let onNavigate: (AppDestination) -> Void

    init(viewModel: DashboardViewModel, onNavigate: @escaping (AppDestination) -> Void) {
        _viewModel = StateObject(wrappedValue: viewModel)
        self.onNavigate = onNavigate
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DS.Spacing.lg) {
                periodSwitch
                content
            }
            .padding(DS.Spacing.lg)
        }
        .refreshable { await viewModel.refresh() }
        .navigationTitle("Dashboard")
        .dsScreenBackground()
        .task { await viewModel.appear() }
    }

    private var periodSwitch: some View {
        Picker("Период", selection: Binding(
            get: { viewModel.period },
            set: { new in Task { await viewModel.select(new) } }
        )) {
            ForEach(DashboardPeriod.allCases, id: \.self) { period in
                Text(DashboardFormat.periodTitle(period)).tag(period)
            }
        }
        .pickerStyle(.segmented)
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .idle, .loading:
            NeonLoader(label: "Загружаю сводку")
                .frame(minHeight: 280)
        case .failure(let message):
            failure(message)
        case .loaded:
            if let summary = viewModel.summary {
                cards(summary)
            }
        }
    }

    private func failure(_ message: String) -> some View {
        VStack(spacing: DS.Spacing.lg) {
            Image(systemName: "wifi.exclamationmark")
                .font(.largeTitle)
                .foregroundStyle(DS.Palette.textSecondary)
                .accessibilityHidden(true)
            Text(message)
                .font(.body)
                .foregroundStyle(DS.Palette.textSecondary)
                .multilineTextAlignment(.center)
            Button(DashboardFormat.retryTitle) { Task { await viewModel.load() } }
                .buttonStyle(LimeButtonStyle())
                .fixedSize()
        }
        .frame(maxWidth: .infinity, minHeight: 280)
    }

    @ViewBuilder
    private func cards(_ summary: DashboardSummaryDTO) -> some View {
        statusLines(summary)
        DashboardRingsCard(scores: summary.scores)
        DashboardStreaksCard(streaks: summary.streaks)
        DashboardHealthCard(metrics: summary.health)
        DashboardBestsCard(bests: summary.bests, period: viewModel.period, today: summary.today)
        DashboardWorkoutsCard(workouts: summary.workouts)
        DashboardInsightCard(insight: summary.insight, period: viewModel.period) { onNavigate(.more(.insights)) }
        DashboardNutritionCard()
    }

    /// The window's dates, and an honest note when the numbers are an old copy or a refresh failed.
    private func statusLines(_ summary: DashboardSummaryDTO) -> some View {
        VStack(alignment: .leading, spacing: DS.Spacing.xs) {
            Text(DashboardFormat.rangeText(from: summary.from, to: summary.to))
                .font(.footnote)
                .foregroundStyle(DS.Palette.textSecondary)
            if let asOf = viewModel.offlineAsOf {
                Text(DashboardFormat.staleText(asOf))
                    .font(.footnote)
                    .foregroundStyle(DashboardPalette.amber)
            }
            if let problem = viewModel.refreshError {
                Text(problem)
                    .font(.footnote)
                    .foregroundStyle(DashboardPalette.amber)
            }
        }
    }
}
