// [review:need-review] PHASE-03/225, PHASE-03/236, PHASE-03/242
// summary: how a queued write reaches the server — each action is sent to its endpoint under the write's Idempotency-Key; a quick-mark press carries the moment it was made as occurred_at (UTC, milliseconds, one shared formatter) (an old stored press, its day as entry_date); a plan mark and a day notebook are first checked against the day as the server holds it now (read without marking the day as opened) — the state it was made over, its own, or one of the writes it replaced — and a server that moved on, or a check answer that cannot be read, refuses the replay instead of overwriting or dropping it
// [review:need-review] PHASE-03/240
// summary: PHASE-03/240 — the replay of markSupplementTaken through OutboxSupplementsAPI (optional, so existing callers stay as they are)
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
    /// Nil only where no supplement write is replayed; one that arrives anyway waits like a dead network.
    var supplements: OutboxSupplementsAPI?

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
                    source: QuickMarkEventRequestDTO.iosSource,
                    occurredAt: tap.occurredAt.map(Self.wireMoment)
                ),
                idempotencyKey: idempotencyKey
            )
        case .setDayMark(let mark):
            if let expected = mark.expected {
                let current = try await serverDay(mark.date)
                    .marks.first { $0.itemId == mark.itemID }?.state ?? ""
                let accepted = [expected, mark.state ?? ""] + (mark.replacedStates ?? [])
                guard accepted.contains(current) else {
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
                let current = try await serverDay(notebook.date).notebook ?? ""
                if current == notebook.content { return }
                guard ([expected] + (notebook.replacedContents ?? [])).contains(current) else {
                    throw OutboxConflict(reason: OutboxQueue.notebookChangedReason)
                }
            }
            try await day.saveNotebook(date: notebook.date, content: notebook.content)
        case .markSupplementTaken(let intake):
            guard let supplements else { throw APIClientError.invalidBaseURL }
            _ = try await supplements.markIntake(
                supplementID: intake.supplementId, intakeDate: intake.intakeDate, idempotencyKey: idempotencyKey
            )
        }
    }

    /// A moment as `occurred_at` travels: ISO 8601 in UTC with milliseconds, `2026-10-25T01:00:00.250Z`.
    private static func wireMoment(_ moment: Date) -> String {
        wireFormatter.string(from: moment)
    }

    /// One formatter for every replay; `ISO8601DateFormatter` is safe to share across threads.
    private static let wireFormatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        formatter.timeZone = TimeZone(identifier: "UTC")
        return formatter
    }()

    /// The day for a replay check. An answer this app cannot read must not pass for "delivered"
    /// (the queue reads `invalidResponse` of a write that way): the write is refused, kept visible.
    private func serverDay(_ date: String) async throws -> DayDetailDTO {
        do {
            return try await day.fetchDayUnopened(date: date)
        } catch APIClientError.invalidResponse {
            throw OutboxConflict(reason: OutboxQueue.checkFailedReason)
        }
    }
}

extension QuickMarkEventRequestDTO {
    /// `source` of a press made on this phone, direct or replayed.
    static let iosSource = "ios"
}
