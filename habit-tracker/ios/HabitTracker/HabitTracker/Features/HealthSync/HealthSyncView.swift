// [review:need-review] PHASE-02/65, PHASE-01/208, PHASE-03/131
// summary: Health section that requests access on first entry, shows four groups with honest empty values, and sends the last 7 days to the server with the result in words

import SwiftUI
import UIKit

struct HealthMetricRow: Identifiable, Equatable {
    let metric: HealthMetricDefinition
    let value: Double?

    var id: String { metric.identifier }
}

enum HealthSyncState: Equatable {
    case idle
    case syncing
    case finished(HealthSyncOutcome)
}

@MainActor
final class HealthSyncViewModel: ObservableObject {
    @Published private(set) var rows = HealthMetricCatalog.metrics.map {
        HealthMetricRow(metric: $0, value: nil)
    }
    @Published private(set) var errorMessage: String?
    @Published private(set) var syncState = HealthSyncState.idle

    private let reader: HealthDataReading
    private let syncer: HealthSyncing
    private var hasEntered = false

    init(reader: HealthDataReading, syncer: HealthSyncing) {
        self.reader = reader
        self.syncer = syncer
    }

    static func live() -> HealthSyncViewModel {
        HealthSyncViewModel(reader: HealthKitDataReader(), syncer: HealthPump.shared)
    }

    func syncNow() async {
        guard syncState != .syncing else { return }
        syncState = .syncing
        syncState = .finished(await syncer.sync())
    }

    /// The result in words. Counts come from the server; the app derives none.
    var syncMessage: String? {
        guard case .finished(let outcome) = syncState else { return nil }
        switch outcome {
        case .sent(let answers):
            return answers
                .map { "Отправлено: принято семплов \($0.samplesReceived), записано часов \($0.bucketsWritten)" }
                .joined(separator: "\n")
        case .nothingToSend:
            return "За 7 дней нет шагов и пульса покоя. Если доступ закрыт, откройте его в Настройках"
        case .notConfigured:
            return "Укажите адрес сервера в More → Settings"
        case .skipped:
            return nil
        case .failed(let failure):
            return Self.message(for: failure)
        }
    }

    private static func message(for failure: HealthSyncFailure) -> String {
        switch failure {
        case .healthDataUnavailable:
            return "На этом устройстве нет данных «Здоровья»"
        case .readFailed:
            return "Не удалось прочитать «Здоровье». Разблокируйте телефон и повторите"
        case .chunkTooLarge:
            return "Слишком много семплов одной метрики для одной отправки"
        case .network, .server:
            return "Сервер недоступен. Данные остались в «Здоровье», повторите позже"
        case .unauthorized:
            return "Сервер не принял ключ API (401)"
        case .rejected:
            return "Сервер отклонил отправку. Повтор не поможет, нужна правка приложения или сервера"
        }
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

            Section("Отправка на сервер") {
                Button(viewModel.syncState == .syncing ? "Отправляю…" : "Отправить за 7 дней") {
                    Task { await viewModel.syncNow() }
                }
                .disabled(viewModel.syncState == .syncing)
                .foregroundStyle(DS.Palette.lime)
                if let message = viewModel.syncMessage {
                    Text(message)
                        .foregroundStyle(DS.Palette.textSecondary)
                }
            }
            .listRowBackground(DS.Palette.card)

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

    private func valueText(_ row: HealthMetricRow) -> String {
        guard let value = row.value else { return "Нет данных" }
        return "\(value.formatted()) \(row.metric.unit)"
    }
}
