// [review:need-review] PHASE-02/65
// summary: Health section that requests access on first entry and shows four groups with honest empty values

import SwiftUI
import UIKit

struct HealthMetricRow: Identifiable, Equatable {
    let metric: HealthMetricDefinition
    let value: Double?

    var id: String { metric.identifier }
}

@MainActor
final class HealthSyncViewModel: ObservableObject {
    @Published private(set) var rows = HealthMetricCatalog.metrics.map {
        HealthMetricRow(metric: $0, value: nil)
    }
    @Published private(set) var errorMessage: String?

    private let reader: HealthDataReading
    private var hasEntered = false

    init(reader: HealthDataReading) {
        self.reader = reader
    }

    static func live() -> HealthSyncViewModel {
        HealthSyncViewModel(reader: HealthKitDataReader())
    }

    func enterSection() async {
        guard !hasEntered else { return }
        hasEntered = true
        do {
            let metrics = HealthMetricCatalog.metrics
            try await reader.requestReadAuthorization(for: Set(metrics.map(\.identifier)))
            let values = try await reader.readLatestValues(for: metrics)
            rows = metrics.map { HealthMetricRow(metric: $0, value: values[$0.identifier]) }
        } catch {
            errorMessage = "Не удалось прочитать данные здоровья"
        }
    }
}

struct HealthSyncView: View {
    @StateObject private var viewModel: HealthSyncViewModel
    @Environment(\.openURL) private var openURL

    init(viewModel: HealthSyncViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        NavigationStack {
            List {
                if let errorMessage = viewModel.errorMessage {
                    Text(errorMessage)
                        .foregroundStyle(DS.Palette.danger)
                }
                Button("Настройки доступа") {
                    if let url = URL(string: UIApplication.openSettingsURLString) {
                        openURL(url)
                    }
                }
                .foregroundStyle(DS.Palette.lime)

                ForEach(HealthMetricGroup.allCases, id: \.self) { group in
                    Section(group.title) {
                        ForEach(viewModel.rows.filter { $0.metric.group == group }) { row in
                            HStack {
                                Text(row.metric.displayName)
                                Spacer()
                                Text(valueText(row))
                                    .foregroundStyle(DS.Palette.textSecondary)
                            }
                        }
                    }
                    .listRowBackground(DS.Palette.card)
                }
            }
            .navigationTitle("Здоровье")
            .dsScreenBackground()
            .task { await viewModel.enterSection() }
        }
    }

    private func valueText(_ row: HealthMetricRow) -> String {
        guard let value = row.value else { return "Нет данных" }
        return "\(value.formatted()) \(row.metric.unit)"
    }
}
