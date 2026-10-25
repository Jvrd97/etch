// [review:need-review] PHASE-01/211
// summary: Day screen (replaces the #208 placeholder) — day stepper, plan sections with tap-to-cycle marks and plan windows, category-linked fact cards (target, fact, unit; record/correct/remove), the two closing touches with the verdict, the notebook; the app's own calendar is not used, days are stepped with arrows
import SwiftUI

struct DayView: View {
    @StateObject private var viewModel: DayViewModel

    /// No-argument init keeps `RootView` unchanged: the model builds its client with `.live()`.
    init() {
        _viewModel = StateObject(wrappedValue: .live())
    }

    init(viewModel: DayViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        content
            .navigationTitle(AppTab.day.title)
            .dsScreenBackground()
            .task { await viewModel.load() }
            .alert(
                "Ошибка",
                isPresented: Binding(
                    get: { viewModel.actionError != nil },
                    set: { if !$0 { viewModel.actionError = nil } }
                )
            ) {
                Button("OK", role: .cancel) { viewModel.actionError = nil }
            } message: {
                Text(viewModel.actionError ?? "")
            }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .idle, .loading:
            NeonLoader(label: "Загрузка")
        case .failure(let message):
            DSErrorState(message: message) { Task { await viewModel.load() } }
        case .loaded:
            if let detail = viewModel.detail {
                loaded(detail)
            }
        }
    }

    private func loaded(_ detail: DayDetailDTO) -> some View {
        ScrollView {
            VStack(spacing: DS.Spacing.lg) {
                DayHeaderCard(viewModel: viewModel, detail: detail)
                DayPlanSection(viewModel: viewModel, detail: detail)
                DayClosingCard(viewModel: viewModel)
                DayNotebookCard(viewModel: viewModel)
            }
            .padding(DS.Spacing.lg)
        }
        .scrollDismissesKeyboard(.interactively)
        .refreshable { await viewModel.load() }
    }
}

// MARK: - Header

private struct DayHeaderCard: View {
    @ObservedObject var viewModel: DayViewModel
    let detail: DayDetailDTO

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.sm) {
                HStack {
                    Button { Task { await viewModel.showPreviousDay() } } label: {
                        Image(systemName: "chevron.left")
                    }
                    .accessibilityLabel("Предыдущий день")
                    Spacer()
                    Text(DayFormat.title(of: detail.day.date))
                        .font(DS.Typography.section)
                        .foregroundStyle(DS.Palette.textPrimary)
                    Spacer()
                    Button { Task { await viewModel.showNextDay() } } label: {
                        Image(systemName: "chevron.right")
                    }
                    .accessibilityLabel("Следующий день")
                }
                .foregroundStyle(DS.Palette.lime)

                HStack(spacing: DS.Spacing.sm) {
                    Text(DayFormat.kindLabel(detail.day.kind))
                    if detail.day.isNocode { Text("· no-code day") }
                    Spacer()
                    Button("Сегодня") { Task { await viewModel.showToday() } }
                        .foregroundStyle(DS.Palette.lime)
                }
                .font(DS.Typography.caption)
                .foregroundStyle(DS.Palette.textSecondary)

                if let counts = viewModel.counts, detail.hasPlan {
                    Text("Рабочих задач: \(counts.planned) из \(detail.rule.maxWorkTasks) · \(DayFormat.countsLine(counts))")
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                }
            }
        }
    }
}

// MARK: - Plan

private struct DayPlanSection: View {
    @ObservedObject var viewModel: DayViewModel
    let detail: DayDetailDTO

    var body: some View {
        if let plan = detail.plan {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                if let lede = plan.lede, !lede.isEmpty {
                    Text(lede)
                        .font(DS.Typography.body)
                        .foregroundStyle(DS.Palette.textSecondary)
                }
                if plan.needsReview {
                    Text("План собран автоматически и ещё не просмотрен")
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.warning)
                }
                ForEach(plan.sections) { section in
                    Card {
                        VStack(alignment: .leading, spacing: DS.Spacing.md) {
                            if let title = section.title, !title.isEmpty {
                                Text(title)
                                    .font(DS.Typography.card)
                                    .foregroundStyle(DS.Palette.textPrimary)
                            }
                            ForEach(section.items) { item in
                                PlanItemRow(
                                    viewModel: viewModel, item: item,
                                    timeZoneID: detail.rule.timezone, depth: 0
                                )
                            }
                        }
                    }
                }
            }
        } else {
            DSEmptyState(
                title: "Плана нет",
                systemImage: "list.bullet.rectangle",
                message: "На этот день план ещё не собран. План создаёт веб-версия или агент."
            )
            .frame(height: 220)
        }
    }
}

private struct PlanItemRow: View {
    @ObservedObject var viewModel: DayViewModel
    let item: DayPlanItemDTO
    let timeZoneID: String
    let depth: Int

    private var markState: String? { viewModel.state(of: item.id) }
    private var isBusy: Bool { viewModel.busyItems.contains(item.id) }

