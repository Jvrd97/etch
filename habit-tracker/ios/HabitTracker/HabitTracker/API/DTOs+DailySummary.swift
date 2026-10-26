// [review:need-review] PHASE-01/213
// summary: wire types of the day-summary flow (POST /daily-summary/draft and /apply) — numeric metric and checklist-tick operations resolved by ids, the day's journal operation with its append/create/replace mode, what could not be placed, the draft and apply requests
import Foundation

/// One number the draft proposes to record. Resolved by `categoryId` and `fieldId` only; the
/// server revalidates both on apply. The apply request echoes the operation back unchanged,
/// so every field the server sends is kept here.
struct LogMetricOpDTO: Codable, Equatable {
    var op = "log_metric"
    let categoryId: Int
    let fieldId: Int
    let value: Double
    /// The wording the number was read from, shown next to its switch.
    let sourceText: String
    /// The model placed the number without confidence: it arrives switched off.
    let uncertain: Bool
    /// The number itself looks wrong (300 push-ups): it arrives switched off.
    let implausible: Bool
    /// Nobody said this number, the model derived it from a description (a meal).
    let estimated: Bool
}

/// One checklist box the draft proposes to tick. There is no value on purpose: the plan can
/// raise a box and cannot lower one, because silence in a retelling is not "didn't do it".
struct CheckOpDTO: Codable, Equatable {
    var op = "check"
    let categoryId: Int
    let fieldId: Int
    let sourceText: String
    let uncertain: Bool
}

/// A number the model heard and could not place in any category. Inert: it writes nothing.
struct UnresolvedMetricDTO: Codable, Equatable {
    let text: String
    let reason: String?
}

/// The day written out as text, with what the server decided to do with it.
/// `existingEntryId` is context for the preview and is never trusted by the apply.
struct JournalOpDTO: Codable, Equatable {
    /// How the text meets what the day already holds. The server only proposes append or create;
    /// replace is chosen by the person.
    enum Mode: String, Codable, Equatable {
        case append
        case create
        case replace
    }

    var op = "write_journal"
    let title: String?
    let content: String
    let mood: String?
    let tags: String?
    var mode: Mode
    let existingEntryId: Int?
}

/// The plan as the server proposes it (`POST /daily-summary/draft`). Nothing is written yet.
struct DailySummaryDraftDTO: Codable, Equatable {
    let metrics: [LogMetricOpDTO]
    let checklist: [CheckOpDTO]
    let unresolved: [UnresolvedMetricDTO]
    let journal: JournalOpDTO?

    var isEmpty: Bool {
        metrics.isEmpty && checklist.isEmpty && unresolved.isEmpty && journal == nil
    }
}

/// Body of `POST /daily-summary/draft`: the retelling and the day it belongs to (`YYYY-MM-DD`).
struct DailySummaryDraftRequestDTO: Encodable, Equatable {
    let transcript: String
    let entryDate: String
}

/// Body of `POST /daily-summary/apply`: only what the person left switched on.
struct DailySummaryApplyRequestDTO: Encodable, Equatable {
    let entryDate: String
    let metrics: [LogMetricOpDTO]
    let checklist: [CheckOpDTO]
    let journal: JournalOpDTO?
}

/// What the apply wrote: one entry per category touched, plus the day's text.
struct DailySummaryApplyResponseDTO: Codable, Equatable {
    let entryIds: [Int]
    let journalEntryId: Int?
}
