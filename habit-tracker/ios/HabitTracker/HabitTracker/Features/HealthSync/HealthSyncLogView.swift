// [review:need-review] PHASE-03/273
// summary: the "Журнал синка" screen — day and week summary (arrivals, median and longest gap, last arrival), the time since the last arrival, and the newest-first list of runs with source, counts, outcome in words and the gap to the previous arrival; pauses are shown as they are
import SwiftUI

enum HealthSyncLogText {
    /// "5 мин", "2 ч 10 мин", "1 д 3 ч". Seconds only below a minute.
    static func duration(_ seconds: TimeInterval) -> String {
        let total = Int(seconds.rounded())
        if total < 60 { return "\(max(total, 0)) с" }
        let minutes = total / 60
        if minutes < 60 { return "\(minutes) мин" }
        let hours = minutes / 60
        if hours < 24 {
            return minutes % 60 == 0 ? "\(hours) ч" : "\(hours) ч \(minutes % 60) мин"
        }
        return hours % 24 == 0 ? "\(hours / 24) д" : "\(hours / 24) д \(hours % 24) ч"
    }

    static func source(_ source: HealthSyncSource) -> String {
        switch source {
        case .appLaunch: return "Вход в приложение"
        case .backgroundWake: return "Фоновое пробуждение"
        case .manual: return "Вручную"
        }
    }

    static func outcome(_ outcome: HealthSyncLogOutcome) -> String {
        switch outcome {
        case .ok: return "Данные пришли"
        case .nothingToSend: return "Нет данных за 7 дней"
        case .notConfigured: return "Нет адреса сервера"
        case .skipped: return "Не запускался"
        case .failed(let failure): return "Отказ: \(failure.rawValue)"
        }
    }
}

struct HealthSyncLogView: View {
    let load: () -> [HealthSyncLogEntry]
    let now: () -> Date
    @State private var entries: [HealthSyncLogEntry] = []

    static func live() -> HealthSyncLogView {
        HealthSyncLogView(load: { HealthSyncLog.shared.entries }, now: Date.init)
    }

    var body: some View {
        let moment = now()
        let gaps = HealthSyncLogMath.gapsBeforeArrivals(entries)
        List {
            summarySection("За сутки", window: HealthSyncLogMath.day, now: moment)
            summarySection("За неделю", window: HealthSyncLogMath.week, now: moment)
            Section("Запуски") {
                if entries.isEmpty {
                    Text("Журнал пуст. Запись появится после первого запуска синка")
                        .foregroundStyle(DS.Palette.textSecondary)
                }
                ForEach(entries.reversed()) { entry in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(entry.at.formatted(date: .abbreviated, time: .standard))
                        Text("\(HealthSyncLogText.source(entry.source)) · \(HealthSyncLogText.outcome(entry.outcome))")
                            .foregroundStyle(entry.isArrival ? DS.Palette.lime : DS.Palette.textSecondary)
                        if entry.isArrival {
                            Text("Образцов: \(entry.samples), чанков: \(entry.chunks)\(gapText(gaps[entry.id]))")
                                .foregroundStyle(DS.Palette.textSecondary)
                        }
                    }
                }
            }
            .listRowBackground(DS.Palette.card)
        }
        .navigationTitle("Журнал синка")
        .dsScreenBackground()
        .onAppear { entries = load() }
    }

    private func gapText(_ gap: TimeInterval?) -> String {
        gap.map { ", после прошлого прихода: \(HealthSyncLogText.duration($0))" } ?? ""
    }

    private func summarySection(_ title: String, window: TimeInterval, now: Date) -> some View {
        let summary = HealthSyncLogMath.summary(entries, window: window, now: now)
        return Section(title) {
            row("Приходов данных", "\(summary.arrivals)")
            row("Медианный интервал", summary.medianInterval.map(HealthSyncLogText.duration) ?? "—")
            row("Максимальный интервал", summary.longestInterval.map(HealthSyncLogText.duration) ?? "—")
            row("Последний приход", summary.lastArrival.map {
                "\($0.formatted(date: .abbreviated, time: .shortened)), \(HealthSyncLogText.duration(now.timeIntervalSince($0))) назад"
            } ?? "ещё не было")
        }
        .listRowBackground(DS.Palette.card)
    }

    private func row(_ title: String, _ value: String) -> some View {
        HStack {
            Text(title)
            Spacer()
            Text(value).foregroundStyle(DS.Palette.textSecondary)
        }
    }
}
