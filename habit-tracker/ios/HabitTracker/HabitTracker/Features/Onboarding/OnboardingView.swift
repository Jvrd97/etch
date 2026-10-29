// [review:need-review] PHASE-01/267
// summary: Onboarding screen (More → Онбординг, or the sheet of the first launch) — the built-in category templates above the voice builder, as on /m/onboarding: pick templates, say in words what to track, tick the plan the model drafts, rename new categories, create the ticked part; states: loading, empty-catalog, error with retry, offline note with the cached moment; no navigation stack of its own
import SwiftUI

struct OnboardingView: View {
    @StateObject private var templates: OnboardingTemplatesModel
    @StateObject private var plan: OnboardingPlanModel
    let onOpenCategories: () -> Void

    /// No model arguments keep `RootView` to one line: both models build their client with `.live()`.
    init(onOpenCategories: @escaping () -> Void) {
        _templates = StateObject(wrappedValue: .live())
        _plan = StateObject(wrappedValue: .live())
        self.onOpenCategories = onOpenCategories
    }

    init(templates: OnboardingTemplatesModel, plan: OnboardingPlanModel, onOpenCategories: @escaping () -> Void) {
        _templates = StateObject(wrappedValue: templates)
        _plan = StateObject(wrappedValue: plan)
        self.onOpenCategories = onOpenCategories
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DS.Spacing.xl) {
                OnboardingTemplatesSection(model: templates, onOpenCategories: onOpenCategories)
                OnboardingBuilderSection(model: plan, onOpenCategories: onOpenCategories)
            }
            .padding(DS.Spacing.lg)
        }
        .scrollDismissesKeyboard(.interactively)
        .navigationTitle(MoreDestination.onboarding.title)
        .navigationBarTitleDisplayMode(.inline)
        .dsScreenBackground()
        .task { if templates.loadState == .idle { await templates.load() } }
    }
}

// MARK: - Templates

private struct OnboardingTemplatesSection: View {
    @ObservedObject var model: OnboardingTemplatesModel
    let onOpenCategories: () -> Void

    var body: some View {
        switch model.step {
        case .dismissed:
            Button("Показать шаблоны") { Task { await model.reopen() } }
                .buttonStyle(LimeButtonStyle(prominent: false))
        case .applied(let added, let skipped):
            applied(added: added, skipped: skipped)
        case .open:
            picker
        }
    }

    private func applied(added: [String], skipped: [String]) -> some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                if !added.isEmpty {
                    Text("Добавлено: \(added.joined(separator: ", ")).")
                        .font(DS.Typography.body)
                        .foregroundStyle(DS.Palette.textPrimary)
                }
                if !skipped.isEmpty {
                    Text("Пропущено, такая категория уже есть: \(skipped.joined(separator: ", ")). Она осталась как была.")
                        .font(DS.Typography.body)
                        .foregroundStyle(DS.Palette.textSecondary)
                }
                Button("Открыть категории", action: onOpenCategories)
                    .buttonStyle(LimeButtonStyle())
                Button("Показать шаблоны") { Task { await model.reopen() } }
                    .buttonStyle(LimeButtonStyle(prominent: false))
            }
        }
        .accessibilityIdentifier("onboarding.templates.applied")
    }

    private var picker: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.md) {
            Text("Начните с шаблона")
                .font(DS.Typography.section)
                .foregroundStyle(DS.Palette.textPrimary)
            Text("Отметьте, что хотите отслеживать. Каждый шаблон станет обычной категорией: её можно переименовать, дополнить или удалить.")
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.textSecondary)
            if let asOf = model.offlineAsOf {
                OfflineBanner(updatedAt: asOf)
            }
            if let error = model.applyError {
                HStack(alignment: .top) {
                    Text(error)
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.danger)
                    Spacer()
                    Button("Скрыть") { model.dismissApplyError() }
                        .font(DS.Typography.caption)
                }
            }
            catalog
            Button(model.isApplying ? "Добавляем…" : "Добавить выбранное") { Task { await model.apply() } }
                .buttonStyle(LimeButtonStyle())
                .disabled(!model.canApply)
                .opacity(model.canApply ? 1 : 0.4)
            Button("Пропустить шаблоны") { model.dismiss() }
                .buttonStyle(LimeButtonStyle(prominent: false))
        }
    }

    @ViewBuilder
    private var catalog: some View {
        switch model.loadState {
        case .idle, .loading:
            ProgressView().tint(DS.Palette.lime).frame(maxWidth: .infinity, minHeight: 80)
        case .failure(let message):
            VStack(spacing: DS.Spacing.md) {
                Text(message)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textSecondary)
                    .multilineTextAlignment(.center)
                Button("Повторить") { Task { await model.load() } }
                    .buttonStyle(LimeButtonStyle())
                    .fixedSize()
            }
            .frame(maxWidth: .infinity)
        case .loaded where model.templates.isEmpty:
            Text("Шаблонов нет.")
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.textSecondary)
        case .loaded:
            ForEach(model.templates) { template in
                TemplateRow(template: template, isOn: model.selected.contains(template.key)) {
                    model.toggle(template.key)
                }
            }
        }
    }
}

