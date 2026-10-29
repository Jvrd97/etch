// [review:need-review] PHASE-01/266
// summary: Roles screen (More → Роли) — the summary for week/month/quarter with the Friday report and a copy button, today's share bar per role with the target always called a hypothesis, the acts of the day, the minutes form with its blocks (confirm an automatic one, remove), the act form, and a link to the markup rules; loading, error with retry, empty directory, offline note over a cached day; pull to refresh; no navigation stack of its own
import SwiftUI
import UIKit

struct RolesView: View {
    @StateObject private var viewModel: RolesViewModel

    /// No-argument init keeps `RootView` to one line: the model builds its client with `.live()`.
    init() {
        _viewModel = StateObject(wrappedValue: .live())
    }

    init(viewModel: RolesViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        VStack(spacing: 0) {
            if let asOf = viewModel.offlineAsOf {
                OfflineBanner(updatedAt: asOf)
            }
            content
        }
        .navigationTitle(MoreDestination.roles.title)
        .dsScreenBackground()
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                NavigationLink {
                    RoleRulesView()
                } label: {
                    Image(systemName: "slider.horizontal.3")
                }
                .accessibilityLabel("Правила разметки")
                .accessibilityIdentifier("roles.rules")
            }
        }
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
            if let day = viewModel.day, !viewModel.roles.isEmpty {
                loaded(day)
            } else {
                DSEmptyState(
                    title: "Ролей нет", systemImage: "person.2", message: RolesFormat.emptyDirectoryText
                )
            }
        }
    }

    private func loaded(_ day: RoleDayDTO) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DS.Spacing.xl) {
                if let message = viewModel.errorMessage {
                    Text(message)
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.warning)
                        .accessibilityIdentifier("roles.error")
                }
                RoleSummaryCard(viewModel: viewModel)
                RoleDayCard(day: day)
                RoleActsCard(day: day)
                RoleMinutesCard(viewModel: viewModel, day: day)
                RoleActFormCard(viewModel: viewModel)
            }
            .padding(DS.Spacing.lg)
        }
        .refreshable { await viewModel.refresh() }
    }
}

// MARK: - Shared bits

struct RolesCardTitle: View {
    let text: String

    var body: some View {
        Text(text)
            .font(DS.Typography.card)
            .foregroundStyle(DS.Palette.textPrimary)
    }
}

struct RolesSecondaryText: View {
    let text: String
    var color: Color = DS.Palette.textSecondary

    init(_ text: String, color: Color = DS.Palette.textSecondary) {
        self.text = text
        self.color = color
    }

    var body: some View {
        Text(text)
            .font(DS.Typography.caption)
            .foregroundStyle(color)
            .fixedSize(horizontal: false, vertical: true)
    }
}

struct RolesShareBar: View {
    let percent: Int

    var body: some View {
        GeometryReader { proxy in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.white.opacity(0.06))
                Capsule()
                    .fill(DS.Palette.lime)
                    .frame(width: proxy.size.width * CGFloat(min(max(percent, 0), 100)) / 100)
            }
        }
        .frame(height: 6)
        .accessibilityHidden(true)
    }
}

// MARK: - Summary

