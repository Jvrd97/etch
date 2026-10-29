// [review:need-review] PHASE-03/131
// summary: wire types of POST /health/samples — one raw HealthKit sample in exactly the six fields of the server's HealthSampleIn, the chunk around it with the sync-run bookkeeping (run id, kind, device id, chunk position), the server's answer, and the failure-by-class report of a run that died
import Foundation

/// One HealthKit sample as the device read it. Mirrors `HealthSampleIn` field for
/// field: there is no place for an hourly bucket, a daily total or a sample count,
/// so the app cannot send a derived number even by mistake. The server aggregates.
struct HealthSampleDTO: Encodable, Hashable {
    /// HealthKit type identifier, e.g. `HKQuantityTypeIdentifierStepCount`.
    let identifier: String
    let value: Double
    /// HealthKit unit string the value is expressed in, e.g. `count/min`.
    let unit: String
    /// ISO 8601 instant in UTC with milliseconds.
    let start: String
    /// Equal to `start` for an instantaneous reading.
    let end: String
    /// The device offset when the sample was recorded; places it in a lived hour.
    let utcOffsetMinutes: Int
}

/// The three kinds of run the server journal tells apart (`SyncRunKind`). A new kind is
/// a case here and a value in the server schema, not a migration.
enum HealthSyncRunKind: String, Codable, Hashable {
    case backfill
    case rolling
    /// A button press.
    case manual
}

/// A class of failure, never a message: the server stores and returns only this word
/// (`SyncFailureKind`).
enum HealthSyncFailureKindDTO: String, Codable, Hashable {
    case network
    case unit
    case unknownMetric = "unknown_metric"
    case auth
    case unknown
}

/// One chunk: accepted whole or refused whole (422 on an unknown identifier or unit).
/// The run fields are optional on the wire; the pump always fills them so the server
/// journal knows which run a chunk belongs to and how far the run got.
struct HealthSamplesRequestDTO: Encodable, Hashable {
    let samples: [HealthSampleDTO]
    /// One id per run, the same on every chunk of it.
    var syncRunId: String?
    var kind: HealthSyncRunKind?
    /// Stable per install, not the advertising id.
    var deviceId: String?
    /// Zero-based position of this chunk in the run.
    var chunkIndex: Int?
    var chunksTotal: Int?
}

/// `POST /health/sync-runs/{id}/fail`: the phone says its run died. No message field exists.
struct HealthSyncFailureDTO: Codable, Hashable {
    let failureKind: HealthSyncFailureKindDTO
    let kind: HealthSyncRunKind
    let deviceId: String?
    let chunksTotal: Int?
}

/// The answer to a failure report; only the status is read.
struct HealthSyncRunAckDTO: Decodable, Equatable {
    let status: String
}

/// What the chunk turned into on the server.
struct HealthSamplesResponseDTO: Decodable, Equatable {
    let samplesReceived: Int
    let bucketsWritten: Int
}
