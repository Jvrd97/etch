// [review:need-review] PHASE-03/131, PHASE-03/234, PHASE-03/233, PHASE-03/254, PHASE-03/238, PHASE-03/272, PHASE-02/70
// summary: the one read-only seam over HKHealthStore (availability, request status, read request for quantity and category types, samples of a window, category samples overlapping a window, HealthKit's deduplicated hourly sums, the latest sample) workouts started in a window read into plain records (type, interval, active time, energy, distance, average and maximum heart rate from the workout's own statistics), and the mapping of a sample or an hourly sum to the six-field wire DTO, of a category sample to the five-field one and of a workout to its DTO with the start's offset, its start optionally clipped to the reading window
import Foundation
import HealthKit

/// One hour of a cumulative metric as HealthKit's statistics report it: the sum is
/// already deduplicated across sources (iPhone and Watch) by the source priority the
/// Health app uses. `sum` is nil for an hour HealthKit holds no data for.
struct HealthHourSum: Equatable {
    let start: Date
    let end: Date
    let sum: HKQuantity?
}

/// One `HKWorkout` reduced to what the wire carries. The numbers come from the workout's
/// own statistics, which HealthKit fills from the samples recorded during it; a number the
/// workout has no statistics for (no watch, no heart-rate permission) is nil.
struct HealthWorkoutRecord: Equatable {
    let uuid: UUID
    let activityType: HKWorkoutActivityType
    let start: Date
    let end: Date
    /// Active time, as `HKWorkout.duration` reports it.
    let duration: TimeInterval
    let energyKcal: Double?
    let distanceM: Double?
    let avgHeartRate: Double?
    let maxHeartRate: Double?
    /// `HKMetadataKeyTimeZone`, when the workout recorded where it was done.
    let timeZoneName: String?

    private static let distanceTypes: [HKQuantityTypeIdentifier] = {
        var types: [HKQuantityTypeIdentifier] = [
            .distanceWalkingRunning, .distanceCycling, .distanceSwimming, .distanceWheelchair,
            .distanceDownhillSnowSports,
        ]
        if #available(iOS 18.0, *) {
            types += [.distanceCrossCountrySkiing, .distancePaddleSports, .distanceRowing, .distanceSkatingSports]
        }
        return types
    }()
    private static let beatsPerMinute = HKUnit.count().unitDivided(by: .minute())

    init(
        uuid: UUID, activityType: HKWorkoutActivityType, start: Date, end: Date, duration: TimeInterval,
        energyKcal: Double? = nil, distanceM: Double? = nil, avgHeartRate: Double? = nil,
        maxHeartRate: Double? = nil, timeZoneName: String? = nil
    ) {
        self.uuid = uuid
        self.activityType = activityType
        self.start = start
        self.end = end
        self.duration = duration
        self.energyKcal = energyKcal
        self.distanceM = distanceM
        self.avgHeartRate = avgHeartRate
        self.maxHeartRate = maxHeartRate
        self.timeZoneName = timeZoneName
    }

    init(_ workout: HKWorkout) {
        let heartRate = workout.statistics(for: HKQuantityType(.heartRate))
        // A workout carries one distance statistic for its sport; sum so a multisport
        // session (swim and run) does not lose a leg.
        let distances = Self.distanceTypes.compactMap {
            workout.statistics(for: HKQuantityType($0))?.sumQuantity()?.doubleValue(for: .meter())
        }
        self.init(
            uuid: workout.uuid,
            activityType: workout.workoutActivityType,
            start: workout.startDate,
            end: workout.endDate,
            duration: workout.duration,
            energyKcal: workout.statistics(for: HKQuantityType(.activeEnergyBurned))?
                .sumQuantity()?.doubleValue(for: .kilocalorie()),
            distanceM: distances.isEmpty ? nil : distances.reduce(0, +),
            avgHeartRate: heartRate?.averageQuantity()?.doubleValue(for: Self.beatsPerMinute),
            maxHeartRate: heartRate?.maximumQuantity()?.doubleValue(for: Self.beatsPerMinute),
            timeZoneName: workout.metadata?[HKMetadataKeyTimeZone] as? String
        )
    }
}

