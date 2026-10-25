// [review:need-review] PHASE-01/35-ios-category-detail, PHASE-01/208
// summary: Entries history screen — date-sectioned list, filter menu; edit form now the shared generic EntryEditView, summary line from shared EntrySummary
import SwiftUI

struct EntriesView: View {
    @StateObject private var viewModel: EntriesViewModel
    @State private var pendingDeletion: EntryDTO?

    init(viewModel: EntriesViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        content
            .navigationTitle("History")
            .dsScreenBackground()
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    filterMenu
                }
            }
        .task { await viewModel.load() }
        .sheet(item: editingBinding) { draft in
            EntryEditView(
                viewModel: viewModel,
                fields: viewModel.categories.first { $0.id == draft.categoryId }?.fields ?? []
            )
        }
        .confirmationDialog(
            "Delete this entry?",
            isPresented: deletionBinding,
            titleVisibility: .visible,
            presenting: pendingDeletion
        ) { entry in
            Button("Delete", role: .destructive) {
                Task { await viewModel.deleteEditEntry(id: entry.id) }
            }
            Button("Cancel", role: .cancel) {}
        } message: { _ in
            Text("This permanently removes the entry and its values.")
        }
    }

    private var filterMenu: some View {
        Menu {
            Button {
                viewModel.selectedCategoryId = nil
            } label: {
                Label("All categories", systemImage: viewModel.selectedCategoryId == nil ? "checkmark" : "")
            }
            ForEach(viewModel.categories) { category in
                Button {
                    viewModel.selectedCategoryId = category.id
                } label: {
                    Label(
                        category.name,
                        systemImage: viewModel.selectedCategoryId == category.id ? "checkmark" : ""
                    )
                }
            }
        } label: {
            Image(systemName: "line.3.horizontal.decrease.circle")
                .accessibilityLabel("Filter by category")
        }
    }

    private var editingBinding: Binding<EntryEditDraft?> {
        Binding(
            get: { viewModel.editDraft },
            set: { if $0 == nil { viewModel.cancelEditing() } }
        )
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
            entryList
        }
    }

    @ViewBuilder
    private var entryList: some View {
        if viewModel.groupedByDate.isEmpty {
            DSEmptyState(
                title: "No entries",
                systemImage: "tray",
                message: "Logged entries will appear here."
            )
        } else {
            List {
                ForEach(viewModel.groupedByDate, id: \.date) { group in
                    Section(group.date) {
                        ForEach(group.entries) { entry in
                            entryRow(entry)
                        }
                        .listRowBackground(DS.Palette.card)
                    }
                }
            }
            .refreshable { await viewModel.load() }
        }
    }

    private func entryRow(_ entry: EntryDTO) -> some View {
        let category = viewModel.category(for: entry)
        return Button {
            viewModel.beginEditing(entry)
        } label: {
            VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                Text(category?.name ?? "Category \(entry.categoryId)")
                    .font(DS.Typography.card)
                    .foregroundStyle(DS.Palette.textPrimary)
                Text(EntrySummary.line(for: entry, category: category))
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
            }
        }
        .swipeActions(edge: .trailing) {
            Button(role: .destructive) {
                pendingDeletion = entry
            } label: {
                Label("Delete", systemImage: "trash")
            }
        }
    }
}
