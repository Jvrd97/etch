// [review:need-review] PHASE-01/32-ios-lime-tech-design-pass, PHASE-01/208
// summary: Journal screen — Lime Tech dark restyle: card feed rows, lime tags, neon loader, DS error/empty states; compose sheet + swipe-delete
import SwiftUI

struct JournalView: View {
    @StateObject private var viewModel: JournalViewModel
    @State private var pendingDeletion: JournalEntryDTO?

    init(viewModel: JournalViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        content
            .navigationTitle("Journal")
            .dsScreenBackground()
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        viewModel.beginComposing()
                    } label: {
                        Image(systemName: "square.and.pencil")
                            .accessibilityLabel("New journal entry")
                    }
                }
            }
        .task { await viewModel.load() }
        .sheet(isPresented: $viewModel.isComposing) {
            JournalComposeView(viewModel: viewModel)
        }
        .confirmationDialog(
            "Delete this entry?",
            isPresented: deletionBinding,
            titleVisibility: .visible,
            presenting: pendingDeletion
        ) { entry in
            Button("Delete", role: .destructive) {
                Task { await viewModel.deleteEntry(id: entry.id) }
            }
            Button("Cancel", role: .cancel) {}
        } message: { _ in
            Text("This permanently removes the entry.")
        }
    }

    private var deletionBinding: Binding<Bool> {
        Binding(
            get: { pendingDeletion != nil },
            set: { if !$0 { pendingDeletion = nil } }
        )
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
            feed
        }
    }

    @ViewBuilder
    private var feed: some View {
        if viewModel.entries.isEmpty {
            DSEmptyState(
                title: "No entries yet",
                systemImage: "book.closed",
                message: "Tap the compose button to write about your day.",
                action: (label: "New entry", run: { viewModel.beginComposing() })
            )
        } else {
            List {
                ForEach(viewModel.entries) { entry in
                    JournalRow(entry: entry)
                        .listRowBackground(DS.Palette.card)
                        .swipeActions(edge: .trailing) {
                            Button(role: .destructive) {
                                pendingDeletion = entry
                            } label: {
                                Label("Delete", systemImage: "trash")
                            }
                        }
                }
            }
            .refreshable { await viewModel.load() }
        }
    }
}

/// A single feed row: date + mood on top, optional title, a content preview, and tag chips.
struct JournalRow: View {
    let entry: JournalEntryDTO

    var body: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.sm) {
            HStack {
                Text(entry.entryDate)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
                Spacer()
                if let mood = entry.mood, let label = JournalMood(rawValue: mood)?.label {
                    Text(label)
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                }
            }
            if let title = entry.title, !title.isEmpty {
                Text(title)
                    .font(DS.Typography.card)
                    .foregroundStyle(DS.Palette.textPrimary)
            }
            Text(entry.content)
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.textPrimary)
                .lineLimit(3)
            let tags = JournalTags.parse(entry.tags ?? "")
            if !tags.isEmpty {
                HStack(spacing: DS.Spacing.sm) {
                    ForEach(tags, id: \.self) { tag in
                        Text("#\(tag)")
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.lime)
                    }
                }
            }
        }
        .padding(.vertical, DS.Spacing.xs)
    }
}

/// Compose sheet for a new entry: title, mood picker, free-text body, and comma tags.
struct JournalComposeView: View {
    @ObservedObject var viewModel: JournalViewModel
    @State private var isSaving = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Entry") {
                    TextField("Title (optional)", text: $viewModel.draftTitle)
                    TextField("Date (YYYY-MM-DD)", text: $viewModel.draftDate)
                        .keyboardType(.numbersAndPunctuation)
                }
                .listRowBackground(DS.Palette.card)
                Section("Mood") {
                    Picker("Mood", selection: $viewModel.draftMood) {
                        Text("None").tag(String?.none)
                        ForEach(JournalMood.allCases) { mood in
                            Text(mood.label).tag(String?.some(mood.rawValue))
                        }
                    }
                }
                .listRowBackground(DS.Palette.card)
                Section("How was your day?") {
                    TextField("Write about your day…", text: $viewModel.draftContent, axis: .vertical)
                        .lineLimit(4...12)
                }
                .listRowBackground(DS.Palette.card)
                Section("Tags") {
                    TextField("comma, separated, tags", text: $viewModel.draftTags)
                        .autocorrectionDisabled()
                }
                .listRowBackground(DS.Palette.card)
                if let message = viewModel.saveErrorMessage {
                    Section {
                        Text(message).foregroundStyle(DS.Palette.danger)
                    }
                    .listRowBackground(DS.Palette.card)
                }
            }
            .dsScreenBackground()
            .navigationTitle("New Entry")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { viewModel.cancelComposing() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { Task { await save() } }
                        .disabled(isSaving)
                }
            }
        }
    }

    private func save() async {
        isSaving = true
        defer { isSaving = false }
        _ = await viewModel.createEntry()
    }
}
