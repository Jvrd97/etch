// [review:need-review] PHASE-01/08-ios-entries-crud, PHASE-01/38-ios-avoid-streaks, PHASE-01/37-ios-insights, PHASE-01/12-ios-offline-queue, PHASE-03/294
// summary: PHASE-03/294 — FieldDTO.quickSteps (the configured quick-add steps, additive)
// summary: Codable DTOs mirroring backend schemas — FieldTypeDTO, checklist upsert, category/field write payloads, entry notes + update payload; category streakMode + CategoryStreakDTO; AI insight request/report/list-item; EntryDTO.isPending marks offline-queued optimistic rows
import Foundation

/// Category with its field definitions, as returned by `GET /api/v1/categories`.
struct CategoryDTO: Codable, Identifiable, Equatable {
    /// Backend `display_mode` value that switches Today to the checklist upsert flow.
    static let checklistDisplayMode = "checklist"
    /// Backend `streak_mode` value that switches Today to the avoid-streak card.
    static let avoidStreakMode = "avoid"
    /// Default `streak_mode` for categories that don't track an avoid streak.
    static let buildStreakMode = "build"

    let id: Int
    let name: String
    let icon: String?
    let color: String?
    let displayMode: String
    let streakMode: String
    let isActive: Bool
    let fields: [FieldDTO]

    /// `streakMode` is defaulted for call-site convenience only. Decoding still
    /// requires the key: the backend always serializes streak_mode (Pydantic
    /// default "build"), so no decode fallback is provided here.
    init(
        id: Int,
        name: String,
        icon: String?,
        color: String?,
        displayMode: String,
        streakMode: String = CategoryDTO.buildStreakMode,
        isActive: Bool,
        fields: [FieldDTO]
    ) {
        self.id = id
        self.name = name
        self.icon = icon
        self.color = color
        self.displayMode = displayMode
        self.streakMode = streakMode
        self.isActive = isActive
        self.fields = fields
    }

    /// Checklist categories save via idempotent `PUT /entries/checklist`, not generic POST.
    var isChecklist: Bool {
        displayMode == Self.checklistDisplayMode
    }

    /// Avoid categories surface a "N days clean" streak card on Today instead of a
    /// running tally; the streak numbers come from `GET /categories/{id}/streak`.
    var isAvoid: Bool {
        streakMode == Self.avoidStreakMode
    }
}

/// Field type mirroring the backend `FieldType` enum; `unknown` keeps decoding
/// forward-compatible when the server introduces a type this client predates.
enum FieldTypeDTO: Equatable, Hashable {
    case text
    case number
    case boolean
    case date
    case datetime
    case time
    case select
    case duration
    case unknown(String)
}

extension FieldTypeDTO: RawRepresentable, Codable {
    private static let knownCases: [String: FieldTypeDTO] = [
        "text": .text,
        "number": .number,
        "boolean": .boolean,
        "date": .date,
        "datetime": .datetime,
        "time": .time,
        "select": .select,
        "duration": .duration,
    ]

    init(rawValue: String) {
        self = Self.knownCases[rawValue] ?? .unknown(rawValue)
    }

    // Explicit switch (no reverse map lookup): a lookup would compare via `==`,
    // which for RawRepresentable types is itself defined through `rawValue` —
    // that pair recurses until the stack blows.
    var rawValue: String {
        switch self {
        case .text: return "text"
        case .number: return "number"
        case .boolean: return "boolean"
        case .date: return "date"
        case .datetime: return "datetime"
        case .time: return "time"
        case .select: return "select"
        case .duration: return "duration"
        case .unknown(let raw): return raw
        }
    }

    init(from decoder: Decoder) throws {
        self.init(rawValue: try decoder.singleValueContainer().decode(String.self))
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }
}

/// Field definition inside a category (drives the dynamic entry form).
struct FieldDTO: Codable, Identifiable, Equatable {
    let id: Int
    let name: String
    let fieldType: FieldTypeDTO
    let isRequired: Bool
    let defaultValue: String?
    let options: String?
    let order: Int
    /// Steps of the quick-add buttons (`quick_steps`); nil when none are configured.
    var quickSteps: [Double]? = nil
}

/// Single field value inside an entry; also used as the create payload item.
struct EntryValueDTO: Codable, Equatable {
    let fieldId: Int
    let value: String?
}

/// Entry as returned by `GET /api/v1/entries`.
struct EntryDTO: Codable, Identifiable, Equatable {
    let id: Int
    let categoryId: Int
    let entryDate: String
    let notes: String?
    let values: [EntryValueDTO]

    init(
        id: Int,
        categoryId: Int,
        entryDate: String,
        notes: String? = nil,
        values: [EntryValueDTO]
    ) {
        self.id = id
        self.categoryId = categoryId
        self.entryDate = entryDate
        self.notes = notes
        self.values = values
    }

    /// True for an optimistic row that only exists locally: it was queued in the
    /// offline outbox and has not yet been accepted by the server. The offline queue
    /// mints such rows with a negative synthetic id (server ids are always positive),
    /// so `id < 0` is the "still waiting to send" marker the UI renders as pending.
    var isPending: Bool { id < 0 }
}

/// Payload for `POST /api/v1/entries`.
struct EntryCreateDTO: Codable, Equatable {
    let categoryId: Int
    let entryDate: String
    let notes: String?
    let values: [EntryValueDTO]
}

