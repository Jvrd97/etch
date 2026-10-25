// [review:need-review] PHASE-01/35-ios-category-detail, PHASE-01/37-ios-insights, PHASE-01/208
// summary: Shared entry-mutation surface — EntryEditDraft/LoadState/DayGroup models, EntryMutating protocol+extension (group/edit/delete/requireAPI)
import Foundation

/// A single entry being edited in a history form. `values` is keyed by field id
/// so the form can bind each of the category's fields to its current value; it is
/// serialized back to the backend's value list only when the PATCH payload is built.
struct EntryEditDraft: Equatable, Identifiable {
    let entryId: Int
    let categoryId: Int
    var entryDate: String
    var notes: String
    var values: [Int: String]

    /// Stable identity for `.sheet(item:)`: one draft per entry.
    var id: Int { entryId }
}

/// Discriminated load state for an entry history list.
enum EntryLoadState: Equatable {
    case idle
    case loading
    case loaded
    case failure(String)
}

/// One day's worth of entries, for a sectioned list.
struct EntryDayGroup: Equatable {
    let date: String
    let entries: [EntryDTO]
}

/// The state and behaviour every entry-history view model shares: an editable list
/// of entries, an in-flight edit draft, and PATCH/DELETE mutations. Conformers add
/// only their own concern — the Entries screen its category filter, the category
/// detail screen its quick-add — while grouping/editing/deleting live here once.
@MainActor
protocol EntryMutating: AnyObject, ObservableObject {
    /// Backing list the mutations edit in place.
    var entries: [EntryDTO] { get set }
    /// The entry currently open in the edit form; `nil` when no form is shown.
    var editDraft: EntryEditDraft? { get set }
    var saveErrorMessage: String? { get set }
    /// Entries the history list should group and show; defaults to `entries`,
    /// overridden where a filter applies (e.g. the Entries screen's category filter).
    var groupableEntries: [EntryDTO] { get }
    /// The shared entry-mutation API, or `nil` when the app is not configured.
    func mutationAPI() -> EntryMutationAPI?
}

extension EntryMutating {
    static var notConfiguredMessage: String { "Set the server address in Settings" }

    var groupableEntries: [EntryDTO] { entries }

    /// `groupableEntries` grouped by day, newest day first; within a day, load order.
    var groupedByDate: [EntryDayGroup] {
        Dictionary(grouping: groupableEntries) { $0.entryDate }
            .map { EntryDayGroup(date: $0.key, entries: $0.value) }
            .sorted { $0.date > $1.date }
    }

    // MARK: - Editing

    /// Opens the edit form for an entry, seeding the draft from its current values.
    func beginEditing(_ entry: EntryDTO) {
        saveErrorMessage = nil
        editDraft = EntryEditDraft(
            entryId: entry.id,
            categoryId: entry.categoryId,
            entryDate: entry.entryDate,
            notes: entry.notes ?? "",
            values: Dictionary(
                uniqueKeysWithValues: entry.values.map { ($0.fieldId, $0.value ?? "") }
            )
        )
    }

    /// Cancels editing without touching the list.
    func cancelEditing() {
        editDraft = nil
        saveErrorMessage = nil
    }

    /// Saves the open draft via `PATCH /entries/{id}`. On success the updated entry
    /// replaces its list row and the form closes; on failure the draft is kept intact
    /// so typed values survive a network error. Returns true on success.
    func saveEdit() async -> Bool {
        guard let draft = editDraft else { return false }
        saveErrorMessage = nil
        guard let api = requireAPI() else { return false }
        let payload = EntryUpdateDTO(
            entryDate: draft.entryDate,
            notes: draft.notes.isEmpty ? nil : draft.notes,
            values: draft.values
                .sorted { $0.key < $1.key }
                .map { EntryValueDTO(fieldId: $0.key, value: $0.value) }
        )
        do {
            let updated = try await api.updateEntry(id: draft.entryId, payload)
            if let index = entries.firstIndex(where: { $0.id == updated.id }) {
                entries[index] = updated
            }
            editDraft = nil
            return true
        } catch let error as APIClientError {
            saveErrorMessage = error.userMessage
            return false
        } catch {
            saveErrorMessage = "Unexpected error"
            return false
        }
    }

    // MARK: - Deleting

    /// Deletes an entry via `DELETE /entries/{id}` and drops it from the list.
    /// On failure the entry stays and an error is surfaced. Returns true on success.
    func deleteEditEntry(id: Int) async -> Bool {
        saveErrorMessage = nil
        guard let api = requireAPI() else { return false }
        do {
            try await api.deleteEntry(id: id)
            entries.removeAll { $0.id == id }
            return true
        } catch let error as APIClientError {
            saveErrorMessage = error.userMessage
            return false
        } catch {
            saveErrorMessage = "Unexpected error"
            return false
        }
    }

    // MARK: - Private

    /// Resolves the shared API, surfacing the not-configured message on failure.
    func requireAPI() -> EntryMutationAPI? {
        guard let api = mutationAPI() else {
            saveErrorMessage = Self.notConfiguredMessage
            return nil
        }
        return api
    }
}
