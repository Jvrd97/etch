// [review:need-review] PHASE-01/268
// summary: the Health tab — the sync/lag block first (a day-old lag is visible without scrolling), the way to the pump screen and its journal, the week of nights and workouts, then every group of the catalogue with the latest value, a 30-day sparkline and the deviation from the metric's own baseline; states: loading, error with retry, the whole catalogue empty, offline from the read cache; pull to refresh in place
import SwiftUI

struct HealthMetricsView: View {
    @StateObject private var viewModel: HealthMetricsViewModel

    init(viewModel: HealthMetricsViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        content
            .navigationTitle("Здоровье")
            // Inline, like the More stack: a large title of a scrolling screen renders blank on the iOS 26 simulator.
            .navigationBarTitleDisplayMode(.inline)
            .dsScreenBackground()
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
        List {
            Section {
                if let asOf = viewModel.offlineAsOf { HealthOfflineNote(updatedAt: asOf) }
                if let status = viewModel.syncStatus {
                    HealthSyncBlock(verdict: HealthMetricsFormat.syncVerdict(status))
                }
                if let error = viewModel.refreshError {
                    Text(error).font(DS.Typography.caption).foregroundStyle(DS.Palette.danger)
                }
                NavigationLink("Синк и журнал") { HealthSyncView(viewModel: .live()) }
                    .foregroundStyle(DS.Palette.lime)
            }
            .listRowBackground(DS.Palette.card)

            if viewModel.isCatalogEmpty {
                Section {
                    Text(HealthMetricsFormat.syncHint)
                        .font(DS.Typography.body)
                        .foregroundStyle(DS.Palette.textSecondary)
                }
                .listRowBackground(DS.Palette.card)
            } else {
                if let nights = viewModel.nights {
                    HealthSleepSection(nights: nights, title: "Сон", allNights: {
                        AnyView(HealthMetricDetailView(viewModel: .live(
                            identifier: HealthMetricsFormat.sleepIdentifier, title: "Сон"
                        )))
                    }, listsNights: false)
                }
                if let workouts = viewModel.workouts {
                    HealthWorkoutsSection(workouts: workouts)
                }
                ForEach(HealthMetricsFormat.groups, id: \.id) { group in
                    let rows = HealthMetricsFormat.metrics(of: group.id, in: viewModel.metrics)
                    if !rows.isEmpty {
                        Section(group.title) {
                            ForEach(rows) { metric in
                                NavigationLink {
                                    HealthMetricDetailView(viewModel: .live(identifier: metric.identifier, title: metric.displayName))
                                } label: {
                                    HealthMetricListRow(metric: metric, today: viewModel.today)
                                }
                            }
                        }
                        .listRowBackground(DS.Palette.card)
                    }
                }
            }
        }
        .refreshable { await viewModel.refresh() }
    }
}

private struct HealthMetricListRow: View {
    let metric: HealthMetricSeriesDTO
    let today: String

    var body: some View {
        let text = HealthMetricRowText(metric, today: today)
        HStack(spacing: DS.Spacing.md) {
            Text(metric.displayName)
                .foregroundStyle(DS.Palette.textPrimary)
            Spacer(minLength: DS.Spacing.sm)
            if let text {
                HealthSparkline(points: HealthMetricsFormat.sparklinePoints(metric.days, endDate: metric.days.last?.date ?? today))
                VStack(alignment: .trailing, spacing: 2) {
                    Text(text.value).monospacedDigit()
                    if let note = text.dateNote { Text(note).font(DS.Typography.caption) }
                    if let deviation = text.deviation {
                        Text(deviation)
                            .font(DS.Typography.caption)
                            .foregroundStyle(text.outsideTypical ? DS.Palette.lime : DS.Palette.textSecondary)
                    }
                }
                .multilineTextAlignment(.trailing)
                .foregroundStyle(DS.Palette.textSecondary)
            } else {
                Text(HealthMetricRowText.noDataText).foregroundStyle(DS.Palette.textSecondary)
            }
        }
    }
}