private struct TemplateRow: View {
    let template: CategoryTemplateDTO
    let isOn: Bool
    let toggle: () -> Void

    var body: some View {
        Button(action: toggle) {
            HStack(alignment: .top, spacing: DS.Spacing.md) {
                Image(systemName: isOn ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 22))
                    .foregroundStyle(isOn ? DS.Palette.lime : DS.Palette.textDisabled)
                VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                    Text(template.name)
                        .font(DS.Typography.card)
                        .foregroundStyle(DS.Palette.textPrimary)
                    if let description = template.description, !description.isEmpty {
                        Text(description)
                            .font(DS.Typography.body)
                            .foregroundStyle(DS.Palette.textSecondary)
                    }
                    Text(template.fields.map(\.name).joined(separator: ", "))
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textDisabled)
                    if template.added {
                        Text("Уже добавлено")
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.textSecondary)
                            .padding(.horizontal, DS.Spacing.sm)
                            .padding(.vertical, DS.Spacing.xs)
                            .background(DS.Palette.surface, in: Capsule())
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(DS.Spacing.lg)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(DS.Palette.card, in: RoundedRectangle(cornerRadius: DS.Radius.control, style: .continuous))
            .opacity(template.added ? 0.6 : 1)
        }
        .buttonStyle(.plain)
        .disabled(template.added)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(isOn ? .isSelected : [])
        .accessibilityIdentifier("onboarding.template.\(template.key)")
    }
}

// MARK: - Voice builder

