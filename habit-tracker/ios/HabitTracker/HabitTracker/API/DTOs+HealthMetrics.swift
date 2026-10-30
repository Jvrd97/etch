// [review:need-review] PHASE-01/268
// summary: wire types of the Health read side — GET /health/metrics (catalogue with days and baseline), /metrics/{id}/days, /metrics/{id}/hours, /sleep, /workouts and /sync-status; Codable so the read cache keeps the last answer; instants stay strings because the clock the phone lived at is part of the text
import Foundation

struct HealthDayValueDTO: Codable, Equatable {
    /// `yyyy-MM-dd`.
    let date: String
    let value: Double
}

/// The metric's own usual level and where its latest day stands against it.
struct HealthBaselineDTO: Codable, Equatable {
    let mean: Double
    let stddev: Double
    let days: Int
    /// The day the deviation is about; not the shown last day for a cumulative metric.
    let day: String
    let deviation: Double
    let outsideTypical: Bool
}

struct HealthMetricSeriesDTO: Codable, Equatable, Identifiable {
    let identifier: String
    let displayName: String
    let group: String
    let kind: String
    let canonicalUnit: String
    /// Empty for a metric the phone never filled.
    let days: [HealthDayValueDTO]
    let baseline: HealthBaselineDTO?

    var id: String { identifier }
}

struct HealthMetricsResponseDTO: Codable, Equatable {
    let metrics: [HealthMetricSeriesDTO]
}

struct HealthMetricDaysResponseDTO: Codable, Equatable {
    let identifier: String
    let displayName: String
    let kind: String
    let canonicalUnit: String
    let days: [HealthDayValueDTO]
}

/// One local hour that holds data; an hour without data is absent.
struct HealthHourValueDTO: Codable, Equatable {
    let hour: Int
    let value: Double
    let min: Double
    let max: Double
    let sampleCount: Int
}

struct HealthMetricHoursResponseDTO: Codable, Equatable {
    let identifier: String
    let displayName: String
    let kind: String
    let canonicalUnit: String
    let date: String
    let hours: [HealthHourValueDTO]
}

/// One night, named by the date the person woke up on. `bedtime`/`wakeTime` carry the phone's own offset.
struct HealthSleepNightDTO: Codable, Equatable {
    let date: String
    let bedtime: String
    let wakeTime: String
    let inBedMin: Double
    let asleepMin: Double
    let awakeMin: Double
    let coreMin: Double
    let deepMin: Double
    let remMin: Double
    let unspecifiedMin: Double
}

struct HealthSleepResponseDTO: Codable, Equatable {
    let nights: [HealthSleepNightDTO]
}

/// One workout; a number HealthKit did not hold is `nil`, never zero.
struct HealthWorkoutRecordDTO: Codable, Equatable, Identifiable {
    let id: String
    let activityType: String
    let activityLabel: String
    let date: String
    let start: String
    let end: String
    let durationMin: Double
    let energyKcal: Double?
    let distanceM: Double?
    let avgHeartRate: Double?
    let maxHeartRate: Double?
}

struct HealthWorkoutsResponseDTO: Codable, Equatable {
    let workouts: [HealthWorkoutRecordDTO]
}

/// One journal row. `status` and `failureKind` stay words so a value the app does not know yet still decodes.
struct HealthSyncRunDTO: Codable, Equatable {
    let syncRunId: String
    let kind: String
    /// `running`, `ok` or `failed`.
    let status: String
    let interrupted: Bool
    let failureKind: String?
    let startedAt: String
    let finishedAt: String?
    let samplesReceived: Int
    let bucketsWritten: Int
    let chunksDone: Int
    let chunksTotal: Int?
}

/// Is the pump alive: the latest run of each kind and how stale the data is.
struct HealthSyncStatusDTO: Codable, Equatable {
    let lastRuns: [HealthSyncRunDTO]
    let lastSuccessAt: String?
    /// Hours since the last successful run finished; `nil` when none ever did.
    let lagHours: Double?
    let interrupted: Bool
}
