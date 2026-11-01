// [review:need-review] PHASE-01/210, PHASE-03/225, PHASE-03/294
// summary: PHASE-03/294 — a relapse may carry the day it happened on; the table read of the last 30 days is part of the Today surface (it orders the cards by use)
// summary: Today endpoints beyond TodayAPI — the quick-mark directory, one tap under an Idempotency-Key, undo, the sets of a day; the avoid streaks of all categories in one request, a one-tap relapse, the relapse history; entry patch/delete for the day list; an entry create under a key, so a save that goes offline replays as the same request
import Foundation

/// The quick-mark endpoints (`/api/v1/quick-marks`). A tap sends an id, the server decides the rest.
protocol QuickMarksAPI {
    func fetchQuickMarks() async throws -> [QuickMarkDTO]
    /// The key makes a retried tap the same tap: a request whose answer was lost is sent
    /// again under it and the day's sum does not double.
    func tapQuickMark(
        id: Int, request: QuickMarkEventRequestDTO, idempotencyKey: String
    ) async throws -> QuickMarkEventDTO
    func undoQuickMarkEvent(id: Int) async throws -> QuickMarkUndoDTO
    func fetchQuickMarkDayEvents(categoryId: Int) async throws -> [QuickMarkDayEventDTO]
}

/// What the Today screen needs on top of `TodayAPI`: one bulk streak read, the one-tap
/// relapse, and the entry mutations of the day list. `APIClient` is the production implementation.
protocol TodayScreenAPI: TodayAPI {
    /// The key is the key of the queued replay too: a save whose answer was lost is not recorded twice.
    func createEntry(_ entry: EntryCreateDTO, idempotencyKey: String?) async throws -> EntryDTO
    func fetchAvoidStreaks() async throws -> [CategoryStreakDTO]
    /// `entryDate` is the day the relapse happened on (`yyyy-MM-dd`); nil is the server's today.
    func recordRelapse(
        categoryId: Int, entryDate: String?, idempotencyKey: String
    ) async throws -> RelapseRecordedDTO
    /// Entries per day and category: the Today cards are ordered by how often they were filled.
    func fetchTable(dateFrom: String, dateTo: String) async throws -> TableResponseDTO
    func updateEntry(id: Int, _ payload: EntryUpdateDTO) async throws -> EntryDTO
    func deleteEntry(id: Int) async throws
    /// Every record of one category, all days: the history behind a card.
    func fetchEntries(categoryId: Int?) async throws -> [EntryDTO]
}

extension TodayScreenAPI {
    func recordRelapse(categoryId: Int, idempotencyKey: String) async throws -> RelapseRecordedDTO {
        try await recordRelapse(categoryId: categoryId, entryDate: nil, idempotencyKey: idempotencyKey)
    }
}

/// The relapse history screen of one avoid category.
protocol RelapseHistoryAPI {
    func fetchRelapseHistory(categoryId: Int) async throws -> RelapseHistoryDTO
}

extension APIClient: QuickMarksAPI, TodayScreenAPI, RelapseHistoryAPI {
    /// Ask for the iOS surface: the server answers every client from one selection.
    private static let quickMarksSurface = "ios"
    private static let avoidStreakMode = "avoid"

    func fetchQuickMarks() async throws -> [QuickMarkDTO] {
        try await getJSON(
            path: "/quick-marks",
            query: [URLQueryItem(name: "surface", value: Self.quickMarksSurface)]
        )
    }

    func tapQuickMark(
        id: Int, request: QuickMarkEventRequestDTO, idempotencyKey: String
    ) async throws -> QuickMarkEventDTO {
        try await sendJSON(
            path: "/quick-marks/\(id)/events", method: "POST", body: request,
            idempotencyKey: idempotencyKey
        )
    }

    func undoQuickMarkEvent(id: Int) async throws -> QuickMarkUndoDTO {
        let url = try makeAPIURL(path: "/quick-marks/events/\(id)/undo", query: [])
        return try decodeJSON(try await send(makeRequest(url: url, method: "POST")))
    }

    func fetchQuickMarkDayEvents(categoryId: Int) async throws -> [QuickMarkDayEventDTO] {
        try await getJSON(
            path: "/quick-marks/events",
            query: [URLQueryItem(name: "category_id", value: String(categoryId))]
        )
    }

    func fetchAvoidStreaks() async throws -> [CategoryStreakDTO] {
        try await getJSON(
            path: "/streaks",
            query: [URLQueryItem(name: "streak_mode", value: Self.avoidStreakMode)]
        )
    }

    func recordRelapse(
        categoryId: Int, entryDate: String?, idempotencyKey: String
    ) async throws -> RelapseRecordedDTO {
        if let entryDate {
            return try await sendJSON(
                path: "/categories/\(categoryId)/relapses", method: "POST",
                body: RelapseRecordRequestDTO(entryDate: entryDate), idempotencyKey: idempotencyKey
            )
        }
        let url = try makeAPIURL(path: "/categories/\(categoryId)/relapses", query: [])
        var request = makeRequest(url: url, method: "POST")
        request.setValue(idempotencyKey, forHTTPHeaderField: "Idempotency-Key")
        return try decodeJSON(try await send(request))
    }

    func fetchRelapseHistory(categoryId: Int) async throws -> RelapseHistoryDTO {
        try await getJSON(path: "/categories/\(categoryId)/relapses", query: [])
    }
}
