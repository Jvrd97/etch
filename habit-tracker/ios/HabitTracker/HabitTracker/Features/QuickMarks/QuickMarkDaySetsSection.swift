// [review:need-review] PHASE-01/210
// summary: the list of a quick-mark card's day as a List section — every tap its own row with its time and amount, the day's total as the card prints it, a taken-back set kept and marked, the undo only where the server says it will be taken, its refusal shown in the list
import SwiftUI

struct QuickMarkDaySetsSection: View {
    let mark: QuickMarkDTO
    @ObservedObject var quickMarks: QuickMarksViewModel
    @StateObject private var viewModel: QuickMarkDaySetsViewModel

    init(mark: QuickMarkDTO, quickMarks: QuickMarksViewModel) {
        self.mark = mark
        self.quickMarks = quickMarks
        _viewModel = StateObject(
            wrappedValue: QuickMarkDaySetsViewModel(
                categoryId: mark.categoryId,
                apiProvider: { APIClient.live() },
                undo: { await quickMarks.undoEvent($0) }
            )
        )
    }

    /// A category can carry several buttons (+250 and +500); the rows then say which one each
    /// came from, and stay quiet when there is only one to name.
    private var namesButtons: Bool {
        Set(viewModel.events.map(\.quickMarkId)).count > 1
    }

    /// The card's own total, read from the live directory: it moves when a set is taken back.
    private var currentMark: QuickMarkDTO {
        quickMarks.marks.first { $0.id == mark.id } ?? mark
    }

    var body: some View {
        Section {
            if let refusal = viewModel.refusal {
                Text(refusal)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.danger)
                    .listRowBackground(DS.Palette.card)
            }
            switch viewModel.state {
            case .idle, .loading:
                Text("Загружаю подходы…")
                    .foregroundStyle(DS.Palette.textSecondary)
                    .listRowBackground(DS.Palette.card)
            case .failure(let message):
                HStack {
                    Text(message).foregroundStyle(DS.Palette.danger)
                    Spacer()
                    Button("Повторить") { Task { await viewModel.load() } }
                }
                .listRowBackground(DS.Palette.card)
            case .loaded where viewModel.events.isEmpty:
                Text("За сегодня пока ничего не отмечено.")
                    .foregroundStyle(DS.Palette.textSecondary)
                    .listRowBackground(DS.Palette.card)
            case .loaded:
                ForEach(viewModel.events) { event in
                    row(for: event)
                        .listRowBackground(DS.Palette.card)
                }
            }
        } header: {
            HStack {
                Text(QuickMarkWording.heading(forKind: mark.kind))
                Spacer()
                if !currentMark.caption.isEmpty {
                    Text("Итого за день: \(currentMark.caption)").monospacedDigit()
                }
            }
        }
        .task { await viewModel.load() }
    }

    private func row(for event: QuickMarkDayEventDTO) -> some View {
        let time = QuickMarkWording.clockTime(event.occurredAt)
        return HStack(spacing: DS.Spacing.md) {
            Text(time)
                .font(DS.Typography.caption)
                .foregroundStyle(DS.Palette.textSecondary)
                .monospacedDigit()
            HStack(spacing: DS.Spacing.sm) {
                Text(event.amountText)
                    .strikethrough(event.isTakenBack)
                    .foregroundStyle(
                        event.isTakenBack ? DS.Palette.textSecondary : DS.Palette.textPrimary
                    )
                if namesButtons {
                    Text(event.label).foregroundStyle(DS.Palette.textSecondary)
                }
            }
            .lineLimit(1)
            Spacer()
            if event.isTakenBack {
                Text("отменён")
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
            }
            if event.undoable {
                Button("Отменить") {
                    Task { await viewModel.undo(eventID: event.eventId) }
                }
                .buttonStyle(.borderless)
                .disabled(viewModel.undoingEventID != nil)
                .accessibilityLabel("Отменить: \(event.amountText) в \(time)")
            }
        }
        .frame(minHeight: 44)
    }
}
