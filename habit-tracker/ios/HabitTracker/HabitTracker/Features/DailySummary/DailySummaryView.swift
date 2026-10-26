// [review:need-review] PHASE-01/213, PHASE-01/208
// summary: day-summary screen — speak or type the day, parse it into a draft, review it with every row switchable, then write the checked part; no NavigationStack of its own, init() takes no required arguments so RootView is unchanged
import SwiftUI

struct DailySummaryView: View {
    @StateObject private var viewModel: DailySummaryViewModel
    @FocusState private var textFocused: Bool

    init(onApplied: @escaping () -> Void = {}) {
        _viewModel = StateObject(wrappedValue: .live(onApplied: onApplied))
    }

    init(viewModel: DailySummaryViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DS.Spacing.lg) {
                if viewModel.applyState == .applied {
                    appliedCard
                } else {
                    dictationControls
                    transcriptField
                    draftSection
                }
            }
            .padding(DS.Spacing.lg)
        }
        .scrollDismissesKeyboard(.interactively)
        .navigationTitle("Рассказать день")
        .navigationBarTitleDisplayMode(.inline)
        .dsScreenBackground()
        .task { await viewModel.loadCategories() }
        .onDisappear { viewModel.stopDictation() }
    }

    // MARK: - Dictation

    private var dictationControls: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.sm) {
            Button {
                textFocused = false
                Task { await viewModel.toggleDictation() }
            } label: {
                Label(
                    viewModel.isListening ? "Слушаю, остановить" : "Говорить",
                    systemImage: viewModel.isListening ? "stop.fill" : "mic.fill"
                )
            }
            .buttonStyle(LimeButtonStyle(prominent: !viewModel.isListening))
            .frame(minHeight: 44)
            .accessibilityIdentifier("dailySummary.dictate")

            if let message = viewModel.speechMessage {
                Text(message)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.warning)
                    .accessibilityIdentifier("dailySummary.speechMessage")
            }
        }
    }

    private var transcriptField: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.sm) {
            Text("Что было за день")
                .font(DS.Typography.caption)
                .foregroundStyle(DS.Palette.textSecondary)
            ZStack(alignment: .topLeading) {
                TextEditor(text: $viewModel.transcript)
                    .focused($textFocused)
                    .scrollContentBackground(.hidden)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textPrimary)
                    .frame(minHeight: 140)
                    .padding(DS.Spacing.sm)
                    .accessibilityIdentifier("dailySummary.transcript")
                if viewModel.transcript.isEmpty {
                    Text("Например: съел борщ и котлету, отжался 30 раз")
                        .font(DS.Typography.body)
                        .foregroundStyle(DS.Palette.textDisabled)
                        .padding(.horizontal, DS.Spacing.md)
                        .padding(.vertical, DS.Spacing.md + 2)
                        .allowsHitTesting(false)
                }
            }
            .background(DS.Palette.surface)
            .clipShape(RoundedRectangle(cornerRadius: DS.Radius.control, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: DS.Radius.control, style: .continuous)
                    .stroke(DS.Palette.cardStroke, lineWidth: 1)
            )
            if !viewModel.interim.isEmpty {
                Text(viewModel.interim)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textDisabled)
                    .accessibilityIdentifier("dailySummary.interim")
            }
        }
    }

    // MARK: - Draft and apply

    @ViewBuilder
    private var draftSection: some View {
        switch viewModel.draftState {
        case .idle:
            parseButton("Разобрать день")
        case .loading:
            ProgressView("Разбираю день")
                .tint(DS.Palette.lime)
                .frame(maxWidth: .infinity)
        case .failure(let message):
            Text(message)
                .font(DS.Typography.caption)
                .foregroundStyle(DS.Palette.danger)
                .accessibilityIdentifier("dailySummary.draftError")
            parseButton("Разобрать день")
        case .done(let plan):
            if plan.isEmpty {
                Text("Модель не нашла в тексте ничего для записи. Расскажите подробнее.")
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textSecondary)
                parseButton("Разобрать день")
            } else {
                DayPlanPreview(plan: plan, viewModel: viewModel)
                applyControls
                parseButton("Пересобрать план", prominent: false)
            }
        }
    }

    private func parseButton(_ title: String, prominent: Bool = true) -> some View {
        Button(title) {
            textFocused = false
            Task { await viewModel.generate() }
        }
        .buttonStyle(LimeButtonStyle(prominent: prominent))
        .frame(minHeight: 44)
        .disabled(!viewModel.canGenerate)
        .opacity(viewModel.canGenerate ? 1 : 0.4)
        .accessibilityIdentifier("dailySummary.parse")
    }

    @ViewBuilder
    private var applyControls: some View {
        if case .failure(let message) = viewModel.applyState {
            Text(message)
                .font(DS.Typography.caption)
                .foregroundStyle(DS.Palette.danger)
                .accessibilityIdentifier("dailySummary.applyError")
        }
        Button(viewModel.applyState == .applying ? "Записываю" : "Записать (\(viewModel.enabledCount))") {
            Task { await viewModel.apply() }
        }
        .buttonStyle(LimeButtonStyle())
        .frame(minHeight: 44)
        .disabled(!viewModel.canApply)
        .opacity(viewModel.canApply ? 1 : 0.4)
        .accessibilityIdentifier("dailySummary.apply")
    }

    private var appliedCard: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                Label("День записан", systemImage: "checkmark.circle.fill")
                    .font(DS.Typography.section)
                    .foregroundStyle(DS.Palette.success)
                Button("Рассказать ещё") { viewModel.reset() }
                    .buttonStyle(LimeButtonStyle(prominent: false))
                    .frame(minHeight: 44)
                    .accessibilityIdentifier("dailySummary.again")
            }
        }
    }
}

/// The button Today shows: opens the screen above in a sheet, closes it once the day is written,
/// and tells Today to read the day again.
struct VoiceDayButton: View {
    var onApplied: () -> Void = {}
    @State private var isPresented = false

    var body: some View {
        Button {
            isPresented = true
        } label: {
            Label("Рассказать день", systemImage: "mic.fill")
        }
        .buttonStyle(LimeButtonStyle(prominent: false))
        .frame(minHeight: 44)
        .accessibilityIdentifier("today.voiceDay")
        .sheet(isPresented: $isPresented) {
            NavigationStack {
                DailySummaryView(onApplied: {
                    isPresented = false
                    onApplied()
                })
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Закрыть") { isPresented = false }
                    }
                }
            }
        }
    }
}
