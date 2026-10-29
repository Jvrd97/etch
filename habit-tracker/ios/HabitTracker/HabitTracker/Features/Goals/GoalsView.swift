// [review:need-review] PHASE-01/216
// summary: the Goals screen under More, drawn as /m/goals draws it — levels 0-5 with the «⚠ подтверди» lines apart from the prose, milestones with status, close date, a Закрыть/Открыть button and «Открывается чем» chips, and the goals of the current quarter; offline banner over a cached board
import SwiftUI

struct GoalsView: View {
    @StateObject private var viewModel: GoalsViewModel

    init() {
        _viewModel = StateObject(wrappedValue: .live())
    }

    init(viewModel: GoalsViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        content
            .navigationTitle(MoreDestination.goals.title)
            .dsScreenBackground()
            .task { await viewModel.load() }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .idle, .loading:
            NeonLoader(label: "Loading")
        case .failure(let message):
            DSErrorState(message: message) { Task { await viewModel.load() } }
        case .loaded:
            ScrollView {
                VStack(alignment: .leading, spacing: DS.Spacing.lg) {
                    if let offlineAsOf = viewModel.offlineAsOf {
                        OfflineBanner(updatedAt: offlineAsOf)
                    }
                    if let message = viewModel.errorMessage {
                        Text(message)
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.danger)
                    }
                    if let board = viewModel.board, !viewModel.isEmpty {
                        levels(board.levels)
                        milestones(board.milestones)
                        quarter(board)
                    } else {
                        Card {
                            Text(GoalsFormat.emptyText)
                                .font(DS.Typography.body)
                                .foregroundStyle(DS.Palette.textSecondary)
                        }
                    }
                }
                .padding(DS.Spacing.lg)
            }
            .refreshable { await viewModel.load() }
        }
    }

    private func levels(_ levels: [GoalLevelDTO]) -> some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.lg) {
                sectionTitle("Уровни")
                ForEach(levels) { level in
                    VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                        Text("Уровень \(level.level) — \(GoalsFormat.plain(level.title))")
                            .font(DS.Typography.body.weight(.semibold))
                            .foregroundStyle(DS.Palette.textPrimary)
                        if !level.bodyMd.isEmpty {
                            secondary(GoalsFormat.plain(level.bodyMd))
                        }
                        ForEach(level.openQuestions, id: \.self) { question in
                            Text(question)
                                .font(DS.Typography.caption)
                                .foregroundStyle(DS.Palette.warning)
                        }
                    }
                }
            }
        }
    }

    private func milestones(_ milestones: [MilestoneDTO]) -> some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                sectionTitle("Милстоны")
                ForEach(milestones) { milestone in
                    if milestone.code != milestones.first?.code {
                        Divider().overlay(DS.Palette.cardStroke)
                    }
                    milestoneRow(milestone)
                }
            }
        }
    }

    private func milestoneRow(_ milestone: MilestoneDTO) -> some View {
        VStack(alignment: .leading, spacing: DS.Spacing.sm) {
            HStack(alignment: .top, spacing: DS.Spacing.md) {
                VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                    Text("\(milestone.code) · \(GoalsFormat.plain(milestone.title))")
                        .font(DS.Typography.body)
                        .foregroundStyle(DS.Palette.textPrimary)
                    if let criterion = milestone.doneCriterion {
                        secondary("Сделано :: \(GoalsFormat.plain(criterion))")
                    }
                    if let when = milestone.whenText {
                        secondary("Когда :: \(GoalsFormat.plain(when))")
                    }
                }
                Spacer(minLength: 0)
                VStack(alignment: .trailing, spacing: DS.Spacing.xs) {
                    secondary(GoalsFormat.statusLine(milestone))
                    Button(GoalsFormat.actionTitle(for: milestone.status)) {
                        Task { await viewModel.toggle(milestone.code) }
                    }
                    .font(DS.Typography.caption)
                    .buttonStyle(.bordered)
                    .tint(milestone.status == .done ? DS.Palette.textSecondary : DS.Palette.lime)
                    .disabled(viewModel.saving.contains(milestone.code))
                }
            }
            dependencyChips(milestone)
        }
    }

    @ViewBuilder
    private func dependencyChips(_ milestone: MilestoneDTO) -> some View {
        let chips = viewModel.dependencies(of: milestone)
        if chips.isEmpty {
            secondary(GoalsFormat.unblockedText)
        } else {
            HStack(spacing: DS.Spacing.sm) {
                ForEach(chips) { chip in
                    Text(chip.text)
                        .font(DS.Typography.caption)
                        .foregroundStyle(chip.isOpened ? DS.Palette.success : DS.Palette.textSecondary)
                        .padding(.horizontal, DS.Spacing.sm)
                        .padding(.vertical, DS.Spacing.xs)
                        .overlay(
                            RoundedRectangle(cornerRadius: DS.Radius.chip)
                                .stroke(chip.isOpened ? DS.Palette.success.opacity(0.4) : DS.Palette.cardStroke)
                        )
                }
            }
        }
    }

    private func quarter(_ board: GoalsBoardDTO) -> some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.sm) {
                sectionTitle("Квартал \(board.quarter)")
                ForEach(board.goals) { goal in
                    HStack(alignment: .firstTextBaseline, spacing: DS.Spacing.xs) {
                        Text("\(goal.ord). \(GoalsFormat.plain(goal.textMd))")
                            .font(DS.Typography.body)
                            .foregroundStyle(DS.Palette.textPrimary)
                        if let code = goal.milestoneCode {
                            secondary("— \(code)")
                        }
                    }
                }
            }
        }
    }

    private func sectionTitle(_ title: String) -> some View {
        Text(title)
            .font(DS.Typography.card)
            .foregroundStyle(DS.Palette.textPrimary)
    }

    private func secondary(_ text: String) -> some View {
        Text(text)
            .font(DS.Typography.caption)
            .foregroundStyle(DS.Palette.textSecondary)
    }
}
