// [review:need-review] PHASE-03/131
// summary: wire types of POST /health/samples — one raw HealthKit sample in exactly the six fields of the server's HealthSampleIn, the chunk around it, and the server's answer
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

/// One chunk: accepted whole or refused whole (422 on an unknown identifier or unit).
struct HealthSamplesRequestDTO: Encodable, Hashable {
    let samples: [HealthSampleDTO]
}

/// What the chunk turned into on the server.
struct HealthSamplesResponseDTO: Decodable, Equatable {
    let samplesReceived: Int
    let bucketsWritten: Int
}
