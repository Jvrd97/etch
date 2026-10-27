// [review:need-review] PHASE-03/225
// summary: the one counter of the offline queue shown atop Today, Quick marks and Day — "written on the phone, waiting to send: N", "not sent: M" and a word when the server refuses the API key; a tap opens the list of waiting writes with their day and the "not sent" ones with the reason, a retry that says what it will do and sends at once, and discard
import SwiftUI

/// A strip that appears while the queue holds anything. The count is the queue's, not a screen's:
/// every screen shows the same number.
struct OutboxQueueBar: View {
    @ObservedObject var queue: OutboxQueue
    @State private var showsList = false

    static let keyRefusedCaption = "сервер не принял ключ API — проверьте Settings"

    static func caption(pending: Int, failed: Int, waitsForKey: Bool = false) -> String {
        var parts: [String] = []
        if pending > 0 { parts.append("Записано на телефоне, ждёт отправки: \(pending)") }
        if pending > 0 && waitsForKey { parts.append(keyRefusedCaption) }
        if failed > 0 { parts.append("Не отправлено: \(failed)") }
        return parts.joined(separator: " · ")
    }

    var body: some View {
        if !queue.writes.isEmpty {
            Button { showsList = true } label: {
                HStack(spacing: DS.Spacing.sm) {
                    Image(systemName: queue.failedCount > 0 ? "exclamationmark.icloud" : "icloud.and.arrow.up")
                    Text(Self.caption(pending: queue.pendingCount, failed: queue.failedCount, waitsForKey: queue.waitsForKey))
                        .font(DS.Typography.caption)
                        .multilineTextAlignment(.leading)
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.right")
                        .font(DS.Typography.caption)
                }
                .foregroundStyle(queue.failedCount > 0 ? DS.Palette.warning : DS.Palette.lime)
                .padding(.vertical, DS.Spacing.sm)
                .padding(.horizontal, DS.Spacing.md)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(DS.Palette.card)
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("outbox.bar")
            .sheet(isPresented: $showsList) {
                OutboxQueueList(queue: queue)
            }
        }
    }
}

/// What waits for the network and what the server would not take, with what can be done about it.
struct OutboxQueueList: View {
    @ObservedObject var queue: OutboxQueue
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                if !queue.failed.isEmpty {
                    Section("Не отправлено") {
                        ForEach(queue.failed) { write in
                            row(write)
                            HStack {
                                Button(write.retryTitle) { Task { await queue.retry(id: write.id) } }
                                    .buttonStyle(.borderless)
                                Spacer()
                                Button("Удалить", role: .destructive) { queue.discard(id: write.id) }
                                    .buttonStyle(.borderless)
                            }
                            .font(DS.Typography.caption)
                        }
                    }
                }
                if !queue.pending.isEmpty {
                    Section {
                        ForEach(queue.pending) { row($0) }
                    } header: {
                        Text("Ждёт отправки")
                    } footer: {
                        Text("Уйдёт сама, когда появится сеть. Каждое действие записывается на свой день.")
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .dsScreenBackground()
            .navigationTitle("Очередь записи")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Готово") { dismiss() }
                }
            }
            .task { await queue.flush() }
        }
        .presentationDetents([.medium, .large])
    }

    private func row(_ write: OutboxWrite) -> some View {
        VStack(alignment: .leading, spacing: DS.Spacing.xs) {
            Text(write.label)
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.textPrimary)
            if let day = write.action.day {
                Text(DayFormat.title(of: day))
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
            }
            if case .saveNotebook(let notebook) = write.action {
                Text(notebook.content)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
                    .lineLimit(4)
                    .textSelection(.enabled)
            }
            if let failure = write.failure {
                Text(failure)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.danger)
            }
        }
        .listRowBackground(DS.Palette.card)
    }
}
