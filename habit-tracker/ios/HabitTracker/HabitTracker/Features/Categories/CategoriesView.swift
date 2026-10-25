// [review:need-review] PHASE-01/35-ios-category-detail, PHASE-01/208
// summary: Categories screen — card rows navigate to category detail; leading-swipe edit, trailing-swipe delete; create/edit form + delete confirmation
import SwiftUI

struct CategoriesView: View {
    @StateObject private var viewModel: CategoriesViewModel
    @State private var editingCategory: CategoryDTO?
    @State private var isCreating = false
    @State private var pendingDeletion: CategoryDTO?

    init(viewModel: CategoriesViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        content
            .navigationTitle("Categories")
            .dsScreenBackground()
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        isCreating = true
                    } label: {
                        Image(systemName: "plus")
                    }
                    .accessibilityLabel("Add category")
                }
            }
        .task { await viewModel.load() }
        .sheet(isPresented: $isCreating) {
            CategoryFormView(mode: .create, viewModel: viewModel)
        }
        .sheet(item: $editingCategory) { category in
            CategoryFormView(mode: .edit(category), viewModel: viewModel)
        }
        .confirmationDialog(
            "Delete this category?",
            isPresented: deletionBinding,
            titleVisibility: .visible,
            presenting: pendingDeletion
        ) { category in
            Button("Delete \(category.name)", role: .destructive) {
                Task { await viewModel.deleteCategory(id: category.id) }
            }
            Button("Cancel", role: .cancel) {}
        } message: { _ in
            Text("This also deletes its fields and all recorded entries.")
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
            categoryList
        }
    }

    @ViewBuilder
    private var categoryList: some View {
        if viewModel.categories.isEmpty {
            DSEmptyState(
                title: "No categories yet",
                systemImage: "folder",
                message: "Create a category to start tracking habits.",
                action: (label: "New category", run: { isCreating = true })
            )
        } else {
            List(viewModel.categories) { category in
                NavigationLink {
                    CategoryDetailView(viewModel: .live(category: category))
                } label: {
                    HStack(spacing: DS.Spacing.md) {
                        ColorSwatch(hex: category.color)
                        Text(category.name)
                            .font(DS.Typography.card)
                            .foregroundStyle(DS.Palette.textPrimary)
                        Spacer()
                        Text("\(category.fields.count) fields")
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.textSecondary)
                    }
                }
                .listRowBackground(DS.Palette.card)
                .swipeActions(edge: .leading) {
                    Button {
                        editingCategory = category
                    } label: {
                        Label("Edit", systemImage: "pencil")
                    }
                    .tint(DS.Palette.info)
                }
                .swipeActions(edge: .trailing) {
                    Button(role: .destructive) {
                        pendingDeletion = category
                    } label: {
                        Label("Delete", systemImage: "trash")
                    }
                }
            }
            .refreshable { await viewModel.load() }
        }
    }
}

/// Small rounded color chip; falls back to a neutral fill when the hex is missing.
struct ColorSwatch: View {
    let hex: String?

    var body: some View {
        RoundedRectangle(cornerRadius: 4)
            .fill(Color(hex: hex) ?? Color.secondary.opacity(0.3))
            .frame(width: 20, height: 20)
    }
}

/// Create-or-edit form. Create builds a full `CategoryDraft` (with a field editor);
/// edit patches only the category's basic properties (field mutation is out of scope).
struct CategoryFormView: View {
    enum Mode {
        case create
        case edit(CategoryDTO)
    }

    let mode: Mode
    @ObservedObject var viewModel: CategoriesViewModel

    @Environment(\.dismiss) private var dismiss
    @State private var draft: CategoryDraft
    @State private var isSaving = false

    private static let palette = [
        "#EF4444", "#F59E0B", "#10B981", "#3B82F6", "#8B5CF6", "#EC4899",
    ]

    init(mode: Mode, viewModel: CategoriesViewModel) {
        self.mode = mode
        self.viewModel = viewModel
        switch mode {
        case .create:
            _draft = State(initialValue: CategoryDraft(color: Self.palette.first))
        case .edit(let category):
            _draft = State(initialValue: CategoryDraft(
                name: category.name,
                color: category.color,
                icon: category.icon,
                displayMode: category.displayMode
            ))
        }
    }

    private var isEditing: Bool {
        if case .edit = mode { return true }
        return false
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Category") {
                    TextField("Name", text: $draft.name)
                    colorPicker
                }
                .listRowBackground(DS.Palette.card)
                if !isEditing {
                    fieldsSection
                        .listRowBackground(DS.Palette.card)
                }
                if let message = viewModel.saveErrorMessage {
                    Section {
                        Text(message).foregroundStyle(DS.Palette.danger)
                    }
                    .listRowBackground(DS.Palette.card)
                }
            }
            .dsScreenBackground()
            .navigationTitle(isEditing ? "Edit Category" : "New Category")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { Task { await save() } }
                        .disabled(isSaving)
                }
            }
            .onAppear { viewModel.saveErrorMessage = nil }
        }
    }

    private var colorPicker: some View {
        HStack {
            Text("Color")
            Spacer()
            ForEach(Self.palette, id: \.self) { hex in
                Circle()
                    .fill(Color(hex: hex) ?? .gray)
                    .frame(width: 24, height: 24)
                    .overlay(
                        Circle().stroke(Color.primary, lineWidth: draft.color == hex ? 2 : 0)
                    )
                    .onTapGesture { draft.color = hex }
            }
        }
    }

    private var fieldsSection: some View {
        Section("Fields") {
            ForEach($draft.fields) { $field in
                FieldEditorRow(field: $field)
            }
            .onDelete { draft.fields.remove(atOffsets: $0) }
            Button {
                draft.fields.append(FieldDraft())
            } label: {
                Label("Add field", systemImage: "plus.circle")
            }
        }
    }

    private func save() async {
        isSaving = true
        defer { isSaving = false }
        let ok: Bool
        switch mode {
        case .create:
            ok = await viewModel.createCategory(draft)
        case .edit(let category):
            ok = await viewModel.updateCategory(id: category.id, draft)
        }
        if ok { dismiss() }
    }
}

/// One editable field row: name, type, required toggle, and (for `select`) a
/// comma-separated options entry mapped to the draft's option list.
struct FieldEditorRow: View {
    @Binding var field: FieldDraft

    private static let editableTypes: [FieldTypeDTO] = [
        .number, .text, .boolean, .select, .date, .time, .duration,
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField("Field name", text: $field.name)
            Picker("Type", selection: $field.fieldType) {
                ForEach(Self.editableTypes, id: \.rawValue) { type in
                    Text(type.rawValue.capitalized).tag(type)
                }
            }
            Toggle("Required", isOn: $field.isRequired)
            if field.fieldType == .select {
                TextField("Options (comma-separated)", text: optionsText)
            }
        }
        .padding(.vertical, 4)
    }

    private var optionsText: Binding<String> {
        Binding(
            get: { field.options.joined(separator: ", ") },
            set: {
                field.options = $0
                    .split(separator: ",")
                    .map { $0.trimmingCharacters(in: .whitespaces) }
            }
        )
    }
}

extension Color {
    /// Parses a `#RRGGBB` string into a Color; nil when the string is missing or malformed.
    init?(hex: String?) {
        guard let hex, hex.hasPrefix("#"), hex.count == 7,
              let value = Int(hex.dropFirst(), radix: 16) else {
            return nil
        }
        self.init(
            red: Double((value >> 16) & 0xFF) / 255,
            green: Double((value >> 8) & 0xFF) / 255,
            blue: Double(value & 0xFF) / 255
        )
    }
}