private struct OnboardingBuilderSection: View {
    @ObservedObject var model: OnboardingPlanModel
    let onOpenCategories: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.md) {
            Text("Опишите словами, что хотите отслеживать — получите план и создайте выбранное одним нажатием.")
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.textSecondary)
            TextEditor(text: $model.transcript)
                .scrollContentBackground(.hidden)
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.textPrimary)
                .frame(minHeight: 120)
                .padding(DS.Spacing.sm)
                .background(DS.Palette.card, in: RoundedRectangle(cornerRadius: DS.Radius.control, style: .continuous))
                .overlay(alignment: .topLeading) {
                    if model.transcript.isEmpty {
                        Text("Например: хочу трекать сон — сколько часов и качество")
                            .font(DS.Typography.body)
                            .foregroundStyle(DS.Palette.textDisabled)
                            .padding(DS.Spacing.md)
                            .allowsHitTesting(false)
                    }
                }
                .accessibilityLabel("Что отслеживать")
                .accessibilityIdentifier("onboarding.transcript")
            Button {
                Task { await model.generate() }
            } label: {
                Label("Сгенерировать план", systemImage: "sparkles")
            }
            .buttonStyle(LimeButtonStyle())
            .disabled(!model.canGenerate)
            .opacity(model.canGenerate ? 1 : 0.4)
            .accessibilityIdentifier("onboarding.generate")
            draft
        }
    }

    @ViewBuilder
    private var draft: some View {
        switch model.draft {
        case .idle:
            EmptyView()
        case .loading:
            NeonLoader(label: "Строим план").frame(height: 120)
        case .failure(let message):
            VStack(spacing: DS.Spacing.md) {
                Text(message)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.danger)
                    .multilineTextAlignment(.center)
                Button("Повторить") { Task { await model.generate() } }
                    .buttonStyle(LimeButtonStyle(prominent: false))
            }
        case .done(let plan):
            if plan.operations.isEmpty {
                Text("Модель не предложила изменений. Попробуйте описать подробнее.")
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textSecondary)
            } else {
                planPreview
            }
        }
    }

    private var planPreview: some View {
        VStack(spacing: DS.Spacing.md) {
            ForEach(Array(model.operations.enumerated()), id: \.offset) { index, op in
                OperationCard(op: op, state: model.opStates[index], position: index + 1,
                              onToggle: { model.setEnabled(index, $0) },
                              onName: { model.setName(index, $0) })
            }
            if let error = model.applyError {
                Text(error)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.danger)
            }
            Button(model.isApplying ? "Создаём…" : "Создать выбранное (\(model.enabledCount))") {
                Task {
                    await model.apply()
                    if model.didApply { onOpenCategories() }
                }
            }
            .buttonStyle(LimeButtonStyle())
            .disabled(!model.canApply)
            .opacity(model.canApply ? 1 : 0.4)
            .accessibilityIdentifier("onboarding.apply")
        }
    }
}

/// One planned operation: the switch, the editable name of a new category (or the position and
/// name of an added field), the conflict note, the display and streak modes, the fields.
private struct OperationCard: View {
    let op: OnboardingOperationDTO
    let state: OnboardingPlanModel.OpState
    let position: Int
    let onToggle: (Bool) -> Void
    let onName: (String) -> Void

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                Toggle(isOn: Binding(get: { state.enabled }, set: onToggle)) {
                    Text(heading)
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                }
                .tint(DS.Palette.lime)
                .accessibilityLabel(toggleLabel)
                switch op {
                case .createCategory(let create):
                    TextField("Имя категории", text: Binding(get: { state.name }, set: onName))
                        .font(DS.Typography.body)
                        .padding(DS.Spacing.md)
                        .background(DS.Palette.surface, in: RoundedRectangle(cornerRadius: DS.Radius.chip, style: .continuous))
                        .accessibilityLabel("Имя категории \(create.name)")
                    if create.nameConflict {
                        Label("имя уже занято", systemImage: "exclamationmark.triangle")
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.danger)
                    }
                    Text(modes(create))
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textDisabled)
                    fieldList(create.fields)
                case .addField(let add):
                    Text("\(position). \(add.field.name)")
                        .font(DS.Typography.card)
                        .foregroundStyle(DS.Palette.textPrimary)
                    fieldList([add.field])
                }
            }
        }
    }

    private var heading: String {
        switch op {
        case .createCategory: return "Новая категория"
        case .addField(let add): return "Поле в категории #\(add.categoryId)"
        }
    }

    private var toggleLabel: String {
        switch op {
        case .createCategory(let create): return "Создать категорию \(create.name)"
        case .addField(let add): return "Добавить поле \(add.field.name)"
        }
    }

    private func modes(_ create: CreateCategoryOpDTO) -> String {
        var parts = [create.displayMode, create.streakMode]
        if let group = create.group, !group.isEmpty { parts.append(group) }
        return parts.joined(separator: " · ")
    }

    private func fieldList(_ fields: [PlanFieldDTO]) -> some View {
        VStack(alignment: .leading, spacing: DS.Spacing.xs) {
            ForEach(Array(fields.enumerated()), id: \.offset) { _, field in
                Text(field.name + " · " + field.fieldType + (field.isRequired ? " · обязательное" : ""))
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
            }
        }
    }
}
