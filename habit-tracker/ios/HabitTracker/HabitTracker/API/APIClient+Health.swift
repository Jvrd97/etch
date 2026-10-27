// [review:need-review] PHASE-03/131
// summary: POST /api/v1/health/samples — sends one chunk of raw samples; no Idempotency-Key, because the server overwrites hourly buckets on their natural key and a re-sent chunk changes nothing
import Foundation

/// Raw-sample intake (`/api/v1/health/samples`). `APIClient` is the production implementation.
protocol HealthSamplesAPI {
    func postHealthSamples(_ request: HealthSamplesRequestDTO) async throws -> HealthSamplesResponseDTO
}

extension APIClient: HealthSamplesAPI {
    func postHealthSamples(_ request: HealthSamplesRequestDTO) async throws -> HealthSamplesResponseDTO {
        try await sendJSON(path: "/health/samples", method: "POST", body: request)
    }
}