    var body: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.sm) {
            HStack(alignment: .top, spacing: DS.Spacing.md) {
                Button { Task { await viewModel.cycleMark(item.id) } } label: {
                    Image(systemName: icon)
                        .font(DS.Typography.section)
                        .foregroundStyle(tint)
                }
                .buttonStyle(.plain)
                .disabled(isBusy)
                .accessibilityLabel("Отметка: \(DayFormat.markLabel(markState))")
                .contextMenu {
                    ForEach(["done", "failed", "skipped"], id: \.self) { state in
                        Button(DayFormat.markLabel(state)) {
                            Task { await viewModel.setMark(item.id, state: state) }
                        }
                    }
                    Button("Снять отметку") { Task { await viewModel.setMark(item.id, state: nil) } }
                }

                VStack(alignment: .leading, spacing: 2) {
                    if let window = DayFormat.window(start: item.startsAt, end: item.endsAt, timeZoneID: timeZoneID) {
                        Text(window)
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.textSecondary)
                    }
                    Text(item.textPlain)
                        .font(DS.Typography.body)
                        .foregroundStyle(markState == "skipped" ? DS.Palette.textDisabled : DS.Palette.textPrimary)
                        .strikethrough(markState == "skipped")
                }
            }

            if let facts = viewModel.facts[item.id] {
                PlanFactCard(viewModel: viewModel, facts: facts)
                    .padding(.leading, DS.Spacing.xl)
            }

            ForEach(item.children) { child in
                PlanItemRow(viewModel: viewModel, item: child, timeZoneID: timeZoneID, depth: depth + 1)
                    .padding(.leading, DS.Spacing.xl)
            }
        }
    }

    private var icon: String {
        switch markState {
        case "done": return "checkmark.circle.fill"
        case "failed": return "xmark.circle.fill"
        case "skipped": return "minus.circle"
        default: return "circle"
        }
    }

    private var tint: Color {
        switch markState {
        case "done": return DS.Palette.success
        case "failed": return DS.Palette.danger
        default: return DS.Palette.textSecondary
        }
    }
}

// MARK: - Category-linked fact

/// What a linked line carries: category, target and total, each entry with its own
/// correct/delete, and the input that writes the next fact into the category's history.
private struct PlanFactCard: View {
    @ObservedObject var viewModel: DayViewModel
    let facts: PlanItemFactsDTO

    @State private var input = ""
    @State private var correcting: PlanFactEntryDTO?
    @State private var deleting: Int?

    private var link: PlanLinkDTO { facts.link }
    private var isBoolean: Bool { link.fieldType == "boolean" }
    private var isBusy: Bool { viewModel.busyItems.contains(facts.itemId) }

    var body: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.sm) {
            HStack(spacing: DS.Spacing.xs) {
                Text(link.categoryName).foregroundStyle(DS.Palette.textPrimary)
                if let field = link.fieldName { Text("· \(field)").foregroundStyle(DS.Palette.textSecondary) }
            }
            .font(DS.Typography.caption)

            Text(PlanFactLogic.progressText(facts))
                .font(DS.Typography.caption)
                .foregroundStyle(facts.progress == "partial" ? DS.Palette.warning : DS.Palette.textSecondary)

            ForEach(facts.entries) { entry in
                entryRow(entry)
            }

            if let broken = PlanFactLogic.linkStateText(link.state) {
                Text(broken).font(DS.Typography.caption).foregroundStyle(DS.Palette.warning)
            } else if link.fieldId != nil {
                inputRow
            }
        }
        .padding(DS.Spacing.md)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(DS.Palette.surface)
        .clipShape(RoundedRectangle(cornerRadius: DS.Radius.control, style: .continuous))
    }

    private func entryRow(_ entry: PlanFactEntryDTO) -> some View {
        let raw = entry.values.first { $0.fieldId == link.fieldId }?.value
        return HStack(spacing: DS.Spacing.sm) {
            Text(PlanFactLogic.valueText(fieldType: link.fieldType, raw: raw, unit: link.unit))
                .foregroundStyle(DS.Palette.textPrimary)
            Text(entry.entryDate).foregroundStyle(DS.Palette.textDisabled)
            Spacer()
            if link.state == "ok" {
                Button("Исправить") { startCorrection(entry, raw: raw) }
            }
            Button(deleting == entry.entryId ? "Точно удалить" : "Удалить") {
                if deleting == entry.entryId {
                    deleting = nil
                    Task { await viewModel.removeFact(facts.itemId, entryID: entry.entryId) }
                } else {
                    deleting = entry.entryId
                }
            }
            .foregroundStyle(DS.Palette.warning)
        }
        .font(DS.Typography.caption)
        .disabled(isBusy)
    }

    @ViewBuilder
    private var inputRow: some View {
        if isBoolean {
            HStack {
                if correcting != nil || !facts.done {
                    Button("Было") { submit(.flag(true)) }
                        .buttonStyle(LimeButtonStyle()).fixedSize()
                }
                if correcting != nil {
                    Button("Не было") { submit(.flag(false)) }
                        .buttonStyle(LimeButtonStyle(prominent: false)).fixedSize()
                    Button("Отмена") { reset() }.foregroundStyle(DS.Palette.textSecondary)
                }
            }
            .disabled(isBusy)
        } else {
            HStack {
                TextField(placeholder, text: $input)
                    .keyboardType(.numbersAndPunctuation)
                    .textFieldStyle(.roundedBorder)
                    .frame(maxWidth: 120)
                Button(correcting == nil ? "Записать" : "Сохранить") { submit(.text(input)) }
                    .buttonStyle(LimeButtonStyle()).fixedSize()
                    .disabled(input.trimmingCharacters(in: .whitespaces).isEmpty)
                if correcting != nil {
                    Button("Отмена") { reset() }.foregroundStyle(DS.Palette.textSecondary)
                }
            }
            .disabled(isBusy)
        }
    }

    private var placeholder: String {
        if link.fieldType == "duration" { return "ч:мм" }
        return link.unit ?? "число"
    }

    private func startCorrection(_ entry: PlanFactEntryDTO, raw: String?) {
        correcting = entry
        deleting = nil
        if link.fieldType == "duration", let seconds = raw.flatMap(Double.init) {
            input = PlanFactLogic.inputText(seconds: seconds)
        } else {
            input = isBoolean ? "" : (raw ?? "")
        }
    }

    private func reset() {
        input = ""
        correcting = nil
    }

    private func submit(_ value: DayViewModel.FactInput) {
        let entryID = correcting?.entryId
        Task {
            if await viewModel.saveFact(facts.itemId, input: value, correcting: entryID) { reset() }
        }
    }
}

