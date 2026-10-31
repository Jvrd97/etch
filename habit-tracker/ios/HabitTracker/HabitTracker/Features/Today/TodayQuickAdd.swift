// [review:need-review] PHASE-03/294
// summary: what the plus of a habit row does — adds the configured step or ticks the box at once, opens a one-field sheet (a number or a text and nothing else that must be filled), or leaves it to the full form
import Foundation

enum TodayQuickAdd: Equatable {
    /// One tap writes `amount` to the field.
    case step(fieldID: Int, amount: Double)
    /// One tap ticks the box: writes `true`.
    case check(fieldID: Int)
    /// A sheet with the one number field; the other fields take their defaults.
    case amountSheet(fieldID: Int)
    /// A sheet with the one text field; the other fields take their defaults.
    case textSheet(fieldID: Int)
    /// The full form: avoid categories, and sets with several fields that must be filled by hand.
    case fullForm

    static func plan(for category: CategoryDTO) -> TodayQuickAdd {
        if category.isAvoid { return .fullForm }
        let fields = category.fields.sorted { ($0.order, $0.id) < ($1.order, $1.id) }
        if category.isChecklist {
            // A checklist of one box is a tick; a longer list is read and ticked as a list.
            if fields.count == 1, fields[0].fieldType == .boolean { return .check(fieldID: fields[0].id) }
            return .fullForm
        }
        if let number = fields.first(where: { $0.fieldType == .number }) {
            // A required field the plus cannot fill from a default would be sent empty.
            guard leavesOthersToDefaults(fields, except: number) else { return .fullForm }
            if fields.count == 1, let step = number.quickSteps?.first(where: { $0 > 0 }) {
                return .step(fieldID: number.id, amount: step)
            }
            return .amountSheet(fieldID: number.id)
        }
        if let box = fields.first(where: { $0.fieldType == .boolean }), leavesOthersToDefaults(fields, except: box) {
            return .check(fieldID: box.id)
        }
        if let text = fields.first(where: { $0.fieldType == .text }), leavesOthersToDefaults(fields, except: text) {
            return .textSheet(fieldID: text.id)
        }
        return .fullForm
    }

    /// True when no other field has to be filled by hand: each is optional or carries a default.
    private static func leavesOthersToDefaults(_ fields: [FieldDTO], except one: FieldDTO) -> Bool {
        fields.allSatisfy { $0.id == one.id || !$0.isRequired || $0.defaultValue != nil }
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
