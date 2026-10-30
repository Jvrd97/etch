// [review:need-review] PHASE-03/131, PHASE-03/238, PHASE-02/70
// summary: wire types of POST /health/samples — one raw HealthKit sample in exactly the six fields of the server's HealthSampleIn, one category sample (a sleep interval with its raw stage) in the five fields of HealthCategorySampleIn, one workout in the fields of HealthWorkoutIn, the chunk around them with the sync-run bookkeeping (run id, kind, device id, chunk position), the server's answer, and the failure-by-class report of a run that died
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

/// One HealthKit category sample (a sleep interval). Mirrors `HealthCategorySampleIn`:
/// the raw category value and the interval, nothing folded. For sleep the value is
/// `HKCategoryValueSleepAnalysis` (0 in bed, 1 asleep, 2 awake, 3 core, 4 deep, 5 REM);
/// the server turns intervals into nights by wake date.
struct HealthCategorySampleDTO: Encodable, Hashable {
    let identifier: String
    let value: Int
    /// ISO 8601 instant in UTC with milliseconds.
    let start: String
    let end: String
    /// The device offset at the end of the interval.
    let utcOffsetMinutes: Int
}

/// One `HKWorkout`. Mirrors `HealthWorkoutIn`: HealthKit's own UUID makes a window read
/// again on every sync an overwrite on the server. A number HealthKit does not hold for
/// the workout (no watch, no heart-rate permission) is nil and left out of the body,
/// never sent as zero.
struct HealthWorkoutDTO: Encodable, Hashable {
    let uuid: String
    /// `HKWorkoutActivityType` in snake_case, e.g. `running`; `other` for a type the app
    /// has no name for.
    let activityType: String
    /// ISO 8601 instants in UTC with milliseconds.
    let start: String
    let end: String
    /// The device offset at the start: it names the day the workout belongs to.
    let utcOffsetMinutes: Int
    /// Active time as HealthKit reports it (a paused run is shorter than end minus start).
    let durationSeconds: Double
    let energyKcal: Double?
    let distanceM: Double?
    let avgHeartRate: Double?
    let maxHeartRate: Double?
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
    /// Category types; each night the chunk touches arrives whole.
    var categorySamples: [HealthCategorySampleDTO] = []
    /// Workouts, each under its own UUID.
    var workouts: [HealthWorkoutDTO] = []
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
    /// Hourly buckets and sleep nights the chunk wrote.
    let bucketsWritten: Int
}
