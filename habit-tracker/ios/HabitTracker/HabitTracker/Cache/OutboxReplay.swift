// [review:need-review] PHASE-03/225
// summary: how a queued write reaches the server — each action is sent to its endpoint under the write's Idempotency-Key; a quick-mark press carries the day it was made as entry_date; a plan mark and a day notebook are first checked against the day as the server holds it now (read without marking the day as opened), and a server that moved on refuses the replay instead of being overwritten
import Foundation

/// Entry writes the queue replays. `APIClient` is the production implementation.
protocol OutboxEntriesAPI {
    func createEntry(_ entry: EntryCreateDTO, idempotencyKey: String?) async throws -> EntryDTO
    func upsertChecklistEntry(_ payload: ChecklistUpsertDTO) async throws -> EntryDTO
}

/// Day writes the queue replays, and the read its checks need. `APIClient` is the production implementation.
protocol OutboxDayAPI {
    /// The day as the server holds it, without `opened=true`: a replay is not a person looking at the day.
    func fetchDayUnopened(date: String) async throws -> DayDetailDTO
    func setMark(date: String, itemID: UUID, _ payload: DayMarkRequestDTO) async throws -> DayMarkDTO
    func recordFact(
        date: String, itemID: UUID, _ payload: PlanFactRequestDTO, idempotencyKey: String
    ) async throws -> PlanFactWriteDTO
    func saveNotebook(date: String, content: String) async throws
}

/// Sends one queued action to its endpoint.
struct OutboxReplay: OutboxSending {
    let entries: OutboxEntriesAPI
    let quickMarks: QuickMarksAPI
    let day: OutboxDayAPI

    func send(_ action: OutboxAction, idempotencyKey: String) async throws {
        switch action {
        case .createEntry(let entry):
            _ = try await entries.createEntry(entry, idempotencyKey: idempotencyKey)
        case .upsertChecklist(let list):
            // A PUT of the whole day's ticks: repeating it is the same state, no key needed.
            _ = try await entries.upsertChecklistEntry(list)
        case .tapQuickMark(let tap):
            _ = try await quickMarks.tapQuickMark(
                id: tap.quickMarkId,
                request: QuickMarkEventRequestDTO(
                    value: nil, entryDate: tap.serverDay, utcOffsetMinutes: tap.utcOffsetMinutes,
                    source: QuickMarkEventRequestDTO.iosSource
                ),
                idempotencyKey: idempotencyKey
            )
        case .setDayMark(let mark):
            if let expected = mark.expected {
                let current = try await day.fetchDayUnopened(date: mark.date)
                    .marks.first { $0.itemId == mark.itemID }?.state ?? ""
                guard current == expected || current == (mark.state ?? "") else {
                    throw OutboxConflict(reason: OutboxQueue.markChangedReason)
                }
            }
            _ = try await day.setMark(
                date: mark.date, itemID: mark.itemID, DayMarkRequestDTO(state: mark.state, note: mark.note)
            )
        case .recordPlanFact(let fact):
            _ = try await day.recordFact(
                date: fact.date, itemID: fact.itemID, fact.body, idempotencyKey: idempotencyKey
            )
        case .saveNotebook(let notebook):
            if let expected = notebook.expected {
                let current = try await day.fetchDayUnopened(date: notebook.date).notebook ?? ""
                if current == notebook.content { return }
                guard current == expected else { throw OutboxConflict(reason: OutboxQueue.notebookChangedReason) }
            }
            try await day.saveNotebook(date: notebook.date, content: notebook.content)
        }
    }
}

extension QuickMarkEventRequestDTO {
    /// `source` of a press made on this phone, direct or replayed.
    static let iosSource = "ios"
}