/// Payload for `PATCH /api/v1/entries/{id}`. Every property is optional so the
/// backend patches only what changed; the client sends `values` as a full
/// replacement list when field values are edited.
struct EntryUpdateDTO: Codable, Equatable {
    let entryDate: String?
    let notes: String?
    let values: [EntryValueDTO]?
}

/// Payload for idempotent `PUT /api/v1/entries/checklist`.
/// `values` is keyed by the field id as a String: the backend expects a JSON
/// object `{ "<field_id>": bool }`, and Swift would encode `[Int: Bool]` as an array.
struct ChecklistUpsertDTO: Codable, Equatable {
    let categoryId: Int
    let entryDate: String
    let values: [String: Bool]
}

/// Payload for creating a field, either standalone (`POST /categories/{id}/fields`)
/// or nested inside `CategoryCreateDTO`. `options` is the backend's JSON-array string
/// for `select` fields (e.g. `["good","bad"]`), and nil for every other field type.
struct FieldCreateDTO: Codable, Equatable {
    let name: String
    let fieldType: FieldTypeDTO
    let isRequired: Bool
    let defaultValue: String?
    let options: String?
    let order: Int
}

/// Payload for `POST /api/v1/categories`. Fields are created in the same request so a
/// whole category (e.g. "Приседания" with a number field) is one round trip.
struct CategoryCreateDTO: Codable, Equatable {
    let name: String
    let color: String?
    let icon: String?
    let displayMode: String
    let fields: [FieldCreateDTO]
}

/// Payload for `PATCH /api/v1/categories/{id}`. Every property is optional so the
/// backend patches only what changed; nil keys are still sent but map to no-op nulls.
struct CategoryUpdateDTO: Codable, Equatable {
    let name: String?
    let color: String?
    let icon: String?
    let displayMode: String?
}

/// Category metadata for the table view, as returned by `GET /api/v1/table`.
/// `primaryField*` describes the single field surfaced as this category's column.
struct TableCategoryMetaDTO: Codable, Identifiable, Equatable {
    let id: Int
    let name: String
    let displayMode: String
    let group: String?
    let primaryFieldId: Int?
    let primaryFieldName: String?
    let primaryFieldType: String?
}

/// Aggregated value of one field for one day (see #04 aggregation rules).
struct TableCellDTO: Codable, Equatable {
    let categoryId: Int
    let fieldId: Int
    let aggregatedValue: String?
    let entryCount: Int
}

/// One day of the table with its aggregated cells.
struct TableDayDTO: Codable, Equatable {
    let date: String
    let cells: [TableCellDTO]
}

/// Response of `GET /api/v1/table?date_from&date_to`.
struct TableResponseDTO: Codable, Equatable {
    let categories: [TableCategoryMetaDTO]
    let days: [TableDayDTO]
}

/// Journal entry as returned by `GET /api/v1/journal` (inside `JournalListResponseDTO.items`).
/// `tags` is the backend's comma-separated string; `entryDate` is `YYYY-MM-DD`.
struct JournalEntryDTO: Codable, Identifiable, Equatable {
    let id: Int
    let title: String?
    let content: String
    let entryDate: String
    let mood: String?
    let tags: String?
    let createdAt: String
    let updatedAt: String
}

/// Response of `GET /api/v1/journal` — total count plus the page of entries.
struct JournalListResponseDTO: Codable, Equatable {
    let total: Int
    let items: [JournalEntryDTO]
}

/// Payload for `POST /api/v1/journal`. `content` is required by the backend;
/// optional fields are omitted (nil) when the user leaves them blank.
struct JournalEntryCreateDTO: Codable, Equatable {
    let title: String?
    let content: String
    let entryDate: String
    let mood: String?
    let tags: String?
}

/// Payload for `PATCH /api/v1/journal/{id}`. Every property is optional so the
/// backend patches only what changed.
struct JournalEntryUpdateDTO: Codable, Equatable {
    let title: String?
    let content: String?
    let entryDate: String?
    let mood: String?
    let tags: String?
}

/// Streak numbers of an avoid category, as returned by `GET /api/v1/categories/{id}/streak`.
/// `lastRelapseDate` is the backend `YYYY-MM-DD` string, nil when the streak was never broken.
struct CategoryStreakDTO: Codable, Equatable {
    let categoryId: Int
    let streakMode: String
    let currentStreak: Int
    let bestStreak: Int
    let lastRelapseDate: String?
}

/// Payload for `POST /api/v1/insights` — the trailing period to analyse, in days.
struct InsightRequestDTO: Codable, Equatable {
    let periodDays: Int
}

/// A persisted AI insight report, as returned by `POST /api/v1/insights` and
/// `GET /api/v1/insights/{id}`. `content` is the full Markdown report; `createdAt`
/// is the backend's ISO-8601 timestamp string (decoded as-is, like other DTO dates).
struct InsightReportDTO: Codable, Identifiable, Equatable {
    let id: Int
    let periodDays: Int
    let content: String
    let model: String
    let createdAt: String
}

/// One row of the report history (`GET /api/v1/insights`): metadata plus a truncated
/// content preview (the backend caps the preview; `content` itself is not sent here).
struct InsightListItemDTO: Codable, Identifiable, Equatable {
    let id: Int
    let periodDays: Int
    let model: String
    let createdAt: String
    let preview: String
}

enum APIJSONCoding {
    /// Decoder matching the backend's snake_case JSON.
    static func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    /// Encoder producing the backend's snake_case JSON.
    static func makeEncoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }
}
