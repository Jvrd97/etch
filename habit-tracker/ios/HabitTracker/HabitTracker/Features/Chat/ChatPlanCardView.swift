// [review:need-review] PHASE-01/212, PHASE-03/230
// summary: the card under an assistant message that proposed a plan — a toggle per proposed operation (doubtful rows unticked), apply and dismiss, and after the apply the count of what was written
import SwiftUI

struct ChatPlanCardView: View {
    let plan: ChatPlanDTO
    @ObservedObject var viewModel: ChatViewModel

    private static let unsure = "Модель не уверена"

    private var isProposed: Bool { plan.status == ChatPlanDTO.proposedStatus }
    private var isBusy: Bool { viewModel.planBusy.contains(plan.id) }
    private var canApply: Bool { isProposed && !isBusy && viewModel.planDrafts[plan.id]?.isEmpty == false }

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                Text("Предложение чата · \(plan.entryDate)")
                    .font(DS.Typography.card)
                    .foregroundStyle(DS.Palette.textPrimary)
                if isProposed {
                    rows
                    buttons
                } else {
                    outcome
                }
                if let notice = viewModel.planNotices[plan.id] {
                    Text(notice)
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.danger)
                }
            }
        }
    }

    @ViewBuilder
    private var rows: some View {
        let proposal = plan.plan
        ForEach(Array(proposal.metrics.enumerated()), id: \.offset) { index, metric in
            row(.metric(index), label: "\(metric.sourceText) — \(metric.value.formatted())", doubt: metric.implausible ? "Значение выглядит странно" : (metric.uncertain ? Self.unsure : nil))
        }
        ForEach(Array(proposal.checklist.enumerated()), id: \.offset) { index, check in
            row(.check(index), label: check.sourceText, doubt: check.uncertain ? Self.unsure : nil)
        }
        if let journal = proposal.journal {
            row(.journal, label: (journal.mode == .create ? "Новая запись в дневнике: " : "Дополнить дневник: ") + journal.content, doubt: nil)
        }
        if let dayPlan = proposal.dayPlan {
            row(
                .dayPlan,
                label: (dayPlan.isRewrite ? "Заменить план дня" : "Собрать план дня") + " · строк: \(dayPlan.itemCount)",
                doubt: nil
            )
        }
    }

    private func row(_ item: ChatPlanDraft.Item, label: String, doubt: String?) -> some View {
        Toggle(isOn: Binding(
            get: { viewModel.planDrafts[plan.id]?.isTicked(item) ?? false },
            set: { _ in viewModel.togglePlanItem(item, planID: plan.id) }
        )) {
            VStack(alignment: .leading, spacing: 2) {
                Text(label)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textPrimary)
                    .lineLimit(3)
                if let doubt {
                    Text(doubt)
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.warning)
                }
            }
        }
        .tint(DS.Palette.lime)
        .disabled(isBusy)
    }

    private var buttons: some View {
        HStack(spacing: DS.Spacing.sm) {
            Button("Применить") {
                Task { await viewModel.applyPlan(id: plan.id) }
            }
            .buttonStyle(LimeButtonStyle())
            .disabled(!canApply)
            Button("Отклонить") {
                Task { await viewModel.dismissPlan(id: plan.id) }
            }
            .buttonStyle(LimeButtonStyle(prominent: false))
            .disabled(isBusy)
        }
    }

    @ViewBuilder
    private var outcome: some View {
        switch plan.status {
        case ChatPlanDTO.appliedStatus:
            Label(
                "Применено" + (viewModel.appliedOperations[plan.id].map { ": операций \($0)" } ?? ""),
                systemImage: "checkmark.circle.fill"
            )
            .foregroundStyle(DS.Palette.success)
        case ChatPlanDTO.dismissedStatus:
            Label("Отклонено", systemImage: "xmark.circle")
                .foregroundStyle(DS.Palette.textSecondary)
        default:
            Label("План устарел", systemImage: "clock.badge.exclamationmark")
                .foregroundStyle(DS.Palette.warning)
        }
    }
}
