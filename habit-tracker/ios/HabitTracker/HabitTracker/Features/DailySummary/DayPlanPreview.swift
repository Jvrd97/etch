// [review:need-review] PHASE-01/213
// summary: the reviewable half of a draft as cards — one per planned number (an estimate says so, a doubtful one says why it starts off), the checklist ticks, the day's text with its append/create/replace choice, and what could not be placed
import SwiftUI

struct DayPlanPreview: View {
    let plan: DailySummaryDraftDTO
    @ObservedObject var viewModel: DailySummaryViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.md) {
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
                .accessibilityLabel("Записать \(metric.sourceText)")
                Text("\(Self.format(metric.value)) · \(viewModel.names(categoryId: metric.categoryId, fieldId: metric.fieldId))")
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
                if metric.estimated {
                    note("оценка по описанию, проверьте, если важна точность", color: DS.Palette.textSecondary)
                }
                if metric.implausible {
                    note("число выглядит неправдоподобно, проверьте перед записью", color: DS.Palette.danger)
                } else if metric.uncertain {
                    note("модель не уверена, куда это относится", color: DS.Palette.danger)
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
                        .accessibilityLabel("Отметить \(check.sourceText)")
                        Text(viewModel.names(categoryId: check.categoryId, fieldId: check.fieldId))
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.textSecondary)
                        if check.uncertain {
                            note("модель не уверена, что речь про эту галочку", color: DS.Palette.danger)
                        }
                    }
                }
            }
        }
    }

    private func journalCard(_ journal: JournalOpDTO) -> some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.sm) {
                Toggle(isOn: $viewModel.journalEnabled) {
                    Text(journal.mode == JournalOpDTO.modeCreate ? "Создать запись дня" : "Дополнить запись дня")
                        .font(DS.Typography.card)
                        .foregroundStyle(DS.Palette.textPrimary)
                }
                .tint(DS.Palette.lime)
                Text(journal.mode == JournalOpDTO.modeCreate
                    ? "За эту дату записи ещё нет: текст станет новой записью."
                    : "Текст допишется в конец записи, ничего не пропадёт.")
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
                Text(journal.content)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textSecondary)
                    .lineLimit(6)
                if viewModel.canReplaceJournal {
                    Toggle(isOn: $viewModel.journalReplace) {
                        Text("Заменить текст: старая запись будет перезаписана")
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.textSecondary)
                    }
                    .tint(DS.Palette.danger)
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

    private static func format(_ value: Double) -> String {
        value.truncatingRemainder(dividingBy: 1) == 0
            ? String(Int(value)) : String(value)
    }
}