/// Everything the app reads from `HKHealthStore`, for the pump and the Health screen
/// alike. Read-only by construction: no method takes a share set, so the app cannot
/// ask to write health data. Tests use a fake. `Sendable`: the pump reads it off the main actor.
protocol HealthStoreQuerying: Sendable {
    var healthDataAvailable: Bool { get }
    /// `.unnecessary` once the person has answered the sheet for these types.
    func readAuthorizationRequestStatus(for types: Set<HKObjectType>) async throws -> HKAuthorizationRequestStatus
    /// Shows the system sheet if any type is still unanswered; otherwise returns at once.
    func requestReadAuthorization(for types: Set<HKObjectType>) async throws
    /// Raw samples that start inside `[from, to)`, oldest first. For discrete metrics.
    func quantitySamples(of type: HKQuantityType, from: Date, to: Date) async throws -> [HKQuantitySample]
    /// Hour-long sums covering `[from, to)`, anchored at `from`. For cumulative metrics.
    /// A window with no data at all may throw `HKError.errorNoData`; the pump reads that as an empty week.
    func hourlySums(of type: HKQuantityType, from: Date, to: Date) async throws -> [HealthHourSum]
    /// Category samples (sleep intervals) overlapping `[from, to)`, oldest first.
    func categorySamples(of type: HKCategoryType, from: Date, to: Date) async throws -> [HKCategorySample]
    /// Workouts that start inside `[from, to)`, oldest first. A workout belongs to the day
    /// it started, so one that began before the window is not this window's.
    func workouts(from: Date, to: Date) async throws -> [HealthWorkoutRecord]
    /// The most recent sample of the type, if any.
    func latestSample(of type: HKQuantityType) async throws -> HKQuantitySample?
}

extension HKHealthStore: HealthStoreQuerying {
    var healthDataAvailable: Bool { HKHealthStore.isHealthDataAvailable() }

    func readAuthorizationRequestStatus(for types: Set<HKObjectType>) async throws -> HKAuthorizationRequestStatus {
        try await statusForAuthorizationRequest(toShare: [], read: types)
    }

    func requestReadAuthorization(for types: Set<HKObjectType>) async throws {
        try await requestAuthorization(toShare: [], read: types)
    }

    func quantitySamples(of type: HKQuantityType, from: Date, to: Date) async throws -> [HKQuantitySample] {
        // Strict start matches how the server places a discrete reading: in the hour
        // it started. Every hour of the window then gets all of its readings, and no
        // hour before the window is touched.
        let window = HKQuery.predicateForSamples(withStart: from, end: to, options: .strictStartDate)
        let descriptor = HKSampleQueryDescriptor(
            predicates: [.quantitySample(type: type, predicate: window)],
            sortDescriptors: [SortDescriptor(\.startDate)]
        )
        return try await descriptor.result(for: self)
    }

    func hourlySums(of type: HKQuantityType, from: Date, to: Date) async throws -> [HealthHourSum] {
        // Samples overlapping the window are included: HealthKit prorates a sample
        // across the hours it spans, so the first hour of the window is whole.
        let window = HKQuery.predicateForSamples(withStart: from, end: to)
        let descriptor = HKStatisticsCollectionQueryDescriptor(
            predicate: .quantitySample(type: type, predicate: window),
            options: .cumulativeSum,
            anchorDate: from,
            intervalComponents: DateComponents(hour: 1)
        )
        let collection = try await descriptor.result(for: self)
        var hours: [HealthHourSum] = []
        collection.enumerateStatistics(from: from, to: to) { statistics, _ in
            hours.append(HealthHourSum(
                start: statistics.startDate, end: statistics.endDate, sum: statistics.sumQuantity()
            ))
        }
        return hours
    }

    func categorySamples(of type: HKCategoryType, from: Date, to: Date) async throws -> [HKCategorySample] {
        // Overlap, not strict start: the server places an interval by its end, and an
        // interval that began before the window still belongs to a night inside it.
        let window = HKQuery.predicateForSamples(withStart: from, end: to)
        let descriptor = HKSampleQueryDescriptor(
            predicates: [.categorySample(type: type, predicate: window)],
            sortDescriptors: [SortDescriptor(\.startDate)]
        )
        return try await descriptor.result(for: self)
    }

    func workouts(from: Date, to: Date) async throws -> [HealthWorkoutRecord] {
        let window = HKQuery.predicateForSamples(withStart: from, end: to, options: .strictStartDate)
        let descriptor = HKSampleQueryDescriptor(
            predicates: [.workout(window)],
            sortDescriptors: [SortDescriptor(\.startDate)]
        )
        return try await descriptor.result(for: self).map(HealthWorkoutRecord.init)
    }

