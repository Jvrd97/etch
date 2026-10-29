// [review:need-review] PHASE-03/240, PHASE-03/258
// summary: SupplementsAPI — GET /supplements, POST /supplements, POST /supplements/{id}/intakes under an Idempotency-Key; APIClient implements it on the shared request helpers, and the queue's replay takes the intake write through OutboxSupplementsAPI
import Foundation

/// The one supplement write the offline queue replays. `APIClient` is the production implementation.
protocol OutboxSupplementsAPI {
    /// The mark «принял». With `intakeDate` the server checks it against its own day (409 when it differs).
    func markIntake(
        supplementID: Int, intakeDate: String?, idempotencyKey: String
    ) async throws -> SupplementIntakeDTO
}

/// API surface of the Supplements screen; `APIClient` is the production implementation.
protocol SupplementsAPI: OutboxSupplementsAPI {
    /// Active supplements in the order they were added, with `taken_today`.
    func fetchSupplements() async throws -> [SupplementDTO]
    func createSupplement(_ payload: SupplementCreateDTO) async throws -> SupplementDTO
    /// The zone and day-start hour the server cuts its day by.
    func fetchDayRule() async throws -> ServerDayRule
}

extension APIClient: SupplementsAPI {
    func fetchSupplements() async throws -> [SupplementDTO] {
        try await getJSON(path: "/supplements", query: [])
    }

    /// Read from the window of the running week: the one place the app gets the rule from.
    func fetchDayRule() async throws -> ServerDayRule {
        let window = try await fetchWeekReview(iso: nil).window
        return ServerDayRule(timeZoneID: window.timezone, dayStartHour: window.dayStartHour)
    }

    func createSupplement(_ payload: SupplementCreateDTO) async throws -> SupplementDTO {
        try await sendJSON(path: "/supplements", method: "POST", body: payload)
    }

    func markIntake(
        supplementID: Int, intakeDate: String?, idempotencyKey: String
    ) async throws -> SupplementIntakeDTO {
        try await sendJSON(
            path: "/supplements/\(supplementID)/intakes", method: "POST",
            body: SupplementIntakeRequestDTO(intakeDate: intakeDate), idempotencyKey: idempotencyKey
        )
    }
}
