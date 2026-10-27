// [review:need-review] PHASE-03/240
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
}

extension APIClient: SupplementsAPI {
    func fetchSupplements() async throws -> [SupplementDTO] {
        try await getJSON(path: "/supplements", query: [])
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