// MARK: - Closing

private struct DayClosingCard: View {
    @ObservedObject var viewModel: DayViewModel

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                Text("Итог дня")
                    .font(DS.Typography.card)
                    .foregroundStyle(DS.Palette.textSecondary)
                if let summary = viewModel.summary {
                    summaryBlock(summary)
                }

                TextField("Минут работы (не измерено)", text: $viewModel.closingMinutes)
                    .keyboardType(.numberPad)
                    .textFieldStyle(.roundedBorder)
                TextField("Что случилось вместо плана, что мешало", text: $viewModel.closingBody, axis: .vertical)
                    .lineLimit(3...8)
                    .textFieldStyle(.roundedBorder)

                Button(viewModel.summary?.stage == "open" || viewModel.summary == nil
                       ? "Записать ревью 15:40" : "Обновить ревью") {
                    Task { await viewModel.review() }
                }
                .buttonStyle(LimeButtonStyle(prominent: false))
                .disabled(viewModel.isClosing)

                Button(viewModel.summary?.closed == true ? "Закрыть день заново" : "Закрыть день") {
                    Task { await viewModel.closeDay() }
                }
                .buttonStyle(LimeButtonStyle())
                .disabled(viewModel.isClosing)
            }
        }
    }

    @ViewBuilder
    private func summaryBlock(_ summary: DaySummaryDTO) -> some View {
        Text(DayFormat.headline(summary))
            .font(DS.Typography.section)
            .foregroundStyle(summary.verdict == "lost" ? DS.Palette.danger : DS.Palette.textPrimary)
        if summary.closed, !summary.verdictReason.isEmpty {
            Text("Не выполнено: \(DayFormat.reasonLabel(summary.verdictReason))")
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.warning)
        }
        Text("Задачи \(summary.tasksDone) из \(summary.tasksTotal) · якоря \(summary.anchorsDone) из \(summary.anchorsTotal)")
            .font(DS.Typography.caption)
            .foregroundStyle(DS.Palette.textSecondary)
        if let streak = summary.streakAfter {
            Text("Серия выигранных дней: \(streak)")
                .font(DS.Typography.caption)
                .foregroundStyle(DS.Palette.textSecondary)
        }
        if !summary.missingAnchors.isEmpty {
            Text("Не отмечены якоря: " + summary.missingAnchors.joined(separator: ", "))
                .font(DS.Typography.caption)
                .foregroundStyle(DS.Palette.warning)
        }
    }
}

// MARK: - Notebook

private struct DayNotebookCard: View {
    @ObservedObject var viewModel: DayViewModel

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                Text("Блокнот дня")
                    .font(DS.Typography.card)
                    .foregroundStyle(DS.Palette.textSecondary)
                TextEditor(text: $viewModel.notebook)
                    .scrollContentBackground(.hidden)
                    .frame(minHeight: 120)
                    .padding(DS.Spacing.sm)
                    .background(DS.Palette.surface)
                    .clipShape(RoundedRectangle(cornerRadius: DS.Radius.control, style: .continuous))
                Button("Сохранить") { Task { await viewModel.saveNotebook() } }
                    .buttonStyle(LimeButtonStyle())
                    .disabled(!viewModel.isNotebookDirty || viewModel.isSavingNotebook)
            }
        }
    }
}
