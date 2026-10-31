// [review:need-review] PHASE-03/294
// summary: what the plus of a habit row does — adds the configured step at once (one number field with a positive quick step), opens a one-field amount sheet (a number field and nothing else that must be filled), or leaves it to the full form
import Foundation

enum TodayQuickAdd: Equatable {
    /// One tap writes `amount` to the field.
    case step(fieldID: Int, amount: Double)
    /// A sheet with the one number field; the other fields take their defaults.
    case amountSheet(fieldID: Int)
    /// The full form: checklists, avoid categories, and any set the two plans above cannot fill.
    case fullForm

    static func plan(for category: CategoryDTO) -> TodayQuickAdd {
        if category.isChecklist || category.isAvoid { return .fullForm }
        let fields = category.fields.sorted { ($0.order, $0.id) < ($1.order, $1.id) }
        guard let number = fields.first(where: { $0.fieldType == .number }) else { return .fullForm }
        // A required field the plus cannot fill from a default would be sent empty.
        let others = fields.filter { $0.id != number.id }
        guard others.allSatisfy({ !$0.isRequired || $0.defaultValue != nil || $0.fieldType == .boolean }) else {
            return .fullForm
        }
        if others.isEmpty, let step = number.quickSteps?.first(where: { $0 > 0 }) {
            return .step(fieldID: number.id, amount: step)
        }
        return .amountSheet(fieldID: number.id)
    }

    /// Values of the fields other than `fieldID` that a quick entry sends: a field's default, an unticked box.
    static func defaultValues(for category: CategoryDTO, except fieldID: Int) -> [Int: String] {
        var values: [Int: String] = [:]
        for field in category.fields where field.id != fieldID {
            if let defaultValue = field.defaultValue {
                values[field.id] = defaultValue
            } else if field.fieldType == .boolean {
                values[field.id] = "false"
            }
        }
        return values
    }

    /// «250», «0.5»: no trailing «.0» on a whole step, the same in every locale.
    static func formatAmount(_ amount: Double) -> String {
        let rounded = (amount * 10_000).rounded() / 10_000
        return rounded == rounded.rounded() ? String(Int(rounded)) : String(rounded)
    }
}
