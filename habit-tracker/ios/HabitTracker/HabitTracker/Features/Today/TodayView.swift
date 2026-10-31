// [review:need-review] PHASE-01/32-ios-lime-tech-design-pass, PHASE-01/38-ios-avoid-streaks, PHASE-01/11-ios-read-cache, PHASE-01/12-ios-offline-queue, PHASE-01/208, PHASE-01/210, PHASE-01/213, PHASE-03/227, PHASE-03/225, PHASE-03/263, PHASE-03/294
// summary: PHASE-03/294 round 3 — the plus is never disabled (a switched-off button hands its touch to the card and the second tap of a quick double press opened the form), a ticked box shows «сделано» and a second tap writes nothing, the row body is one VoiceOver button
// summary: PHASE-03/294 — the plus of a habit row is its own button (adds the step, ticks the box, or opens the one-field sheet) and the row body still opens the form; «Когда?» on an avoid card records a relapse on a chosen day
// summary: PHASE-03/263 — the empty screen shows the refresh failure line
// summary: Today screen — quick-mark buttons first (they take over the legacy cards of their categories), avoid streak cards with a one-tap Happened that leads to the relapse history, habit cards with the quick-entry sheet, a card opens the day's sets and records; offline banner atop when data came from the read cache, and the shared offline-queue strip (waiting and not-sent writes of every screen)
import SwiftUI

/// What a card of Today opened: the day of one category — its sets (when a button answers for it)
/// and its records. The category is nil for a button whose category is not an active one: there are
/// sets to show and no category to add a record to.
struct DaySheetTarget: Identifiable {
    let categoryID: Int
    let title: String
    let category: CategoryDTO?
    let mark: QuickMarkDTO?

    var id: Int { categoryID }
}

struct TodayView: View {
    @StateObject private var viewModel: TodayViewModel
    @StateObject private var quickMarks: QuickMarksViewModel
    @State private var selectedCategory: CategoryDTO?
    @State private var daySheet: DaySheetTarget?
    @State private var detailsCategory: CategoryDTO?
    @State private var fieldCategory: CategoryDTO?
    @State private var whenCategory: CategoryDTO?

    init(viewModel: TodayViewModel, quickMarks: QuickMarksViewModel? = nil) {
        _viewModel = StateObject(wrappedValue: viewModel)
        _quickMarks = StateObject(wrappedValue: quickMarks ?? .live())
    }

    var body: some View {
        VStack(spacing: 0) {
            if let offlineAsOf = viewModel.offlineAsOf {
                OfflineBanner(updatedAt: offlineAsOf)
            }
            OutboxQueueBar(queue: OutboxLive.shared)
            content
        }
        .navigationTitle("Today")
        .dsScreenBackground()
        .task {
            // A tap or an undo moved the day of a category: read its records and streak again.
            quickMarks.onDayChanged = { [weak viewModel] categoryID in
                Task { await viewModel?.reloadAfterMark(categoryID: categoryID) }
            }
            await reload()
        }
        .sheet(item: $selectedCategory) { category in
            QuickEntrySheet(category: category, viewModel: viewModel)
        }
        .sheet(item: $daySheet) { target in
            TodayDaySheet(target: target, viewModel: viewModel, quickMarks: quickMarks)
        }
        .sheet(item: $detailsCategory) { category in
            RelapseDetailsSheet(category: category, viewModel: viewModel)
        }
        .sheet(item: $fieldCategory) { category in
            QuickFieldSheet(category: category, viewModel: viewModel)
        }
        .sheet(item: $whenCategory) { category in
            RelapseWhenSheet(category: category, viewModel: viewModel)
        }
    }

