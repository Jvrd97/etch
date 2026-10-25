// [review:need-review] PHASE-03/159
// summary: the content of the floating window — date and a stale marker, the current task, the timer with start and stop, the button that opens the day in the browser, and an empty band kept for the quick marks of #170
import SwiftUI

/// The window is a column of sections. A new one (the day mode of #162, the quick
/// marks of #170) is one more line in `PanelView.body`, not a change to the others.
struct PanelView: View {
    @ObservedObject var model: PanelModel
    let onMinimize: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            PanelHeader(model: model, onMinimize: onMinimize)
            TaskSection(model: model)
            TimerSection(timer: model.timer, onToggle: model.toggleTimer)
            Spacer(minLength: 0)
            QuickMarksSlot()
            Button(action: model.openDayInBrowser) {
                Label("Открыть день в браузере", systemImage: "safari")
                    .frame(maxWidth: .infinity)
            }
            .disabled(!model.canOpenDay)
        }
        .padding(12)
        .frame(width: FloatingPanelController.contentSize.width, height: FloatingPanelController.contentSize.height)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

private struct PanelHeader: View {
    @ObservedObject var model: PanelModel
    let onMinimize: () -> Void

    var body: some View {
        HStack(spacing: 6) {
            Text(model.dateLabel ?? "Habit Agent")
                .font(.headline)
            Spacer(minLength: 0)
            if model.configIsStale {
                Label("данные не свежие", systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .help("Сервер давно не отвечает; показано то, что приехало последним")
            }
            Button(action: onMinimize) {
                Image(systemName: "minus")
            }
            .buttonStyle(.borderless)
            .help("Свернуть в меню-бар")
            .accessibilityLabel("Свернуть окно")
        }
    }
}

private struct TaskSection: View {
    @ObservedObject var model: PanelModel

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            if let running = model.timer.task {
                Text(running.title)
                    .font(.body)
                    .lineLimit(2)
                Text("идёт таймер")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else if let task = model.currentTask {
                Text(task.title)
                    .font(.body)
                    .lineLimit(2)
                Text(model.windowLabel(of: task))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                Text(emptyText)
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .frame(maxWidth: .infinity, minHeight: 52, alignment: .topLeading)
    }

    private var emptyText: String {
        if model.needsSetup { return "Укажите адрес сервера и ключ в меню" }
        if model.config.value == nil { return "Ждём ответа сервера" }
        return "Задачи на сейчас нет"
    }
}

private struct TimerSection: View {
    @ObservedObject var timer: TaskTimer
    let onToggle: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text(Self.format(timer.elapsed))
                    .font(.system(size: 26, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                Spacer(minLength: 0)
                Button(timer.isRunning ? "Стоп" : "Старт", action: onToggle)
            }
            Text(stopNote ?? " ")
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
    }

    private var stopNote: String? {
        switch timer.lastStop {
        case let .idle(since)?:
            return "Остановлен: ввода не было с \(Self.clock(since))"
        case let .suspended(since)?:
            return "Остановлен: мак спал, конец в \(Self.clock(since))"
        case .manual?, nil:
            return nil
        }
    }

    static func format(_ seconds: TimeInterval) -> String {
        let total = Int(seconds)
        return String(format: "%d:%02d:%02d", total / 3600, total % 3600 / 60, total % 60)
    }

    private static func clock(_ date: Date) -> String {
        date.formatted(date: .omitted, time: .shortened)
    }
}

/// Room for the quick marks of #170: they are drawn there, not by this ticket.
private struct QuickMarksSlot: View {
    static let height: CGFloat = 28

    var body: some View {
        Color.clear.frame(height: Self.height)
    }
}
