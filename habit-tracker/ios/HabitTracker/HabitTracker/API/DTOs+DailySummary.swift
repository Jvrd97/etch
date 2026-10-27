// [review:need-review] PHASE-01/213, PHASE-03/230
// summary: wire types of the day-summary flow (POST /daily-summary/draft and /apply) — what could not be placed, the draft and apply requests; the operations themselves (metric, check, journal) are shared with the chat in DTOs+PlanOperations.swift
import Foundation

/// A number the model heard and could not place in any category. Inert: it writes nothing.
struct UnresolvedMetricDTO: Codable, Equatable {
    let text: String
    let reason: String?
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
