// [review:need-review] PHASE-03/294
// summary: the quick entry behind the plus of a habit row that has no step — one number or text field with the keyboard up, the other fields take their defaults, the save is the form save (one key per attempt, the outbox when offline)
import SwiftUI

struct QuickFieldSheet: View {
    let category: CategoryDTO
    @ObservedObject var viewModel: TodayViewModel

    @Environment(\.dismiss) private var dismiss
    @State private var amount = ""
    @State private var isSaving = false
    @FocusState private var focused: Bool

    private var field: FieldDTO? {
        switch TodayQuickAdd.plan(for: category) {
        case .amountSheet(let fieldID), .textSheet(let fieldID):
            return category.fields.first { $0.id == fieldID }
        case .step, .check, .fullForm:
            return nil
        }
    }

    private var isNumber: Bool { field?.fieldType == .number }

    /// The typed value: a number with a comma read as a point, or the trimmed text; nil while it is empty
    /// or, for a number, not a number.
    private var normalizedAmount: String? {
        let text = amount.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        guard isNumber else { return text }
        let number = text.replacingOccurrences(of: ",", with: ".")
        return Double(number) == nil ? nil : number
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(normalizedAmount ?? "—")
                        .font(DS.Typography.hero)
                        .foregroundStyle(DS.Palette.lime)
                        .lineLimit(1)
                        .minimumScaleFactor(0.5)
                        .frame(maxWidth: .infinity)
                    TextField(field?.name ?? category.name, text: $amount)
                        .keyboardType(isNumber ? .decimalPad : .default)
                        .focused($focused)
                        .accessibilityIdentifier("quickfield.field")
                }
                .listRowBackground(DS.Palette.card)
                if let message = viewModel.saveErrorMessage {
                    Section {
                        Text(message).foregroundStyle(DS.Palette.danger)
                    }
                    .listRowBackground(DS.Palette.card)
                }
            }
            .dsScreenBackground()
            .navigationTitle(category.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { Task { await save() } }
                        .disabled(isSaving || normalizedAmount == nil || field == nil)
                        .accessibilityIdentifier("quickfield.save")
                }
            }
            .onAppear {
                viewModel.saveErrorMessage = nil
                focused = true
            }
        }
        .presentationDetents([.fraction(0.45)])
        .presentationDragIndicator(.visible)
    }

    private func save() async {
        guard let field, let normalizedAmount else { return }
        isSaving = true
        defer { isSaving = false }
        var values = TodayQuickAdd.defaultValues(for: category, except: field.id)
        values[field.id] = normalizedAmount
        if await viewModel.saveEntry(categoryID: category.id, values: values) {
            dismiss()
        }
    }
}
