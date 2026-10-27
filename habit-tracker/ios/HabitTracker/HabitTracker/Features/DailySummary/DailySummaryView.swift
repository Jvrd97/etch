// [review:need-review] PHASE-01/213, PHASE-01/208, PHASE-03/227, PHASE-03/230, PHASE-03/250
// summary: day-summary screen — pick the day (today by default, the project's chevron navigator), speak or type it, parse it into a draft (cancellable), review it with every row switchable, then write the checked part; dictation stops when the app leaves the foreground; the screen cannot be left over an unconfirmed write without asking (the sheet: Close button, swipe off; the pushed page: own Back button, swipe back off); an already-applied key (409) ends in a card, not a dead retry button; no NavigationStack of its own, init() takes no required arguments; the Today sheet hands Today a callback on every dismissal (applied, 409 or Close) so it reads the day again; on the More stack a retainer keeps a model with an unconfirmed write across a pop the system makes on its own, and the screen tells the root it must not be popped, each instance under its own token (#230, #250); the retainer adopts the model the screen shows and lets it go after an ordinary exit; the two-finger escape asks like the screen's own Back; the Today sheet hands Today its callback only when the sheet sent a write, so a plain Close leaves Today as it was (#250)
import SwiftUI

/// The page pushed from More. It owns its view model, so leaving it drops the idempotency key of a
/// write that may have landed: Back (and the swipe, which goes with the hidden button) asks first.
struct DailySummaryView: View {
    @StateObject private var viewModel: DailySummaryViewModel
    @Environment(\.dismiss) private var dismiss
    @Environment(\.moreLeaveHold) private var leaveHold
    @State private var asksToLeave = false
    /// This instance's name in the root's set of holders: an old instance going away cannot lift the hold of a new one.
    @State private var holdToken = UUID()
    private let retainer: DailySummaryRetainer?

    /// A page that owns its model for good: leaving it, however it happens, ends the model.
    init(onApplied: @escaping () -> Void = {}) {
        retainer = nil
        _viewModel = StateObject(wrappedValue: .live(onApplied: onApplied))
    }

    /// With a retainer the model outlives a pop the system makes on its own (see `AppNavigation`).
    /// The retainer builds the model, so what happens when the day is written is the retainer's `make`.
    init(retainer: DailySummaryRetainer) {
        self.retainer = retainer
        _viewModel = StateObject(wrappedValue: retainer.model())
    }

    var body: some View {
        DailySummaryContent(viewModel: viewModel)
            .navigationBarBackButtonHidden(viewModel.closeNeedsConfirmation)
            .toolbar {
                if viewModel.closeNeedsConfirmation {
                    ToolbarItem(placement: .topBarLeading) {
                        Button { asksToLeave = true } label: {
                            Label("Назад", systemImage: "chevron.backward")
                        }
                        .accessibilityIdentifier("dailySummary.back")
                    }
                }
            }
            .holdsMoreScreen(viewModel.closeNeedsConfirmation, token: holdToken)
            // The two-finger Z gesture pops a pushed page; with the page's own Back standing in for
            // the system one it must ask the same question.
            .accessibilityAction(.escape) {
                if viewModel.closeNeedsConfirmation { asksToLeave = true } else { dismiss() }
            }
            .onAppear { retainer?.adopt(viewModel) }
            .onDisappear { retainer?.screenLeft(viewModel) }
            .unconfirmedWriteDialog(isPresented: $asksToLeave, leaveTitle: "Выйти без проверки") {
                // The person chose this: let the stack pop, and let the next visit start clean.
                leaveHold.release(holdToken)
                retainer?.release()
                dismiss()
            }
    }
}

