// [review:need-review] PHASE-03/162
// summary: the day-mode section of the floating window — the kind in a menu and no-code as its own switch (a working Tuesday is both), who decided it (schedule or hand), a way back to the schedule for a day decided by hand, and a note when a write did not go through
import SwiftUI

/// A change of the day mode the window asks the server for.
enum ModeChange: Equatable {
    /// Both fields go: the kind and no-code are independent.
    case decide(kind: String, nocode: Bool)
    /// Hand the date back to the schedule.
    case reset
}

struct ModeSwitcher: View {
    @ObservedObject var model: PanelModel

    var body: some View {
        if let mode = model.dayMode {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 8) {
                    Picker("Вид дня", selection: kindBinding(mode)) {
                        ForEach(PanelDayMode.kinds, id: \.self) { kind in
                            Text(PanelDayMode.label(of: kind)).tag(kind)
                        }
                        // A kind the window does not know stays selectable as it came.
                        if !PanelDayMode.kinds.contains(mode.kind) {
                            Text(PanelDayMode.label(of: mode.kind)).tag(mode.kind)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    Toggle("no-code", isOn: nocodeBinding(mode))
                        .toggleStyle(.switch)
                        .controlSize(.small)
                }
                HStack(spacing: 6) {
                    Text(model.modeWriteFailed ? "не сохранилось" : mode.sourceText)
                        .font(.caption)
                        .foregroundStyle(model.modeWriteFailed ? .orange : .secondary)
                    if mode.source == .manual {
                        Button("К расписанию") { Task { await model.resetMode() } }
                            .buttonStyle(.link)
                            .font(.caption)
                    }
                }
            }
        }
    }

    private func kindBinding(_ mode: PanelDayMode) -> Binding<String> {
        Binding(
            get: { mode.kind },
            set: { kind in Task { await model.decideMode(kind: kind, nocode: mode.nocode) } }
        )
    }

    private func nocodeBinding(_ mode: PanelDayMode) -> Binding<Bool> {
        Binding(
            get: { mode.nocode },
            set: { nocode in Task { await model.decideMode(kind: mode.kind, nocode: nocode) } }
        )
    }
}
