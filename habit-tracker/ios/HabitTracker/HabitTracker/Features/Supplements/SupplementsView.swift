// [review:need-review] PHASE-03/240, PHASE-03/258
// summary: re-reads when the server's day turns (timer, clock or zone change); «Принял: <название>» for VoiceOver; the button is off while its press is in flight; the form's error is cleared on close; Supplements screen (More → Добавки) — the list with a «Принял» button per supplement («Принято сегодня» once marked, «ждёт отправки» while the press is in the queue), the shared offline-queue strip on top, the offline note over a cached list, an add sheet (name, dose, unit, planned time from two menus — no system date picker), loading, error with retry and empty states; no navigation stack of its own
// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 — the cached list is drawn before the first frame; a return to the app reads again only what is not recent
import SwiftUI

struct SupplementsView: View {
    @StateObject private var viewModel: SupplementsViewModel
    @State private var isAdding = false
    @Environment(\.scenePhase) private var scenePhase

    /// No-argument init keeps `RootView` to one line: the model builds its client with `.live()`.
    init() {
        _viewModel = StateObject(wrappedValue: .live())
    }

    init(viewModel: SupplementsViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        VStack(spacing: 0) {
            OutboxQueueBar(queue: OutboxLive.shared)
            if let asOf = viewModel.offlineAsOf {
                OfflineBanner(updatedAt: asOf)
            }
            content
        }
        .navigationTitle(MoreDestination.supplements.title)
        .dsScreenBackground()
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    viewModel.clearError()
                    isAdding = true
                } label: {
                    Image(systemName: "plus")
                }
                .accessibilityLabel("Добавить добавку")
                .accessibilityIdentifier("supplements.add")
            }
        }
        .onAppear { viewModel.showCached() }
        .task { await viewModel.appear() }
        .onChange(of: scenePhase) { _, phase in
            // The server's day may have turned while the app was away; the timer below reads at the turn itself.
            if phase == .active { Task { await viewModel.appear() } }
        }
        .task(id: viewModel.rule) { await rereadWhenTheDayTurns() }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.significantTimeChangeNotification)) { _ in
            Task { await viewModel.load() }
        }
        .onReceive(NotificationCenter.default.publisher(for: .NSSystemTimeZoneDidChange)) { _ in
            Task { await viewModel.load() }
        }
        .sheet(isPresented: $isAdding) {
            SupplementFormSheet(viewModel: viewModel)
        }
    }

    /// Sleeps to the next turn of the server's day, reads again, and waits for the one after.
    private func rereadWhenTheDayTurns() async {
        while !Task.isCancelled {
            guard let seconds = viewModel.secondsUntilDayTurn() else { return }
            try? await Task.sleep(for: .seconds(max(seconds, 0) + Self.turnSlackSeconds))
            if Task.isCancelled { return }
            await viewModel.load()
        }
    }

    private static let turnSlackSeconds = 1.0

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .idle, .loading:
            NeonLoader(label: "Загрузка")
        case .failure(let message):
            DSErrorState(message: message) { Task { await viewModel.load() } }
        case .loaded where viewModel.rows.isEmpty:
            DSEmptyState(
                title: "Добавок пока нет",
                systemImage: "pills",
                message: "Заведите добавки, которые пьёте: отметка «принял» попадает в советы.",
                action: (label: "Добавить", run: { viewModel.clearError(); isAdding = true })
            )
        case .loaded:
            ScrollView {
                VStack(spacing: DS.Spacing.md) {
                    if let message = viewModel.errorMessage {
                        Text(message)
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.danger)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .accessibilityIdentifier("supplements.error")
                    }
                    ForEach(viewModel.rows) { row in
                        SupplementRowView(row: row) { Task { await viewModel.markTaken(row.supplement) } }
                    }
                }
                .padding(DS.Spacing.lg)
            }
            .refreshable { await viewModel.load() }
        }
    }
}

private struct SupplementRowView: View {
    let row: SupplementsViewModel.Row
    let onTake: () -> Void

    var body: some View {
        Card {
            HStack(spacing: DS.Spacing.md) {
                VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                    Text(row.supplement.name)
                        .font(DS.Typography.card)
                        .foregroundStyle(DS.Palette.textPrimary)
                    Text(SupplementsFormat.detail(row.supplement))
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                    if row.isWaiting {
                        Text(Self.waitingText(since: row.waitingSince))
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.lime)
                    }
                }
                Spacer(minLength: DS.Spacing.sm)
                Button(action: onTake) {
                    Label(row.isTaken ? "Принято сегодня" : "Принял", systemImage: row.isTaken ? "checkmark.circle.fill" : "circle")
                        .labelStyle(.titleAndIcon)
                        .font(DS.Typography.caption)
                }
                .buttonStyle(LimeButtonStyle(prominent: !row.isTaken))
                // Wraps to a second line at a large text size instead of being cut off or pushing the name out.
                .fixedSize(horizontal: false, vertical: true)
                .disabled(row.isTaken || row.isSending)
                .accessibilityLabel(row.isTaken ? "Принято сегодня: \(row.supplement.name)" : "Принял: \(row.supplement.name)")
                .accessibilityIdentifier("supplements.take.\(row.supplement.id)")
            }
        }
        .accessibilityElement(children: .contain)
    }

    private static func waitingText(since: Date?) -> String {
        guard let since else { return "ждёт отправки" }
        return "ждёт отправки · нажато " + since.formatted(date: .omitted, time: .shortened)
    }
}

/// Add form: name, dose with its unit, and an optional planned time chosen from two menus.
struct SupplementFormSheet: View {
    @ObservedObject var viewModel: SupplementsViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var draft = SupplementDraft()

    private static let minutes = Array(stride(from: 0, to: 60, by: SupplementsFormat.minuteStep))

    var body: some View {
        NavigationStack {
            Form {
                Section("Добавка") {
                    TextField("Название", text: $draft.name)
                        .accessibilityIdentifier("supplements.form.name")
                    TextField("Доза", text: $draft.doseText)
                        .keyboardType(.decimalPad)
                        .accessibilityIdentifier("supplements.form.dose")
                    TextField("Единица", text: $draft.unit)
                        .accessibilityIdentifier("supplements.form.unit")
                }
                .listRowBackground(DS.Palette.card)
                Section("Время приёма") {
                    Toggle("Назначить время", isOn: $draft.hasTime)
                        .tint(DS.Palette.lime)
                    if draft.hasTime {
                        HStack {
                            Picker("Часы", selection: $draft.hour) {
                                ForEach(0..<24, id: \.self) { Text(String(format: "%02d", $0)).tag($0) }
                            }
                            Text(":")
                            Picker("Минуты", selection: $draft.minute) {
                                ForEach(Self.minutes, id: \.self) { Text(String(format: "%02d", $0)).tag($0) }
                            }
                        }
                        .pickerStyle(.menu)
                    }
                }
                .listRowBackground(DS.Palette.card)
                if let message = viewModel.errorMessage {
                    Section {
                        Text(message).foregroundStyle(DS.Palette.danger)
                            .accessibilityIdentifier("supplements.form.error")
                    }
                    .listRowBackground(DS.Palette.card)
                }
            }
            .dsScreenBackground()
            .navigationTitle("Новая добавка")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Отмена") {
                        viewModel.clearError()
                        dismiss()
                    }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Сохранить") {
                        Task { if await viewModel.add(draft) { dismiss() } }
                    }
                    .disabled(viewModel.isSaving)
                    .accessibilityIdentifier("supplements.form.save")
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}