private struct RoleSummaryCard: View {
    @ObservedObject var viewModel: RolesViewModel
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.md) {
            Picker("Период", selection: Binding(
                get: { viewModel.period },
                set: { period in Task { await viewModel.select(period: period) } }
            )) {
                ForEach(RolesFormat.Period.allCases) { Text($0.label).tag($0) }
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("roles.period")

            if let summary = viewModel.summary {
                Card { content(summary) }
            }
        }
    }

    private func content(_ summary: RoleSummaryDTO) -> some View {
        VStack(alignment: .leading, spacing: DS.Spacing.md) {
            HStack(alignment: .firstTextBaseline) {
                RolesCardTitle(text: "Роли за период")
                Spacer()
                RolesSecondaryText("\(summary.dateFrom) — \(summary.dateTo)")
            }
            if summary.totalMinutes == 0 {
                Text(RolesFormat.summaryEmptyText)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textSecondary)
            } else {
                ForEach(RolesFormat.workingRoles(summary), id: \.roleId) { slice in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(slice.title)
                            .font(DS.Typography.body)
                            .foregroundStyle(DS.Palette.textPrimary)
                        RolesSecondaryText(RolesFormat.summaryRowLine(slice))
                        let acts = RolesFormat.actsText(slice)
                        if !acts.isEmpty {
                            RolesSecondaryText("акты: \(slice.actTotal) — \(acts)", color: DS.Palette.textDisabled)
                        }
                    }
                }
                RolesSecondaryText(RolesFormat.summaryTargetNote, color: DS.Palette.textDisabled)
                unassigned(summary)
                report(summary)
            }
        }
    }

    private func unassigned(_ summary: RoleSummaryDTO) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(RolesFormat.unassignedTitle)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textPrimary)
                Spacer()
                RolesSecondaryText("\(RolesFormat.summaryMinutes(summary.unassignedMinutes)) · \(summary.unassignedSharePct)%")
            }
            RolesSecondaryText(
                RolesFormat.unassignedNote(summary),
                color: summary.rulesLag ? DS.Palette.warning : DS.Palette.textDisabled
            )
        }
        .padding(DS.Spacing.md)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: DS.Radius.chip, style: .continuous)
                .fill(DS.Palette.surface)
        )
        .overlay(
            RoundedRectangle(cornerRadius: DS.Radius.chip, style: .continuous)
                .stroke(summary.rulesLag ? DS.Palette.warning.opacity(0.4) : .clear, lineWidth: 1)
        )
    }

    private func report(_ summary: RoleSummaryDTO) -> some View {
        VStack(alignment: .leading, spacing: DS.Spacing.sm) {
            Divider().overlay(DS.Palette.cardStroke)
            HStack {
                RolesSecondaryText("Пятничный отчёт")
                Spacer()
                Button {
                    UIPasteboard.general.string = summary.markdown
                    copied = true
                } label: {
                    Label(copied ? "Скопировано" : "Скопировать", systemImage: "doc.on.doc")
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.lime)
                }
                .accessibilityIdentifier("roles.copy-report")
            }
            Text(summary.markdown)
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(DS.Palette.textSecondary)
                .textSelection(.enabled)
        }
        .onChange(of: summary.markdown) { _, _ in copied = false }
    }
}

// MARK: - Day

private struct RoleDayCard: View {
    let day: RoleDayDTO

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                HStack(alignment: .firstTextBaseline) {
                    RolesCardTitle(text: "Роли · \(day.workDay)")
                    Spacer()
                    RolesSecondaryText("всего \(RolesFormat.minutes(day.totalMinutes))")
                }
                RolesSecondaryText(RolesFormat.actsSummary(day))
                if let line = RolesFormat.unassignedLine(day) {
                    RolesSecondaryText(line, color: DS.Palette.warning)
                }
                if day.totalMinutes == 0 {
                    Text(RolesFormat.noMinutesText)
                        .font(DS.Typography.body)
                        .foregroundStyle(DS.Palette.textSecondary)
                } else {
                    ForEach(day.roles, id: \.roleCode) { slice in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack(alignment: .firstTextBaseline) {
                                Text(slice.title)
                                    .font(DS.Typography.body)
                                    .foregroundStyle(DS.Palette.textPrimary)
                                Spacer()
                                RolesSecondaryText("\(RolesFormat.minutes(slice.minutes)) · \(slice.sharePct)%")
                            }
                            RolesShareBar(percent: slice.sharePct)
                            if let target = RolesFormat.targetShareLine(slice) {
                                RolesSecondaryText(target)
                            }
                        }
                    }
                }
            }
        }
        .accessibilityIdentifier("roles.day")
    }
}

private struct RoleActsCard: View {
    let day: RoleDayDTO

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.sm) {
                RolesCardTitle(text: "Акты дня")
                if day.acts.isEmpty {
                    Text(RolesFormat.noActsText)
                        .font(DS.Typography.body)
                        .foregroundStyle(DS.Palette.textSecondary)
                } else {
                    ForEach(day.acts) { act in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(RolesFormat.actLine(act) + (act.isManual ? " · \(RolesFormat.manualMark)" : ""))
                                .font(DS.Typography.body)
                                .foregroundStyle(DS.Palette.textPrimary)
                            if let source = RolesFormat.fromPlanLine(act) {
                                RolesSecondaryText(source)
                            }
                        }
                    }
                }
            }
        }
    }
}