/// The screen itself, for whoever owns the view model.
struct DailySummaryContent: View {
    @ObservedObject var viewModel: DailySummaryViewModel
    @FocusState private var textFocused: Bool
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DS.Spacing.lg) {
                if viewModel.applyState.isWritten {
                    appliedCard
                } else {
                    dayNavigator
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
        .onDisappear {
            viewModel.stopDictation()
            viewModel.cancelDraft()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase != .active { viewModel.stopDictationForBackground() }
        }
    }

    // MARK: - Day

    private var dayNavigator: some View {
        HStack {
            Button { viewModel.showPreviousDay() } label: {
                Image(systemName: "chevron.left").frame(minWidth: 44, minHeight: 44)
            }
            .disabled(!viewModel.canChangeDay)
            .accessibilityLabel("Предыдущий день")
            Spacer()
            VStack(spacing: DS.Spacing.xs) {
                Text(DayFormat.title(of: viewModel.entryDate))
                    .font(DS.Typography.card)
                    .foregroundStyle(DS.Palette.textPrimary)
                if !viewModel.isToday {
                    Button("Сегодня") { viewModel.showToday() }
                        .font(DS.Typography.caption)
                        .disabled(!viewModel.canChangeDay)
                }
            }
            Spacer()
            Button { viewModel.showNextDay() } label: {
                Image(systemName: "chevron.right").frame(minWidth: 44, minHeight: 44)
            }
            .disabled(!viewModel.canShowNextDay)
            .accessibilityLabel("Следующий день")
        }
        .foregroundStyle(DS.Palette.lime)
        .opacity(viewModel.canChangeDay ? 1 : 0.5)
        .accessibilityIdentifier("dailySummary.day")
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
            VStack(spacing: DS.Spacing.md) {
                ProgressView("Разбираю день")
                    .tint(DS.Palette.lime)
                Button("Отменить") { viewModel.cancelDraft() }
                    .buttonStyle(LimeButtonStyle(prominent: false))
                    .frame(minHeight: 44)
                    .accessibilityIdentifier("dailySummary.cancelDraft")
            }
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
        Button(applyTitle) {
            Task { await viewModel.apply() }
        }
        .buttonStyle(LimeButtonStyle())
        .frame(minHeight: 44)
        .disabled(!viewModel.canApply)
        .opacity(viewModel.canApply ? 1 : 0.4)
        .accessibilityIdentifier("dailySummary.apply")
    }

    private var applyTitle: String {
        if viewModel.applyState == .applying { return "Записываю" }
        let verb = viewModel.applyIsUnconfirmed ? "Повторить запись" : "Записать"
        return "\(verb) (\(viewModel.enabledCount))"
    }

    private var appliedCard: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                Label(
                    viewModel.applyState == .alreadyApplied ? "Запись по этому плану уже прошла" : "День записан",
                    systemImage: "checkmark.circle.fill"
                )
                .font(DS.Typography.section)
                .foregroundStyle(DS.Palette.success)
                if viewModel.applyState == .alreadyApplied {
                    Text("Сервер уже принял этот план под тем же ключом, то есть день записан. Проверьте записи за день.")
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                        .accessibilityIdentifier("dailySummary.alreadyApplied")
                }
                Button("Рассказать ещё") { viewModel.reset() }
                    .buttonStyle(LimeButtonStyle(prominent: false))
                    .frame(minHeight: 44)
                    .accessibilityIdentifier("dailySummary.again")
            }
        }
    }
}

/// The button Today shows: opens the screen above in a sheet and closes it once the day is written.
/// Today is told when the sheet goes away only if the sheet sent a write — after the write, after a
/// 409 (the day already holds the plan, but the sheet only says so), or after a Close that left a
/// write of unknown outcome behind. A sheet closed without one changed nothing: reading the day again
/// would swap Today for its loader and lose the scroll for no reason.
struct VoiceDayButton: View {
    var onDismiss: () -> Void = {}
    @State private var isPresented = false
    @State private var model: DailySummaryViewModel?

    var body: some View {
        Button {
            model = .live(onApplied: { isPresented = false })
            isPresented = true
        } label: {
            Label("Рассказать день", systemImage: "mic.fill")
        }
        .buttonStyle(LimeButtonStyle(prominent: false))
        .frame(minHeight: 44)
        .accessibilityIdentifier("today.voiceDay")
        .sheet(isPresented: $isPresented, onDismiss: sheetDismissed) {
            if let model {
                VoiceDaySheet(viewModel: model, close: { isPresented = false })
            }
        }
    }

    private func sheetDismissed() {
        let sentAWrite = model?.mayHaveChangedTheDay ?? false
        model = nil
        if sentAWrite { onDismiss() }
    }
}

/// The sheet knows from the view model when closing would lose the key of a write that may
/// have landed. A swipe cannot be intercepted to ask, so it is switched off for that case and the
/// Close button asks instead.
private struct VoiceDaySheet: View {
    @ObservedObject var viewModel: DailySummaryViewModel
    @State private var asksToClose = false
    let close: () -> Void

    var body: some View {
        NavigationStack {
            DailySummaryContent(viewModel: viewModel)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Закрыть") {
                            if viewModel.closeNeedsConfirmation { asksToClose = true } else { close() }
                        }
                        .accessibilityIdentifier("dailySummary.close")
                    }
                }
        }
        .interactiveDismissDisabled(viewModel.closeNeedsConfirmation)
        .unconfirmedWriteDialog(isPresented: $asksToClose, leaveTitle: "Закрыть без проверки") { close() }
    }
}

private extension View {
    /// Leaving drops the key of a write that may have landed: the next retelling would write the
    /// day a second time.
    func unconfirmedWriteDialog(
        isPresented: Binding<Bool>, leaveTitle: String, leave: @escaping () -> Void
    ) -> some View {
        confirmationDialog("Запись не подтверждена", isPresented: isPresented, titleVisibility: .visible) {
            Button(leaveTitle, role: .destructive, action: leave)
            Button("Остаться", role: .cancel) {}
        } message: {
            Text("Запись могла пройти. Если выйти и рассказать день снова, он запишется второй раз. Сначала проверьте записи за день.")
        }
    }
}
