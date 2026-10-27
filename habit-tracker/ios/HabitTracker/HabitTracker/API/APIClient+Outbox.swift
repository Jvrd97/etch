// [review:need-review] PHASE-03/225
// summary: APIClient as the network side of the offline queue — entry and day writes it already has, plus GET /day/{on} without opened=true for the replay checks; the replay sender of the current settings
import Foundation

extension APIClient: OutboxEntriesAPI, OutboxDayAPI {
    func fetchDayUnopened(date: String) async throws -> DayDetailDTO {
        try await getJSON(path: "/day/\(date)", query: [])
    }

    /// The queue's sender over the current settings; nil while no server address is stored.
    static func liveOutboxSender() -> OutboxSending? {
        guard let client = APIClient.live() else { return nil }
        return OutboxReplay(entries: client, quickMarks: client, day: client)
    }
}