    private func reload() async {
        async let today: Void = viewModel.load()
        async let marks: Void = quickMarks.load()
        _ = await (today, marks)
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .idle, .loading:
            NeonLoader(label: "Loading")
        case .failure(let message):
            DSErrorState(message: message) {
                Task { await reload() }
            }
        case .loaded:
            categoryList
        }
    }

    /// Avoid categories get the streak card, a category a button answers for loses its legacy
    /// card (two ways to add to one field on one screen is one too many), checklist categories keep
    /// theirs.
    private var plainCategories: [CategoryDTO] {
        let covered = quickMarks.coveredCategoryIDs
        return viewModel.categories.filter { category in
            !category.isAvoid && (category.isChecklist || !covered.contains(category.id))
        }
    }

    private var avoidCategories: [CategoryDTO] {
        viewModel.categories.filter(\.isAvoid)
    }

    @ViewBuilder
    private var categoryList: some View {
        if viewModel.categories.isEmpty && quickMarks.marks.isEmpty {
            VStack(spacing: 0) {
                VoiceDayButton { Task { await reload() } }
                    .padding(.horizontal, DS.Spacing.lg)
                    .padding(.top, DS.Spacing.lg)
                if let message = viewModel.saveErrorMessage {
                    Text(message)
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.danger)
                        .padding(.horizontal, DS.Spacing.lg)
                        .padding(.top, DS.Spacing.md)
                        .accessibilityIdentifier("today.error")
                }
                DSEmptyState(
                    title: "No habits yet",
                    systemImage: "checkmark.circle",
                    message: "Create a category to start tracking today."
                )
            }
        } else {
            ScrollView {
                VStack(alignment: .leading, spacing: DS.Spacing.lg) {
                    if let message = viewModel.saveErrorMessage {
                        Text(message)
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.danger)
                            .accessibilityIdentifier("today.error")
                    }
                    VoiceDayButton { Task { await reload() } }
                    if !quickMarks.marks.isEmpty {
                        sectionLabel("Быстрые отметки")
                        QuickMarksSection(viewModel: quickMarks) { openDaySheet(for: $0) }
                    }
                    if !avoidCategories.isEmpty {
                        sectionLabel("Streaks")
                        if let message = viewModel.streaksError {
                            Text(message)
                                .font(DS.Typography.caption)
                                .foregroundStyle(DS.Palette.textSecondary)
                        }
                        ForEach(avoidCategories) { category in
                            avoidStreakCard(category)
                        }
                    }
                    if !plainCategories.isEmpty {
                        if !quickMarks.marks.isEmpty || !avoidCategories.isEmpty {
                            sectionLabel("Habits")
                        }
                        ForEach(plainCategories) { category in
                            habitCard(category)
                        }
                    }
                }
                .padding(DS.Spacing.lg)
            }
            .refreshable {
                await reload()
            }
        }
    }

    private func sectionLabel(_ title: String) -> some View {
        Text(title.uppercased())
            .font(DS.Typography.caption)
            .tracking(1.5)
            .foregroundStyle(DS.Palette.lime)
    }

    private func openDaySheet(for mark: QuickMarkDTO) {
        let category = viewModel.categories.first { $0.id == mark.categoryId }
        daySheet = DaySheetTarget(
            categoryID: mark.categoryId, title: category?.name ?? mark.label, category: category,
            mark: mark
        )
    }

    private func openDaySheet(for category: CategoryDTO) {
        let mark = quickMarks.marks.first { $0.categoryId == category.id }
        daySheet = DaySheetTarget(
            categoryID: category.id, title: category.name, category: category, mark: mark
        )
    }

    // MARK: Avoid streak card

    /// Oversized lime "N days clean" readout with the best streak underneath. The header leads to the
    /// relapse history; "It happened" records a relapse in one tap, whatever fields the category has.
    private func avoidStreakCard(_ category: CategoryDTO) -> some View {
        let streak = viewModel.streak(forCategory: category.id)
        let relapse = viewModel.relapseState(forCategory: category.id)
        return Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                NavigationLink {
                    RelapseHistoryView(category: category, viewModel: .live(categoryId: category.id))
                } label: {
                    HStack(spacing: DS.Spacing.sm) {
                        if let icon = category.icon, !icon.isEmpty {
                            Text(icon)
                                .font(DS.Typography.section)
                        }
                        Text(category.name)
                            .font(DS.Typography.card)
                            .foregroundStyle(DS.Palette.textPrimary)
                        Spacer()
                        Image(systemName: "chevron.right")
                            .foregroundStyle(DS.Palette.textSecondary)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("\(category.name): история срывов")

                VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                    Text(streak.map { TodayView.formatDays($0.currentStreak) } ?? "—")
                        .font(DS.Typography.hero)
                        .foregroundStyle(DS.Palette.lime)
                        .lineLimit(1)
                        .minimumScaleFactor(0.5)
                    Text("clean")
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                }
                if let streak {
                    Text("Best: \(TodayView.formatDays(streak.bestStreak))")
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                }

                HStack(spacing: DS.Spacing.sm) {
                    Button {
                        Task { await viewModel.recordRelapse(categoryID: category.id) }
                    } label: {
                        pill("It happened", color: DS.Palette.danger)
                    }
                    .buttonStyle(.plain)
                    .disabled(isBusy(relapse))
                    .accessibilityIdentifier("avoid.happened.\(category.id)")
                    Button {
                        whenCategory = category
                    } label: {
                        pill("Когда?", color: DS.Palette.lime)
                    }
                    .buttonStyle(.plain)
                    .disabled(isBusy(relapse))
                    .accessibilityIdentifier("avoid.when.\(category.id)")
                    Button {
                        openDaySheet(for: category)
                    } label: {
                        pill("Записи", color: DS.Palette.textSecondary)
                    }
                    .buttonStyle(.plain)
                }

                relapseFollowUp(relapse, category: category)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func pill(_ title: String, color: Color) -> some View {
        Text(title)
            .font(DS.Typography.caption)
            .foregroundStyle(color)
            .padding(.vertical, DS.Spacing.xs)
            .padding(.horizontal, DS.Spacing.md)
            .overlay(Capsule().stroke(color.opacity(0.5), lineWidth: 1))
    }

    private func isBusy(_ state: TodayViewModel.RelapseState) -> Bool {
        switch state {
        case .recording, .undoing, .savingDetails: return true
        case .idle, .recorded: return false
        }
    }

    /// After the tap: what was written, with undo of this screen's own relapse and optional details.
    @ViewBuilder
    private func relapseFollowUp(
        _ state: TodayViewModel.RelapseState, category: CategoryDTO
    ) -> some View {
        switch state {
        case .idle, .recording:
            EmptyView()
        case .recorded(let recorded), .undoing(let recorded), .savingDetails(let recorded):
            HStack(spacing: DS.Spacing.sm) {
                Text(relapseLine(recorded))
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textPrimary)
                Spacer()
                Button("Подробнее") { detailsCategory = category }
                    .font(DS.Typography.caption)
                    .disabled(isBusy(state))
                if recorded.created {
                    Button("Отменить") {
                        Task { await viewModel.undoRelapse(categoryID: category.id) }
                    }
                    .font(DS.Typography.caption)
                    .disabled(isBusy(state))
                    .accessibilityIdentifier("avoid.undo.\(category.id)")
                }
            }
        }
    }

    private func relapseLine(_ recorded: RelapseRecordedDTO) -> String {
        let base = recorded.created ? "Срыв записан" : "Срыв уже записан"
        guard recorded.entry.entryDate != viewModel.todayString else { return base }
        return "\(base): \(RelapseAnalysis.formatDay(recorded.entry.entryDate))"
    }

    /// Streak length with the correct English day form, e.g. "1 day" / "42 days".
    /// Mirrors the web `formatDays` so both clients read identically.
    static func formatDays(_ days: Int) -> String {
        "\(days) \(days == 1 ? "day" : "days")"
    }

    // MARK: Habit card

    /// The size of the plus: a thumb hits it without opening the row.
    private static let quickAddIconSize: CGFloat = 32
    private static let quickAddHitSize: CGFloat = 48

    /// The whole card, its padding included, opens the form; the plus inside it is a button of its own
    /// and takes its taps first.
    private func habitCard(_ category: CategoryDTO) -> some View {
        Card {
            HStack(spacing: DS.Spacing.sm) {
                HStack(spacing: DS.Spacing.md) {
                    if let icon = category.icon, !icon.isEmpty {
                        Text(icon)
                            .font(DS.Typography.section)
                    }
                    Text(category.name)
                        .font(DS.Typography.card)
                        .foregroundStyle(DS.Palette.textPrimary)
                    Spacer()
                    if hasPendingEntry(category) {
                        PendingRowTag()
                    }
                    // A ticked box says «сделано» beside the plus; its raw «true» would only crowd the name.
                    if !viewModel.isTicked(categoryID: category.id) {
                        Text(todaySummary(for: category))
                            .font(DS.Typography.card)
                            .foregroundStyle(hasEntries(category) ? DS.Palette.lime : DS.Palette.textSecondary)
                    }
                }
                .frame(minHeight: Self.quickAddHitSize)
                // One element for VoiceOver that opens the form; the plus beside it is another one.
                .accessibilityElement(children: .combine)
                .accessibilityAddTraits(.isButton)
                .accessibilityAction { selectedCategory = category }
                .accessibilityIdentifier("today.card.\(category.id)")
                quickAddButton(category)
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { selectedCategory = category }
    }

    /// What the plus does is `TodayQuickAdd`'s call: add the step, ask for the amount, or open the form.
    private func quickAddButton(_ category: CategoryDTO) -> some View {
        let plan = TodayQuickAdd.plan(for: category)
        let isAdding = viewModel.quickAddingCategoryIDs.contains(category.id)
        let isTicked = viewModel.isTicked(categoryID: category.id)
        return Button {
            switch plan {
            case .step, .check:
                Task { await viewModel.quickAdd(categoryID: category.id) }
            case .amountSheet, .textSheet:
                fieldCategory = category
            case .fullForm:
                selectedCategory = category
            }
        } label: {
            HStack(spacing: DS.Spacing.xs) {
                if case .step(_, let amount) = plan {
                    Text("+\(TodayQuickAdd.formatAmount(amount))")
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.lime)
                }
                if isTicked {
                    Text("сделано")
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.lime)
                }
                Image(systemName: isTicked ? "checkmark.circle.fill" : "plus.circle.fill")
                    .font(.system(size: Self.quickAddIconSize))
                    .foregroundStyle(DS.Palette.lime)
                    .frame(width: Self.quickAddHitSize, height: Self.quickAddHitSize)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        // Never `.disabled`: a switched-off button hands its touch to the card behind it, and the second
        // tap of a quick double press would open the form. The model drops that tap instead.
        .opacity(isAdding ? 0.5 : 1)
        .accessibilityLabel(isTicked ? "Сделано: \(category.name)" : "Добавить: \(category.name)")
        .accessibilityIdentifier("today.quickadd.\(category.id)")
    }

    private func hasEntries(_ category: CategoryDTO) -> Bool {
        !viewModel.entries(forCategory: category.id).isEmpty
    }

    /// True when at least one of the category's rows is an offline-queued create that
    /// has not reached the server yet — drives the per-card "pending" tag so a queued
    /// entry reads as pending in the list, not as an already-saved value.
    private func hasPendingEntry(_ category: CategoryDTO) -> Bool {
        viewModel.entries(forCategory: category.id).contains(where: \.isPending)
    }

    /// Compact right-side summary: today's single value, entry count, or a dash.
    private func todaySummary(for category: CategoryDTO) -> String {
        let entries = viewModel.entries(forCategory: category.id)
        if entries.isEmpty {
            return "—"
        }
        if entries.count == 1, entries[0].values.count == 1,
           let value = entries[0].values[0].value {
            return value
        }
        // Water in three taps reads as one total, not as «3 entries».
        if category.fields.count == 1, category.fields[0].fieldType == .number {
            let amounts = entries.compactMap { $0.values.first?.value.flatMap { Double($0) } }
            if amounts.count == entries.count {
                return TodayQuickAdd.formatAmount(amounts.reduce(0, +))
            }
        }
        return "\(entries.count) entries"
    }
}

/// Per-card "pending" tag: marks a habit whose value came from an offline-queued create
/// still waiting to sync, so the row reads as pending rather than as a saved value.
struct PendingRowTag: View {
    var body: some View {
        HStack(spacing: DS.Spacing.xs) {
            Image(systemName: "arrow.up.circle")
            Text("Pending")
        }
        .font(DS.Typography.caption)
        .foregroundStyle(DS.Palette.textSecondary)
        .padding(.vertical, 2)
        .padding(.horizontal, DS.Spacing.sm)
        .overlay(
            Capsule().stroke(DS.Palette.textSecondary.opacity(0.4), lineWidth: 1)
        )
    }
}

/// Dynamic entry form generated from the category's field definitions.
/// The first number field is auto-focused so "42 pushups" needs only:
/// tap habit → type 42 → tap Save.
struct QuickEntrySheet: View {
    let category: CategoryDTO
    @ObservedObject var viewModel: TodayViewModel

    @Environment(\.dismiss) private var dismiss
    @State private var fieldValues: [Int: String] = [:]
    @State private var isSaving = false
    @FocusState private var focusedFieldID: Int?

    private var sortedFields: [FieldDTO] {
        category.fields.sorted { ($0.order, $0.id) < ($1.order, $1.id) }
    }

    /// Required fields the user has not filled in yet; Save stays disabled
    /// (and the field names are highlighted) until this is empty, so the sheet
    /// never sends a POST with missing required values.
    private var missingRequiredFields: [FieldDTO] {
        sortedFields.filter { field in
            field.isRequired && trimmedValue(for: field.id).isEmpty
        }
    }

    private func trimmedValue(for fieldID: Int) -> String {
        (fieldValues[fieldID] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// The field whose value drives the oversized hero readout — the first number
    /// field ("42 pushups" reads big), falling back to the first field of any type.
    private var heroField: FieldDTO? {
        sortedFields.first { $0.fieldType == .number } ?? sortedFields.first
    }

    var body: some View {
        NavigationStack {
            Form {
                if let heroField {
                    Section {
                        heroReadout(for: heroField)
                    }
                    .listRowBackground(Color.clear)
                }
                Section {
                    ForEach(sortedFields) { field in
                        fieldRow(for: field)
                    }
                } footer: {
                    if !missingRequiredFields.isEmpty {
                        Text(
                            "Required: "
                                + missingRequiredFields.map(\.name).joined(separator: ", ")
                        )
                        .foregroundStyle(DS.Palette.danger)
                    }
                }
                .listRowBackground(DS.Palette.card)
                if let message = viewModel.saveErrorMessage {
                    Section {
                        Text(message)
                            .foregroundStyle(DS.Palette.danger)
                    }
                    .listRowBackground(DS.Palette.card)
                }
            }
            .dsScreenBackground()
            .navigationTitle(category.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        Task { await save() }
                    }
                    .disabled(isSaving || !missingRequiredFields.isEmpty)
                }
            }
            .onAppear {
                // A previous sheet's failure message must not leak into this one.
                viewModel.saveErrorMessage = nil
                seedDefaults()
                focusedFieldID = sortedFields.first { $0.fieldType == .number }?.id
                    ?? sortedFields.first?.id
            }
        }
        .presentationDetents([.fraction(0.7), .large])
        .presentationDragIndicator(.visible)
    }

    /// Oversized lime readout of the primary field's current value, so the number
    /// being logged dominates the sheet the way the reference mockup does.
    private func heroReadout(for field: FieldDTO) -> some View {
        VStack(spacing: DS.Spacing.xs) {
            Text(trimmedValue(for: field.id).isEmpty ? "—" : trimmedValue(for: field.id))
                .font(DS.Typography.hero)
                .foregroundStyle(DS.Palette.lime)
                .lineLimit(1)
                .minimumScaleFactor(0.5)
            Text(field.name)
                .font(DS.Typography.caption)
                .foregroundStyle(DS.Palette.textSecondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, DS.Spacing.md)
    }

    @ViewBuilder
    private func fieldRow(for field: FieldDTO) -> some View {
        switch field.fieldType {
        case .number:
            TextField(field.name, text: binding(for: field.id))
                .keyboardType(.decimalPad)
                .focused($focusedFieldID, equals: field.id)
        case .boolean:
            Toggle(field.name, isOn: boolBinding(for: field.id))
        case .select:
            Picker(field.name, selection: binding(for: field.id)) {
                Text("—").tag("")
                ForEach(selectOptions(for: field), id: \.self) { option in
                    Text(option).tag(option)
                }
            }
        case .text, .date, .datetime, .time, .duration, .unknown:
            TextField(field.name, text: binding(for: field.id))
                .focused($focusedFieldID, equals: field.id)
        }
    }

    private func seedDefaults() {
        for field in sortedFields {
            guard fieldValues[field.id] == nil else { continue }
            if let defaultValue = field.defaultValue {
                fieldValues[field.id] = defaultValue
            } else if field.fieldType == .boolean {
                // The toggle already renders "off"; seed it so what the user
                // sees is what gets sent, and required booleans count as filled.
                fieldValues[field.id] = "false"
            }
        }
    }

    private func binding(for fieldID: Int) -> Binding<String> {
        Binding(
            get: { fieldValues[fieldID] ?? "" },
            set: { fieldValues[fieldID] = $0 }
        )
    }

    private func boolBinding(for fieldID: Int) -> Binding<Bool> {
        Binding(
            get: { fieldValues[fieldID] == "true" },
            set: { fieldValues[fieldID] = $0 ? "true" : "false" }
        )
    }

    /// Parses the field's `options` JSON array (e.g. `["good", "bad"]`).
    private func selectOptions(for field: FieldDTO) -> [String] {
        guard let options = field.options,
              let data = options.data(using: .utf8),
              let parsed = try? JSONDecoder().decode([String].self, from: data) else {
            return []
        }
        return parsed
    }

    private func save() async {
        isSaving = true
        defer { isSaving = false }
        let nonEmptyValues = fieldValues.filter {
            !$0.value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        if await viewModel.saveEntry(categoryID: category.id, values: nonEmptyValues) {
            dismiss()
        }
    }
}
