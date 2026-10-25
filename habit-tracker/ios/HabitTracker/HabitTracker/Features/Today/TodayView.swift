// [review:need-review] PHASE-01/32-ios-lime-tech-design-pass, PHASE-01/38-ios-avoid-streaks, PHASE-01/11-ios-read-cache, PHASE-01/12-ios-offline-queue, PHASE-01/208
// summary: Today screen — habit cards + quick-entry sheet; avoid categories show "N days clean" streak card + "It happened" relapse form; offline banner + "N entries waiting to send" outbox badge atop when data came from the read cache / a save was queued offline
import SwiftUI

struct TodayView: View {
    @StateObject private var viewModel: TodayViewModel
    @State private var selectedCategory: CategoryDTO?
    @State private var relapseCategory: CategoryDTO?

    init(viewModel: TodayViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        VStack(spacing: 0) {
            if let offlineAsOf = viewModel.offlineAsOf {
                OfflineBanner(updatedAt: offlineAsOf)
            }
            if viewModel.pendingUploadCount > 0 {
                PendingUploadsBadge(count: viewModel.pendingUploadCount)
            }
            content
        }
        .navigationTitle("Today")
        .dsScreenBackground()
        .task {
            await viewModel.load()
        }
        .sheet(item: $selectedCategory) { category in
            QuickEntrySheet(category: category, viewModel: viewModel)
        }
        .sheet(item: $relapseCategory) { category in
            RelapseSheet(category: category, viewModel: viewModel)
        }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .idle, .loading:
            NeonLoader(label: "Loading")
        case .failure(let message):
            DSErrorState(message: message) {
                Task { await viewModel.load() }
            }
        case .loaded:
            categoryList
        }
    }

    @ViewBuilder
    private var categoryList: some View {
        if viewModel.categories.isEmpty {
            DSEmptyState(
                title: "No habits yet",
                systemImage: "checkmark.circle",
                message: "Create a category to start tracking today."
            )
        } else {
            ScrollView {
                VStack(spacing: DS.Spacing.md) {
                    ForEach(viewModel.categories) { category in
                        row(for: category)
                    }
                }
                .padding(DS.Spacing.lg)
            }
            .refreshable {
                await viewModel.load()
            }
        }
    }

    /// Avoid categories with a loaded streak show the "N days clean" card; every
    /// other category keeps the tap-to-log habit card.
    @ViewBuilder
    private func row(for category: CategoryDTO) -> some View {
        if category.isAvoid, let streak = viewModel.streak(forCategory: category.id) {
            avoidStreakCard(category, streak: streak)
        } else {
            habitCard(category)
        }
    }

    /// Oversized lime "N days clean" readout with the best streak underneath and a
    /// small "It happened" button that opens the relapse form.
    private func avoidStreakCard(
        _ category: CategoryDTO, streak: CategoryStreakDTO
    ) -> some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.md) {
                HStack(spacing: DS.Spacing.sm) {
                    if let icon = category.icon, !icon.isEmpty {
                        Text(icon)
                            .font(DS.Typography.section)
                    }
                    Text(category.name)
                        .font(DS.Typography.card)
                        .foregroundStyle(DS.Palette.textPrimary)
                    Spacer()
                }
                VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                    Text(TodayView.formatDays(streak.currentStreak))
                        .font(DS.Typography.hero)
                        .foregroundStyle(DS.Palette.lime)
                        .lineLimit(1)
                        .minimumScaleFactor(0.5)
                    Text("clean")
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                }
                Text("Best: \(TodayView.formatDays(streak.bestStreak))")
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
                Button {
                    relapseCategory = category
                } label: {
                    Text("It happened")
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.danger)
                        .padding(.vertical, DS.Spacing.xs)
                        .padding(.horizontal, DS.Spacing.md)
                        .overlay(
                            Capsule().stroke(DS.Palette.danger.opacity(0.5), lineWidth: 1)
                        )
                }
                .buttonStyle(.plain)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    /// Streak length with the correct English day form, e.g. "1 day" / "42 days".
    /// Mirrors the web `formatDays` so both clients read identically.
    static func formatDays(_ days: Int) -> String {
        "\(days) \(days == 1 ? "day" : "days")"
    }

    private func habitCard(_ category: CategoryDTO) -> some View {
        Button {
            selectedCategory = category
        } label: {
            Card {
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
                    Text(todaySummary(for: category))
                        .font(DS.Typography.card)
                        .foregroundStyle(hasEntries(category) ? DS.Palette.lime : DS.Palette.textSecondary)
                    Image(systemName: "plus.circle.fill")
                        .foregroundStyle(DS.Palette.lime)
                        .font(DS.Typography.section)
                }
            }
        }
        .buttonStyle(.plain)
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

/// Slim badge shown above Today when the outbox holds creates that could not reach the
/// server yet (airplane mode). Tells the user their taps are safe, just not synced.
struct PendingUploadsBadge: View {
    let count: Int

    /// "1 entry waiting to send" / "3 entries waiting to send".
    static func caption(for count: Int) -> String {
        "\(count) \(count == 1 ? "entry" : "entries") waiting to send"
    }

    var body: some View {
        HStack(spacing: DS.Spacing.sm) {
            Image(systemName: "arrow.up.circle")
            Text(PendingUploadsBadge.caption(for: count))
                .font(DS.Typography.caption)
                .lineLimit(1)
            Spacer(minLength: 0)
        }
        .foregroundStyle(DS.Palette.lime)
        .padding(.vertical, DS.Spacing.sm)
        .padding(.horizontal, DS.Spacing.md)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(DS.Palette.card)
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

/// Relapse form for an avoid category ("It happened"): a count ("how much") and an
/// optional note. Saving posts the entry and reloads the streak, so the card shows
/// the reset current streak when the sheet dismisses.
struct RelapseSheet: View {
    let category: CategoryDTO
    @ObservedObject var viewModel: TodayViewModel

    @Environment(\.dismiss) private var dismiss
    @State private var count = ""
    @State private var notes = ""
    @State private var isSaving = false
    @FocusState private var countFocused: Bool

    private var countFieldName: String {
        viewModel.countField(forCategory: category.id)?.name ?? "How much"
    }

    private var canSave: Bool {
        // Backend counts a relapse only when the value is a positive number;
        // anything else would dismiss the sheet without resetting the streak.
        guard let value = Double(count.trimmingCharacters(in: .whitespacesAndNewlines)) else { return false }
        return value > 0 && !isSaving
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField(countFieldName, text: $count)
                        .keyboardType(.decimalPad)
                        .focused($countFocused)
                    TextField("Note (optional)", text: $notes, axis: .vertical)
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
                    .disabled(!canSave)
                }
            }
            .onAppear {
                viewModel.saveErrorMessage = nil
                countFocused = true
            }
        }
        .presentationDetents([.fraction(0.4), .medium])
        .presentationDragIndicator(.visible)
    }

    private func save() async {
        isSaving = true
        defer { isSaving = false }
        let trimmedCount = count.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedNotes = notes.trimmingCharacters(in: .whitespacesAndNewlines)
        let logged = await viewModel.logRelapse(
            categoryID: category.id,
            count: trimmedCount,
            notes: trimmedNotes.isEmpty ? nil : trimmedNotes
        )
        if logged {
            dismiss()
        }
    }
}
