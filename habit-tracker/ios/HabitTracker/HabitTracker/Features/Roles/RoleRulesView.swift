// [review:need-review] PHASE-01/266
// summary: Markup rules screen (Роли → правила) — the rules in the resolver's order with a switch per rule (the server has no delete, a switched-off rule is the way to remove one), the new-rule form with the dry run over the history before saving, and the re-markup of a week/month/quarter with its before/after and the count of rows a person had confirmed; loading, error with retry, empty list, offline note; pull to refresh; no navigation stack of its own
import SwiftUI

struct RoleRulesView: View {
    @StateObject private var viewModel: RoleRulesViewModel

    init() {
        _viewModel = StateObject(wrappedValue: .live())
    }

    init(viewModel: RoleRulesViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        VStack(spacing: 0) {
            if let asOf = viewModel.offlineAsOf {
                OfflineBanner(updatedAt: asOf)
            }
            content
        }
        .navigationTitle("Правила разметки")
        .navigationBarTitleDisplayMode(.inline)
        .dsScreenBackground()
        .task { await viewModel.appear() }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .idle, .loading:
            NeonLoader(label: "Загрузка")
        case .failure(let message):
            DSErrorState(message: message) { Task { await viewModel.load() } }
        case .loaded:
            ScrollView {
                VStack(alignment: .leading, spacing: DS.Spacing.xl) {
                    if let message = viewModel.errorMessage {
                        Text(message)
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.warning)
                            .accessibilityIdentifier("rules.error")
                    }
                    RuleListCard(viewModel: viewModel)
                    if !viewModel.roles.isEmpty {
                        RuleFormCard(viewModel: viewModel)
                    }
                    ReclassifyCard(viewModel: viewModel)
                }
                .padding(DS.Spacing.lg)
            }
            .refreshable { await viewModel.refresh() }
        }
    }
}

private struct RuleListCard: View {
    @ObservedObject var viewModel: RoleRulesViewModel

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                RolesCardTitle(text: "Правила разметки")
                if viewModel.rules.isEmpty {
                    Text(RolesFormat.emptyRulesText)
                        .font(DS.Typography.body)
                        .foregroundStyle(DS.Palette.textSecondary)
                } else {
                    ForEach(viewModel.rules) { rule in
                        HStack(alignment: .center, spacing: DS.Spacing.md) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(RolesFormat.ruleLine(rule))
                                    .font(DS.Typography.body)
                                    .foregroundStyle(DS.Palette.textPrimary)
                                RolesSecondaryText(RolesFormat.ruleTarget(rule))
                            }
                            Spacer()
                            Toggle("Включено", isOn: Binding(
                                get: { rule.isActive },
                                set: { value in Task { await viewModel.setActive(rule, isActive: value) } }
                            ))
                            .labelsHidden()
                            .tint(DS.Palette.lime)
                            .disabled(viewModel.isBusy)
                            .accessibilityIdentifier("rules.toggle.\(rule.id)")
                        }
                    }
                }
            }
        }
        .accessibilityIdentifier("rules.list")
    }
}

private struct RuleFormCard: View {
    @ObservedObject var viewModel: RoleRulesViewModel
    @State private var priorityText = String(RolesFormat.defaultPriority)

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                RolesCardTitle(text: "Новое правило")
                RolePicker(title: "Роль", roles: viewModel.roles, selection: $viewModel.draft.roleCode)
                choice("Источник", RolesFormat.sources, $viewModel.draft.source)
                choice("По чему сверять", RolesFormat.matchers, $viewModel.draft.matcherKind)
                RoleField(
                    title: "Вес (меньше — сильнее)", placeholder: "100", text: $priorityText, numeric: true, signed: true
                )
                .accessibilityIdentifier("rules.priority")
                .onChange(of: priorityText) { _, text in
                    if let value = Int(text.trimmingCharacters(in: .whitespaces)) { viewModel.draft.priority = value }
                }
                RoleField(
                    title: "Образец", placeholder: "feat(", text: $viewModel.draft.pattern
                )
                .accessibilityIdentifier("rules.pattern")
                HStack(spacing: DS.Spacing.md) {
                    Button("Прогнать по истории") { Task { await viewModel.runDryRun() } }
                        .buttonStyle(LimeButtonStyle(prominent: false))
                        .accessibilityIdentifier("rules.dry-run")
                    Button("Сохранить правило") { Task { await viewModel.saveRule() } }
                        .buttonStyle(LimeButtonStyle())
                        .accessibilityIdentifier("rules.save")
                }
                .disabled(!viewModel.canSubmitDraft)

                if let run = viewModel.dryRun {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(RolesFormat.dryRunSummary(run))
                            .font(DS.Typography.body)
                            .foregroundStyle(DS.Palette.textPrimary)
                        ForEach(RolesFormat.takenFromLines(run, rules: viewModel.rules), id: \.self) {
                            RolesSecondaryText($0)
                        }
                        ForEach(Array(run.examples.enumerated()), id: \.offset) { _, example in
                            RolesSecondaryText("\(example.workDay) · \(example.label)", color: DS.Palette.textDisabled)
                        }
                    }
                    .accessibilityIdentifier("rules.dry-run-result")
                }
            }
        }
    }

    private func choice(_ title: String, _ options: [RolesFormat.Choice], _ selection: Binding<String>) -> some View {
        HStack {
            RolesSecondaryText(title)
            Spacer()
            Picker(title, selection: selection) {
                ForEach(options, id: \.id) { Text($0.label).tag($0.id) }
            }
            .pickerStyle(.menu)
            .tint(DS.Palette.lime)
        }
    }
}

private struct ReclassifyCard: View {
    @ObservedObject var viewModel: RoleRulesViewModel

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                RolesCardTitle(text: "Переразметить период")
                HStack(spacing: DS.Spacing.sm) {
                    ForEach(RolesFormat.Period.allCases) { period in
                        Button(period.label) { viewModel.selectReclassify(period: period) }
                            .buttonStyle(LimeButtonStyle(prominent: false))
                    }
                }
                .disabled(viewModel.today == nil)
                if viewModel.reclassifyFrom != nil, viewModel.reclassifyTo != nil {
                    dayPicker("С", selection: $viewModel.reclassifyFrom)
                    dayPicker("По", selection: $viewModel.reclassifyTo)
                }
                Button("Переразметить") { Task { await viewModel.reclassify() } }
                    .buttonStyle(LimeButtonStyle(prominent: false))
                    .disabled(!viewModel.canReclassify)
                    .accessibilityIdentifier("rules.reclassify")
                if let result = viewModel.reclassified {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(RolesFormat.protectedLine(result))
                            .font(DS.Typography.body)
                            .foregroundStyle(DS.Palette.textPrimary)
                        ForEach(RolesFormat.reclassifyLines(result, roles: viewModel.roles), id: \.self) {
                            RolesSecondaryText($0)
                        }
                    }
                    .accessibilityIdentifier("rules.reclassify-result")
                }
            }
        }
    }

    /// The days are server days: the picker runs in UTC so the chosen day is the one that is sent.
    private func dayPicker(_ title: String, selection: Binding<Date?>) -> some View {
        DatePicker(
            title,
            selection: Binding(get: { selection.wrappedValue ?? Date() }, set: { selection.wrappedValue = $0 }),
            displayedComponents: .date
        )
        .environment(\.timeZone, RolesFormat.utcTimeZone)
        .tint(DS.Palette.lime)
        .font(DS.Typography.caption)
        .foregroundStyle(DS.Palette.textSecondary)
        .accessibilityIdentifier("rules.reclassify.\(title)")
    }
}
