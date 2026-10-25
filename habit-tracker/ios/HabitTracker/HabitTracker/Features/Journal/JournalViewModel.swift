// [review:need-review] PHASE-01/09-ios-journal, PHASE-01/208
// summary: Journal feed state — load list, compose draft (title/content/mood/tags/date), create with tag normalization, delete
import Foundation

/// Pure helpers for the backend's comma-separated `tags` string. Kept free of any
/// view-model state so tag parsing is trivially testable and reused by create/edit.
enum JournalTags {
    /// Splits a raw tag string into trimmed, non-empty tokens, preserving order.
    static func parse(_ raw: String) -> [String] {
        raw.split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    /// Normalizes a raw tag string to the backend form (`a,b,c`), or nil when empty.
    static func normalize(_ raw: String) -> String? {
        let parts = parse(raw)
        return parts.isEmpty ? nil : parts.joined(separator: ",")
    }
}

/// The mood options offered by the picker. Raw values match the backend's `mood` strings.
enum JournalMood: String, CaseIterable, Identifiable {
    case happy
    case sad
    case neutral
    case excited
    case anxious
    case calm
    case tired

    var id: String { rawValue }

    /// User-facing label with an emoji cue for the picker.
    var label: String {
        switch self {
        case .happy: return "😀 Радость"
        case .sad: return "😢 Грусть"
        case .neutral: return "😐 Нейтрально"
        case .excited: return "🤩 Восторг"
        case .anxious: return "😰 Тревога"
        case .calm: return "😌 Спокойствие"
        case .tired: return "😴 Усталость"
        }
    }
}

@MainActor
final class JournalViewModel: ObservableObject {
    /// Discriminated load state for the feed.
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    @Published private(set) var state: LoadState = .idle
    @Published private(set) var entries: [JournalEntryDTO] = []

    /// Whether the compose sheet is open.
    @Published var isComposing = false
    @Published var draftTitle = ""
    @Published var draftContent = ""
    @Published var draftDate = ""
    @Published var draftMood: String?
    @Published var draftTags = ""
    @Published var saveErrorMessage: String?

    static let notConfiguredMessage = "Set the server address in Settings"
    static let emptyContentMessage = "Write something before saving"

    private let apiProvider: () -> JournalAPI?

    /// Primary init: the provider is re-evaluated on every call, so Settings
    /// changes (server address / API key) take effect without an app restart.
    init(apiProvider: @escaping () -> JournalAPI?) {
        self.apiProvider = apiProvider
    }

    /// Convenience init with a fixed API (used by unit tests).
    convenience init(api: JournalAPI) {
        self.init(apiProvider: { api })
    }

    /// The date used to seed a new entry, formatted as the backend's `YYYY-MM-DD`.
    static func todayString(_ now: Date = Date()) -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .iso8601)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone.current
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: now)
    }

    /// Builds the production view model from stored Settings (UserDefaults + Keychain).
    static func live() -> JournalViewModel {
        JournalViewModel(apiProvider: { APIClient.live() })
    }

    // MARK: - Loading

    /// Loads the journal feed. Newest entries first (by date, then id).
    func load() async {
        state = .loading
        guard let api = apiProvider() else {
            state = .failure(Self.notConfiguredMessage)
            return
        }
        do {
            let fetched = try await api.fetchJournalEntries()
            entries = Self.sorted(fetched)
            state = .loaded
        } catch let error as APIClientError {
            state = .failure(error.userMessage)
        } catch {
            state = .failure("Unexpected error")
        }
    }

    // MARK: - Composing

    /// Opens the compose sheet with an empty draft seeded to today's date.
    func beginComposing() {
        draftTitle = ""
        draftContent = ""
        draftDate = Self.todayString()
        draftMood = nil
        draftTags = ""
        saveErrorMessage = nil
        isComposing = true
    }

    /// Closes the compose sheet without saving.
    func cancelComposing() {
        isComposing = false
        saveErrorMessage = nil
    }

    /// Creates a journal entry from the current draft via `POST /journal`.
    /// Content is required; blank title/tags/mood are omitted. On success the new
    /// entry is inserted at the top and the sheet closes; on failure the draft is
    /// kept intact (so typed text survives a network error). Returns true on success.
    func createEntry() async -> Bool {
        saveErrorMessage = nil
        let content = draftContent.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !content.isEmpty else {
            saveErrorMessage = Self.emptyContentMessage
            return false
        }
        guard let api = requireAPI() else { return false }

        let title = draftTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        let payload = JournalEntryCreateDTO(
            title: title.isEmpty ? nil : title,
            content: content,
            entryDate: draftDate.isEmpty ? Self.todayString() : draftDate,
            mood: draftMood,
            tags: JournalTags.normalize(draftTags)
        )
        do {
            let created = try await api.createJournalEntry(payload)
            entries = Self.sorted(entries + [created])
            isComposing = false
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

    /// Deletes an entry via `DELETE /journal/{id}` and drops it from the feed.
    /// On failure the entry stays and an error is surfaced. Returns true on success.
    func deleteEntry(id: Int) async -> Bool {
        saveErrorMessage = nil
        guard let api = requireAPI() else { return false }
        do {
            try await api.deleteJournalEntry(id: id)
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

    /// Newest first: descending by entry date, breaking ties by id (newest id first).
    private static func sorted(_ entries: [JournalEntryDTO]) -> [JournalEntryDTO] {
        entries.sorted {
            if $0.entryDate != $1.entryDate {
                return $0.entryDate > $1.entryDate
            }
            return $0.id > $1.id
        }
    }

    private func requireAPI() -> JournalAPI? {
        guard let api = apiProvider() else {
            saveErrorMessage = Self.notConfiguredMessage
            return nil
        }
        return api
    }
}
