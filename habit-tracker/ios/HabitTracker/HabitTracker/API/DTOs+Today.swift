// [review:need-review] PHASE-01/210, PHASE-03/236
// summary: wire types of the Today screen beyond DTOs.swift — the quick-mark directory with the day's state, one tap and its answer, an undo, one set of the day's journal, the relapse history of an avoid category and the answer to a one-tap relapse
// summary: PHASE-03/236 — a tap may carry `occurredAt`, the moment of a press replayed from the queue
import Foundation

/// One button of the quick-mark directory with the state of the day it was read for
/// (`GET /quick-marks`). The server decides the order (planned buttons first), what a
/// tap means and where it lands; the client only draws and sends the id.
struct QuickMarkDTO: Codable, Identifiable, Equatable {
    static let kindIncrement = "increment"
    static let kindCheck = "check"
    static let kindSetValue = "set_value"
    static let kindRelapse = "relapse"

    let id: Int
    let label: String
    let categoryId: Int
    let fieldId: Int
    let kind: String
    let step: Double?
    let unitLabel: String?
    let icon: String?
    let color: String?
    let hotkey: String?
    let order: Int
    let showInAgent: Bool
    let isActive: Bool
    let entryDate: String
    /// Null for a tick (a box is not a quantity) and for a number button the day has not touched.
    var todayTotal: Double?
    var done: Bool
    let planned: Bool
    let planItemId: String?
}

/// Body of `POST /quick-marks/{id}/events`. Carries an intent, never a category or a field.
/// `entryDate` is a guard against a stale screen after midnight (409), not a destination.
/// `occurredAt` is the moment of a press replayed from the queue, ISO 8601 in UTC: the server puts
/// the press on that moment's day. Nil is the moment the server takes the request.
struct QuickMarkEventRequestDTO: Encodable, Equatable {
    let value: Double?
    let entryDate: String?
    let utcOffsetMinutes: Int
    let source: String
    var occurredAt: String? = nil
}

/// The recorded tap and the state it produced, so a screen repaints without a second request.
struct QuickMarkEventDTO: Codable, Equatable {
    let eventId: Int
    let quickMarkId: Int
    let entryId: Int?
    let entryDate: String
    let occurredAt: String
    let todayTotal: Double?
    let done: Bool
}

/// A tap taken back, and what the day says once it is gone.
struct QuickMarkUndoDTO: Codable, Equatable {
    let eventId: Int
    let quickMarkId: Int
    let entryDate: String
    let undoneAt: String
    let todayTotal: Double?
    let done: Bool
}

/// One tap of a category's day as the journal keeps it. A taken-back tap stays in the list
/// with `undoneAt`, so a total that dropped has a visible reason.
struct QuickMarkDayEventDTO: Codable, Identifiable, Equatable {
    let eventId: Int
    let quickMarkId: Int
    let label: String
    let kind: String
    let unitLabel: String?
    let entryDate: String
    let occurredAt: String
    let delta: Double?
    let boolValue: Bool?
    let undoneAt: String?
    /// The server will accept an undo of exactly this tap; the screen does not re-derive the rule.
    let undoable: Bool

    var id: Int { eventId }
}

/// `GET /categories/{id}/relapses`: the streak with the days it broke on. `today` is the
/// server's day by the day rule in force, so the windows are counted from the same day
/// the streak was.
struct RelapseHistoryDTO: Codable, Equatable {
    let categoryId: Int
    let streakMode: String
    let currentStreak: Int
    let bestStreak: Int
    let lastRelapseDate: String?
    let trackedSince: String?
    let relapseDates: [String]
    let today: String
}

/// The entry a one-tap relapse landed on. `created` is true when this request (or an earlier
/// attempt under the same key) wrote it, so undoing it is allowed; false when the tap landed on a
/// relapse somebody else recorded a moment ago and must not delete it.
struct RelapseRecordedDTO: Decodable, Equatable {
    let entry: EntryDTO
    let created: Bool

    private enum CodingKeys: String, CodingKey {
        case created
    }

    init(entry: EntryDTO, created: Bool) {
        self.entry = entry
        self.created = created
    }

    init(from decoder: Decoder) throws {
        entry = try EntryDTO(from: decoder)
        created = try decoder.container(keyedBy: CodingKeys.self).decode(Bool.self, forKey: .created)
    }
}
