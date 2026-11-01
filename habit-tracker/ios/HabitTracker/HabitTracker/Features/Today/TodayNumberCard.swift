// [review:need-review] PHASE-03/294
// summary: the Today card of a category counted in one number, laid out as on the web — the name opens the history, an input takes any amount, the step buttons adjust it, the plus records it (an empty input records the step, or one)
import SwiftUI

struct TodayNumberCard: View {
    let category: CategoryDTO
    let field: FieldDTO
    /// Today's total as the screen reads it: the sum, the single value, or a dash.
    let summary: String
    let hasEntries: Bool
    let hasPending: Bool
    @ObservedObject var viewModel: TodayViewModel
    let onOpenHistory: () -> Void

    @State private var draft = ""
    @FocusState private var focused: Bool

    private static let hitSize: CGFloat = 48
    private static let plusIconSize: CGFloat = 32

    /// The amount an empty plus records: the first positive step of the field.
    private var step: Double? {
        field.quickSteps?.first { $0 > 0 }
    }

    private var steps: [Double] {
        (field.quickSteps ?? []).filter { $0 != 0 }
    }

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.sm) {
                header
                inputRow
            }
        }
    }

    /// Everything above the input opens the history; the input row has taps of its own.
    private var header: some View {
        Button(action: onOpenHistory) {
            HStack(spacing: DS.Spacing.md) {
                if let icon = category.icon, !icon.isEmpty {
                    Text(icon).font(DS.Typography.section)
                }
                Text(category.name)
                    .font(DS.Typography.card)
                    .foregroundStyle(DS.Palette.textPrimary)
                Spacer()
                if hasPending {
                    PendingRowTag()
                }
                Text(summary)
                    .font(DS.Typography.card)
                    .foregroundStyle(hasEntries ? DS.Palette.lime : DS.Palette.textSecondary)
                Image(systemName: "chevron.right")
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textDisabled)
            }
            .frame(minHeight: DS.Spacing.xxl + DS.Spacing.md)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("today.card.\(category.id)")
    }

    private var inputRow: some View {
        HStack(spacing: DS.Spacing.sm) {
            TextField(TodayQuickAdd.formatAmount(step ?? TodayQuickAdd.implicitAmount), text: $draft)
                .keyboardType(.decimalPad)
                .focused($focused)
                .font(DS.Typography.card)
                .foregroundStyle(DS.Palette.textPrimary)
                .padding(.horizontal, DS.Spacing.md)
                .frame(minHeight: 44)
                .background(DS.Palette.surface, in: RoundedRectangle(cornerRadius: DS.Radius.control))
                .overlay(
                    RoundedRectangle(cornerRadius: DS.Radius.control)
                        .stroke(focused ? DS.Palette.lime : DS.Palette.cardStroke, lineWidth: 1)
                )
                .accessibilityLabel("\(category.name): \(field.name)")
                .accessibilityIdentifier("today.amount.\(category.id)")
            ForEach(steps, id: \.self) { stepButton($0) }
            plusButton
        }
    }

    /// Like on the web, a step button only moves the typed number; the plus records it.
    private func stepButton(_ amount: Double) -> some View {
        let label = (amount > 0 ? "+" : "−") + TodayQuickAdd.formatAmount(abs(amount))
        return Button {
            let current = Double(draft.replacingOccurrences(of: ",", with: ".")) ?? 0
            draft = TodayQuickAdd.formatAmount(current + amount)
        } label: {
            Text(label)
                .font(DS.Typography.caption)
                .foregroundStyle(DS.Palette.textPrimary)
                .padding(.horizontal, DS.Spacing.sm)
                .frame(minHeight: 44)
                .background(DS.Palette.surface, in: RoundedRectangle(cornerRadius: DS.Radius.chip))
                .overlay(RoundedRectangle(cornerRadius: DS.Radius.chip).stroke(DS.Palette.cardStroke, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(category.name): \(label)")
    }

    /// Never `.disabled`: the model drops a second tap while one save is in flight.
    private var plusButton: some View {
        let isAdding = viewModel.quickAddingCategoryIDs.contains(category.id)
        return Button {
            guard let amount = TodayQuickAdd.amount(from: draft, step: step) else { return }
            Task {
                if await viewModel.quickAdd(categoryID: category.id, amount: amount) {
                    draft = ""
                    focused = false
                }
            }
        } label: {
            Image(systemName: "plus.circle.fill")
                .font(.system(size: Self.plusIconSize))
                .foregroundStyle(DS.Palette.lime)
                .frame(width: Self.hitSize, height: Self.hitSize)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .opacity(isAdding ? 0.5 : 1)
        .accessibilityLabel("Добавить: \(category.name)")
        .accessibilityIdentifier("today.quickadd.\(category.id)")
    }
}
