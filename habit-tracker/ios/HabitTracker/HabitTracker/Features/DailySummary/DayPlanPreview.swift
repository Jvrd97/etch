// [review:need-review] PHASE-01/213
// summary: the reviewable half of a draft as cards, headed by the day it will be written to — one per planned number (an estimate says so, a doubtful one says why it starts off), the checklist ticks, the day's text with its append/create/replace choice, and what could not be placed
import SwiftUI

struct DayPlanPreview: View {
    let plan: DailySummaryDraftDTO
    @ObservedObject var viewModel: DailySummaryViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.md) {
            Text("Запишется на \(DayFormat.title(of: viewModel.entryDate))")
                .font(DS.Typography.card)
                .foregroundStyle(DS.Palette.textPrimary)
                .accessibilityIdentifier("dailySummary.planDay")
            ForEach(Array(plan.metrics.enumerated()), id: \.offset) { index, metric in
                metricCard(index: index, metric: metric)
            }
            if !plan.checklist.isEmpty {
                checklistCard
            }
            if let journal = plan.journal {
                journalCard(journal)
            }
            if !plan.unresolved.isEmpty {
                unresolvedCard
            }
        }
    }

    private func metricCard(index: Int, metric: LogMetricOpDTO) -> some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.sm) {
                Toggle(isOn: Binding(
                    get: { viewModel.metricEnabled.indices.contains(index) && viewModel.metricEnabled[index] },
                    set: { viewModel.setMetric(index, enabled: $0) }
                )) {
                    Text(metric.sourceText)
                        .font(DS.Typography.card)
                        .foregroundStyle(DS.Palette.textPrimary)
                }
                .tint(DS.Palette.lime)
                .disabled(!viewModel.canEditPlan)
                .accessibilityLabel("Записать \(metric.sourceText)")
                .accessibilityHint(Self.doubt(of: metric) ?? "")
                Text("\(Self.format(metric.value)) · \(viewModel.names(categoryId: metric.categoryId, fieldId: metric.fieldId))")
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
                if metric.estimated {
                    note("оценка по описанию, проверьте, если важна точность", color: DS.Palette.textSecondary)
                }
                if let doubt = Self.doubt(of: metric) {
                    note(doubt, color: DS.Palette.danger)
                }
            }
        }
    }

    private var checklistCard: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                Label("Отметки в чек-листах", systemImage: "checklist")
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
                ForEach(Array(plan.checklist.enumerated()), id: \.offset) { index, check in
                    VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                        Toggle(isOn: Binding(
                            get: { viewModel.checkEnabled.indices.contains(index) && viewModel.checkEnabled[index] },
                            set: { viewModel.setCheck(index, enabled: $0) }
                        )) {
                            Text(check.sourceText)
                                .font(DS.Typography.card)
                                .foregroundStyle(DS.Palette.textPrimary)
                        }
                        .tint(DS.Palette.lime)
                        .disabled(!viewModel.canEditPlan)
                        .accessibilityLabel("Отметить \(check.sourceText)")
                        .accessibilityHint(check.uncertain ? Self.checkDoubt : "")
                        Text(viewModel.names(categoryId: check.categoryId, fieldId: check.fieldId))
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.textSecondary)
                        if check.uncertain {
                            note(Self.checkDoubt, color: DS.Palette.danger)
                        }
                    }
                }
            }
        }
    }

    private func journalCard(_ journal: JournalOpDTO) -> some View {
        let replacing = viewModel.isReplacingJournal
        return Card {
            VStack(alignment: .leading, spacing: DS.Spacing.sm) {
                Toggle(isOn: Binding(
                    get: { viewModel.journalEnabled },
                    set: { viewModel.setJournalEnabled($0) }
                )) {
                    Text(Self.journalTitle(for: journal.mode, replacing: replacing))
                        .font(DS.Typography.card)
                        .foregroundStyle(DS.Palette.textPrimary)
                }
                .tint(replacing ? DS.Palette.danger : DS.Palette.lime)
                .disabled(!viewModel.canEditPlan)
                Text(Self.journalCaption(for: journal.mode, replacing: replacing))
                    .font(DS.Typography.caption)
                    .foregroundStyle(replacing ? DS.Palette.danger : DS.Palette.textSecondary)
                Text(journal.content)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textSecondary)
                    .lineLimit(6)
                if viewModel.canReplaceJournal && viewModel.journalEnabled {
                    Toggle(isOn: Binding(
                        get: { viewModel.journalReplace },
                        set: { viewModel.setJournalReplace($0) }
                    )) {
                        Text("Заменить текст: старая запись будет перезаписана")
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.textSecondary)
                    }
                    .tint(DS.Palette.danger)
                    .disabled(!viewModel.canEditPlan)
                    .accessibilityLabel("Заменить текст")
                }
            }
        }
    }

    private var unresolvedCard: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.sm) {
                Label("Не нашлось категории", systemImage: "questionmark.circle")
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
                ForEach(Array(plan.unresolved.enumerated()), id: \.offset) { _, item in
                    Text(item.reason.map { "\(item.text) · \($0)" } ?? item.text)
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                }
            }
        }
    }

    private func note(_ text: String, color: Color) -> some View {
        Text(text)
            .font(DS.Typography.caption)
            .foregroundStyle(color)
    }

    static let checkDoubt = "модель не уверена, что речь про эту галочку"

    static func doubt(of metric: LogMetricOpDTO) -> String? {
        if metric.implausible { return "число выглядит неправдоподобно, проверьте перед записью" }
        if metric.uncertain { return "модель не уверена, куда это относится" }
        return nil
    }

    static func journalTitle(for mode: JournalOpDTO.Mode, replacing: Bool) -> String {
        if replacing { return "Заменить запись дня" }
        return mode == .create ? "Создать запись дня" : "Дополнить запись дня"
    }

    static func journalCaption(for mode: JournalOpDTO.Mode, replacing: Bool) -> String {
        if replacing { return "Прежний текст записи будет перезаписан и пропадёт." }
        return mode == .create
            ? "За эту дату записи ещё нет: текст станет новой записью."
            : "Текст допишется в конец записи, ничего не пропадёт."
    }

    /// A number from the model can be anything a Double holds; integer conversion would trap on 1e20.
    static func format(_ value: Double) -> String {
        value.formatted(.number)
    }
}
