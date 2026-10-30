// [review:need-review] PHASE-01/268
// summary: one metric's detail screen — the period switch (7/30/90 days), the days of the period (tap to choose one), then the 24 hours of the chosen day (an hour without data is «нет данных», min–max for a discrete hour) or, for sleep, the nights of the period ending at that day; states: loading, error with retry, no days, offline from the read cache
import SwiftUI

struct HealthMetricDetailView: View {
    @StateObject private var viewModel: HealthMetricDetailViewModel

    init(viewModel: HealthMetricDetailViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        content
            .navigationTitle(viewModel.title)
            .navigationBarTitleDisplayMode(.inline)
            .dsScreenBackground()
            .task { await viewModel.load() }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.days {
        case .loading:
            NeonLoader(label: "Загрузка")
        case .failure(let message):
            DSErrorState(message: message) { Task { await viewModel.load() } }
        case .ready(let series):
            List {
                Section {
                    if let asOf = viewModel.offlineAsOf { HealthOfflineNote(updatedAt: asOf) }
                    periodSwitch
                }
                .listRowBackground(DS.Palette.card)
                if series.days.isEmpty {
                    Section {
                        Text("За этот период данных нет.")
                            .foregroundStyle(DS.Palette.textSecondary)
                    }
                    .listRowBackground(DS.Palette.card)
                } else {
                    daysSection(series)
                    if viewModel.isSleep { nightsSection } else { hoursSection(series) }
                }
            }
        }
    }

    private var periodSwitch: some View {
        HStack(spacing: DS.Spacing.sm) {
            ForEach(HealthMetricsFormat.periods, id: \.days) { period in
                Button(period.label) { Task { await viewModel.selectPeriod(period.days) } }
                    .buttonStyle(LimeButtonStyle(prominent: period.days == viewModel.periodDays))
                    .accessibilityAddTraits(period.days == viewModel.periodDays ? .isSelected : [])
            }
        }
        .buttonStyle(.borderless)
    }

    private func daysSection(_ series: HealthMetricDaysResponseDTO) -> some View {
        Section("По дням") {
            ForEach(series.days.reversed(), id: \.date) { entry in
                Button {
                    Task { await viewModel.selectDay(entry.date) }
                } label: {
                    HStack {
                        Text(HealthMetricsFormat.dayLabel(entry.date))
                            .foregroundStyle(DS.Palette.textSecondary)
                        Spacer()
                        Text(HealthMetricsFormat.formatQuantity(identifier: series.identifier, value: entry.value, unit: series.canonicalUnit))
                            .monospacedDigit()
                            .foregroundStyle(DS.Palette.textPrimary)
                    }
                }
                .listRowBackground(entry.date == viewModel.shownDay ? DS.Palette.cardStroke : DS.Palette.card)
                .accessibilityAddTraits(entry.date == viewModel.shownDay ? .isSelected : [])
            }
        }
    }

    @ViewBuilder
    private var nightsSection: some View {
        switch viewModel.nights {
        case .loading:
            Section { ProgressView() }.listRowBackground(DS.Palette.card)
        case .failure(let message):
            Section { Text(message).foregroundStyle(DS.Palette.danger) }.listRowBackground(DS.Palette.card)
        case .ready(let nights):
            HealthSleepSection(nights: nights, title: "Ночи периода")
        }
    }

    @ViewBuilder
    private func hoursSection(_ series: HealthMetricDaysResponseDTO) -> some View {
        let title = "Часы: \(HealthMetricsFormat.dayLabel(viewModel.shownDay ?? ""))"
        switch viewModel.hours {
        case .loading:
            Section(title) { ProgressView() }.listRowBackground(DS.Palette.card)
        case .failure(let message):
            Section(title) { Text(message).foregroundStyle(DS.Palette.danger) }.listRowBackground(DS.Palette.card)
        case .ready(let hours):
            let slots = HealthMetricsFormat.hourSlots(hours.hours)
            let peak = hours.hours.map(\.value).max() ?? 0
            Section(title) {
                ForEach(slots.indices, id: \.self) { hour in
                    HealthHourRow(hour: hour, slot: slots[hour], peak: peak, discrete: hours.kind == "discrete", whole: HealthMetricsFormat.isWhole(unit: hours.canonicalUnit))
                }
            }
            .listRowBackground(DS.Palette.card)
        }
    }
}

private struct HealthHourRow: View {
    let hour: Int
    let slot: HealthHourValueDTO?
    let peak: Double
    let discrete: Bool
    let whole: Bool

    private static let minShare = 0.02

    var body: some View {
        HStack(spacing: DS.Spacing.md) {
            Text(HealthMetricsFormat.hourLabel(hour))
                .monospacedDigit()
                .foregroundStyle(DS.Palette.textSecondary)
            if let slot {
                GeometryReader { box in
                    Capsule()
                        .fill(DS.Palette.lime)
                        .frame(width: box.size.width * (peak > 0 ? max(Self.minShare, slot.value / peak) : Self.minShare))
                }
                .frame(height: 8)
                Text(whole ? String(Int(slot.value.rounded())) : HealthMetricsFormat.formatValue(slot.value)).monospacedDigit()
                if discrete, let range = HealthMetricsFormat.hourRange(slot) {
                    Text(range).font(DS.Typography.caption).foregroundStyle(DS.Palette.textSecondary)
                }
            } else {
                Text("нет данных").foregroundStyle(DS.Palette.textSecondary)
                Spacer()
            }
        }
        .accessibilityElement(children: .combine)
    }
}
