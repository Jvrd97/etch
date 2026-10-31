// [review:need-review] PHASE-01/210, PHASE-03/294
// summary: PHASE-03/294 — the day of the recorded relapse can be moved on a month grid
// summary: optional details of a relapse the tap already recorded — how much (a positive number, or leave it empty) and a note, saved as a PATCH over the entry the tap wrote
import SwiftUI

struct RelapseDetailsSheet: View {
    let category: CategoryDTO
    @ObservedObject var viewModel: TodayViewModel

    @Environment(\.dismiss) private var dismiss
    @State private var amount = ""
    @State private var notes = ""
    @State private var day = ""
    @State private var isSaving = false

    private var amountFieldName: String? {
        viewModel.amountField(forCategory: category.id)?.name
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    if let amountFieldName {
                        TextField(amountFieldName, text: $amount)
                            .keyboardType(.decimalPad)
                    }
                    TextField("Что случилось?", text: $notes, axis: .vertical)
                } footer: {
                    Text("Срыв уже записан. Здесь можно добавить подробности.")
                }
                .listRowBackground(DS.Palette.card)
                if !day.isEmpty {
                    Section {
                        DayCalendarPicker(selection: $day, maxDay: viewModel.todayString)
                    } header: {
                        Text("Когда случилось: \(RelapseAnalysis.formatDay(day))")
                    }
                    .listRowBackground(DS.Palette.card)
                }
                if let message = viewModel.saveErrorMessage {
                    Section {
                        Text(message).foregroundStyle(DS.Palette.danger)
                    }
                    .listRowBackground(DS.Palette.card)
                }
            }
            .dsScreenBackground()
            .navigationTitle("\(category.name): подробности")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Отмена") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Сохранить") { Task { await save() } }
                        .disabled(isSaving)
                }
            }
            .onAppear { prefill() }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }

    /// Starts from what the entry already holds, so a second visit edits instead of blanking.
    private func prefill() {
        viewModel.saveErrorMessage = nil
        guard case .recorded(let recorded) = viewModel.relapseState(forCategory: category.id) else {
            return
        }
        notes = recorded.entry.notes ?? ""
        day = recorded.entry.entryDate
        if let field = viewModel.amountField(forCategory: category.id),
           let stored = recorded.entry.values.first(where: { $0.fieldId == field.id })?.value {
            amount = stored
        }
    }

    private func save() async {
        isSaving = true
        defer { isSaving = false }
        if await viewModel.saveRelapseDetails(
            categoryID: category.id, amount: amount, notes: notes, day: day
        ) {
            dismiss()
        }
    }
}
