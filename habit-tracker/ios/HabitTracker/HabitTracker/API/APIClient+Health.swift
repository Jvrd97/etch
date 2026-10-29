// [review:need-review] PHASE-03/131
// summary: POST /api/v1/health/samples — sends one chunk of raw samples; no Idempotency-Key, because the server overwrites hourly buckets on their natural key and a re-sent chunk changes nothing; POST /health/sync-runs/{id}/fail reports a dead run by class
import Foundation

/// Raw-sample intake (`/api/v1/health/samples`). `APIClient` is the production implementation.
protocol HealthSamplesAPI {
    func postHealthSamples(_ request: HealthSamplesRequestDTO) async throws -> HealthSamplesResponseDTO
    func postHealthSyncFailure(runId: String, _ report: HealthSyncFailureDTO) async throws -> HealthSyncRunAckDTO
}

extension APIClient: HealthSamplesAPI {
    func postHealthSamples(_ request: HealthSamplesRequestDTO) async throws -> HealthSamplesResponseDTO {
        try await sendJSON(path: "/health/samples", method: "POST", body: request)
    }

    func postHealthSyncFailure(runId: String, _ report: HealthSyncFailureDTO) async throws -> HealthSyncRunAckDTO {
        try await sendJSON(path: "/health/sync-runs/\(runId)/fail", method: "POST", body: report)
    }
}
