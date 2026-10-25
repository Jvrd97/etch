// [review:need-review] PHASE-01/32-ios-lime-tech-design-pass, PHASE-01/37-ios-insights, PHASE-01/208
// summary: Dashboard screen — Lime Tech dark restyle: KPI cards, recent-activity feed, lime quick-actions; Insights entry point
import SwiftUI

struct DashboardView: View {
    @StateObject private var viewModel: DashboardViewModel

    /// Quick jumps: Today is a tab, Journal and Insights are pushed on the More stack.
    private let onNavigate: (AppDestination) -> Void

    init(viewModel: DashboardViewModel, onNavigate: @escaping (AppDestination) -> Void) {
        _viewModel = StateObject(wrappedValue: viewModel)
        self.onNavigate = onNavigate
    }

    var body: some View {
        content
            .navigationTitle("Dashboard")
            .dsScreenBackground()
        .task {
            await viewModel.load()
        }
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
            dashboard
        }
    }

    private var dashboard: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DS.Spacing.xl) {
                kpiRow
                sectionHeader("Recent activity")
                recentActivity
                sectionHeader("Quick actions")
                quickActions
            }
            .padding(DS.Spacing.lg)
        }
        .refreshable {
            await viewModel.load()
        }
    }

    private var kpiRow: some View {
        HStack(spacing: DS.Spacing.md) {
            kpiCard(label: "Categories", value: viewModel.stats.categoriesCount)
            kpiCard(label: "Entries", value: viewModel.stats.entriesCount)
            kpiCard(label: "Journal", value: viewModel.stats.journalCount)
        }
    }

    private func kpiCard(label: String, value: Int) -> some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.sm) {
                Text("\(value)")
                    .font(DS.Typography.h1)
                    .foregroundStyle(DS.Palette.textPrimary)
                    .monospacedDigit()
                Text(label)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
            }
        }
    }

    @ViewBuilder
    private var recentActivity: some View {
        if viewModel.stats.recentEntries.isEmpty {
            Card {
                Text("Nothing here yet")
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textSecondary)
            }
        } else {
            Card {
                VStack(spacing: 0) {
                    ForEach(Array(viewModel.stats.recentEntries.enumerated()), id: \.element.id) { index, entry in
                        if index > 0 {
                            Divider().overlay(DS.Palette.cardStroke)
                                .padding(.vertical, DS.Spacing.sm)
                        }
                        HStack {
                            Image(systemName: "calendar")
                                .foregroundStyle(DS.Palette.lime)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Entry #\(entry.id)")
                                    .font(DS.Typography.body)
                                    .foregroundStyle(DS.Palette.textPrimary)
                                Text(entry.entryDate)
                                    .font(DS.Typography.caption)
                                    .foregroundStyle(DS.Palette.textSecondary)
                            }
                            Spacer()
                            Text("\(entry.values.count) values")
                                .font(DS.Typography.caption)
                                .foregroundStyle(DS.Palette.textSecondary)
                        }
                    }
                }
            }
        }
    }

    private var quickActions: some View {
        HStack(spacing: DS.Spacing.md) {
            Button {
                onNavigate(.tab(.today))
            } label: {
                Label("Today", systemImage: "checkmark.circle")
            }
            .buttonStyle(LimeButtonStyle(prominent: false))
            Button {
                onNavigate(.more(.journal))
            } label: {
                Label("Journal", systemImage: "book")
            }
            .buttonStyle(LimeButtonStyle(prominent: false))
            Button {
                onNavigate(.more(.insights))
            } label: {
                Label("Insights", systemImage: "sparkles")
            }
            .buttonStyle(LimeButtonStyle(prominent: false))
        }
    }

    private func sectionHeader(_ title: String) -> some View {
        Text(title)
            .font(DS.Typography.section)
            .foregroundStyle(DS.Palette.textPrimary)
    }
}