    func latestSample(of type: HKQuantityType) async throws -> HKQuantitySample? {
        let descriptor = HKSampleQueryDescriptor(
            predicates: [.quantitySample(type: type)],
            sortDescriptors: [SortDescriptor(\.startDate, order: .reverse)],
            limit: 1
        )
        return try await descriptor.result(for: self).first
    }
}

/// Turns a HealthKit sample or hourly sum into the wire DTO. No arithmetic on values:
/// the quantity is only read in the catalogue's HealthKit unit and labelled with the
/// unit the server canonicalises from.
struct HealthSampleMapper {
    private static let secondsPerMinute = 60

    /// The device zone, read live: a change of zone applies without restarting the app.
    /// A sample that recorded its own zone (`HKMetadataKeyTimeZone`) wins.
    let timeZone: TimeZone

    init(timeZone: TimeZone = .autoupdatingCurrent) {
        self.timeZone = timeZone
    }

    func dto(_ sample: HKQuantitySample, metric: HealthMetricDefinition) -> HealthSampleDTO {
        dto(
            metric: metric, quantity: sample.quantity,
            start: sample.startDate, end: sample.endDate, zone: zone(of: sample)
        )
    }

    /// The raw category value (a sleep stage) and the interval, nothing derived. The offset
    /// is the one at the end: the server names a night by the local date it ended on, and
    /// places a count in the hour of its end. `notBefore` cuts an interval that began
    /// before the reading window at the window's start; the end never moves.
    func dto(
        _ sample: HKCategorySample, category: HealthCategoryDefinition, notBefore: Date? = nil
    ) -> HealthCategorySampleDTO {
        HealthCategorySampleDTO(
            identifier: category.identifier,
            value: sample.value,
            start: Self.wireInstant(max(sample.startDate, notBefore ?? sample.startDate)),
            end: Self.wireInstant(sample.endDate),
            utcOffsetMinutes: zone(of: sample).secondsFromGMT(for: sample.endDate) / Self.secondsPerMinute
        )
    }

    /// The workout with the offset at its start: the server names its day by the start.
    func dto(_ workout: HealthWorkoutRecord) -> HealthWorkoutDTO {
        HealthWorkoutDTO(
            uuid: workout.uuid.uuidString,
            activityType: HealthWorkoutActivity.name(of: workout.activityType),
            start: Self.wireInstant(workout.start),
            end: Self.wireInstant(workout.end),
            utcOffsetMinutes: zone(named: workout.timeZoneName).secondsFromGMT(for: workout.start)
                / Self.secondsPerMinute,
            durationSeconds: workout.duration,
            energyKcal: workout.energyKcal,
            distanceM: workout.distanceM,
            avgHeartRate: workout.avgHeartRate,
            maxHeartRate: workout.maxHeartRate
        )
    }

    /// Nil for an empty hour: absent data is not sent as a zero.
    func dto(_ hour: HealthHourSum, metric: HealthMetricDefinition) -> HealthSampleDTO? {
        guard let sum = hour.sum else {
            return nil
        }
        // Statistics carry no per-sample zone: the hour is lived in the device zone,
        // as the Health app shows it.
        return dto(metric: metric, quantity: sum, start: hour.start, end: hour.end, zone: timeZone)
    }

    private func dto(
        metric: HealthMetricDefinition, quantity: HKQuantity, start: Date, end: Date, zone: TimeZone
    ) -> HealthSampleDTO {
        HealthSampleDTO(
            identifier: metric.identifier,
            value: quantity.doubleValue(for: HKUnit(from: metric.unit)),
            unit: metric.wireUnit,
            start: Self.wireInstant(start),
            end: Self.wireInstant(end),
            utcOffsetMinutes: zone.secondsFromGMT(for: start) / Self.secondsPerMinute
        )
    }

    private func zone(of sample: HKSample) -> TimeZone {
        zone(named: sample.metadata?[HKMetadataKeyTimeZone] as? String)
    }

    private func zone(named name: String?) -> TimeZone {
        if let name, let recorded = TimeZone(identifier: name) {
            return recorded
        }
        return timeZone
    }

    // ISO8601DateFormatter is thread-safe; one instance serves every sample.
    private static let formatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        formatter.timeZone = TimeZone(identifier: "UTC")
        return formatter
    }()

    private static func wireInstant(_ date: Date) -> String {
        formatter.string(from: date)
    }
}