// MARK: - Forms

private struct RoleMinutesCard: View {
    @ObservedObject var viewModel: RolesViewModel
    let day: RoleDayDTO
    @State private var roleCode = ""
    @State private var minutes = String(RolesFormat.defaultMinutes)
    @State private var note = ""

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                RolesCardTitle(text: "Записать минуты")
                RolePicker(title: "Роль", roles: viewModel.roles, selection: $roleCode)
                RoleField(title: "Минуты", placeholder: "90", text: $minutes, numeric: true)
                    .accessibilityIdentifier("roles.minutes")
                RoleField(title: "Чем занимался", placeholder: "найм", text: $note)
                Button("Записать") {
                    Task {
                        if await viewModel.addMinutes(
                            roleCode: roleCode, minutes: Int(minutes) ?? 0, note: note
                        ) {
                            note = ""
                        }
                    }
                }
                .buttonStyle(LimeButtonStyle())
                .disabled(viewModel.isSaving)
                .accessibilityIdentifier("roles.minutes.submit")

                ForEach(day.blocks) { block in blockRow(block) }
            }
        }
        .onAppear { if roleCode.isEmpty { roleCode = viewModel.roles.first?.code ?? "" } }
    }

    private func blockRow(_ block: RoleTimeBlockDTO) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(RolesFormat.blockLine(block))
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.textPrimary)
            if let markup = RolesFormat.markupSource(block) {
                RolesSecondaryText(markup)
            }
            HStack(spacing: DS.Spacing.lg) {
                if RolesFormat.canConfirm(block) {
                    Button(RolesFormat.confirmLabel) { Task { await viewModel.confirmBlock(id: block.id) } }
                        .accessibilityIdentifier("roles.block.confirm.\(block.id)")
                }
                Button("убрать", role: .destructive) { Task { await viewModel.removeBlock(id: block.id) } }
                    .accessibilityIdentifier("roles.block.remove.\(block.id)")
            }
            .font(DS.Typography.caption)
            .disabled(viewModel.isSaving)
        }
    }
}

private struct RoleActFormCard: View {
    @ObservedObject var viewModel: RolesViewModel
    @State private var roleCode = ""
    @State private var kind = RolesFormat.actKinds[0].id
    @State private var title = ""

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                RolesCardTitle(text: "Записать акт роли")
                RolePicker(title: "Роль", roles: viewModel.roles, selection: $roleCode)
                HStack {
                    RolesSecondaryText("Вид акта")
                    Spacer()
                    Picker("Вид акта", selection: $kind) {
                        ForEach(RolesFormat.actKinds, id: \.id) { Text($0.label).tag($0.id) }
                    }
                    .pickerStyle(.menu)
                    .tint(DS.Palette.lime)
                }
                RoleField(title: "Что это было", placeholder: "ADR-0020", text: $title)
                    .accessibilityIdentifier("roles.act.title")
                Button("Записать акт") {
                    Task {
                        if await viewModel.addAct(roleCode: roleCode, actKind: kind, title: title) {
                            title = ""
                        }
                    }
                }
                .buttonStyle(LimeButtonStyle())
                .disabled(viewModel.isSaving || title.trimmingCharacters(in: .whitespaces).isEmpty)
                .accessibilityIdentifier("roles.act.submit")
            }
        }
        .onAppear { if roleCode.isEmpty { roleCode = viewModel.roles.first?.code ?? "" } }
    }
}

struct RolePicker: View {
    let title: String
    let roles: [RoleDTO]
    @Binding var selection: String

    var body: some View {
        HStack {
            RolesSecondaryText(title)
            Spacer()
            Picker(title, selection: $selection) {
                ForEach(roles) { Text($0.title).tag($0.code) }
            }
            .pickerStyle(.menu)
            .tint(DS.Palette.lime)
        }
    }
}

struct RoleField: View {
    let title: String
    let placeholder: String
    @Binding var text: String
    var numeric = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            RolesSecondaryText(title)
            TextField(placeholder, text: $text)
                .keyboardType(numeric ? .numberPad : .default)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.textPrimary)
                .padding(DS.Spacing.md)
                .background(
                    RoundedRectangle(cornerRadius: DS.Radius.chip, style: .continuous)
                        .fill(DS.Palette.surface)
                )
        }
    }
}
