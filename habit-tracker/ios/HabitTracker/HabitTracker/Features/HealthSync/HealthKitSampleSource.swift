// [review:need-review] PHASE-03/131
// summary: the read-only slice of HKHealthStore the pump uses (availability, request status, read request, samples of a window) and the mapping of one HKQuantitySample to the six-field wire DTO
import Foundation
import HealthKit

/// What the pump needs from `HKHealthStore`. Read-only by construction: no method
/// takes a share set, so the app cannot ask to write health data. Tests use a fake.
protocol HealthStoreQuerying {
    var healthDataAvailable: Bool { get }
    /// `.unnecessary` once the person has answered the sheet for these types.
    func readAuthorizationRequestStatus(for types: Set<HKQuantityType>) async throws -> HKAuthorizationRequestStatus
    /// Shows the system sheet if any type is still unanswered; otherwise returns at once.
    func requestReadAuthorization(for types: Set<HKQuantityType>) async throws
    /// Samples that start inside `[from, to)`, oldest first.
    func quantitySamples(of type: HKQuantityType, from: Date, to: Date) async throws -> [HKQuantitySample]
}

extension HKHealthStore: HealthStoreQuerying {
    var healthDataAvailable: Bool { HKHealthStore.isHealthDataAvailable() }

    func readAuthorizationRequestStatus(for types: Set<HKQuantityType>) async throws -> HKAuthorizationRequestStatus {
        try await statusForAuthorizationRequest(toShare: [], read: types)
    }

    func requestReadAuthorization(for types: Set<HKQuantityType>) async throws {
        try await requestAuthorization(toShare: [], read: types)
    }

    func quantitySamples(of type: HKQuantityType, from: Date, to: Date) async throws -> [HKQuantitySample] {
        // Strict start: a sample begun before the window is left out whole. Taking it
        // would resend a partial hour of the previous day, and the server overwrites
        // that hour with the part it was given.
        let window = HKQuery.predicateForSamples(withStart: from, end: to, options: .strictStartDate)
        let descriptor = HKSampleQueryDescriptor(
            predicates: [.quantitySample(type: type, predicate: window)],
            sortDescriptors: [SortDescriptor(\.startDate)]
        )
        return try await descriptor.result(for: self)
    }
}

/// Turns one HealthKit sample into the wire DTO. No arithmetic on values: the
/// quantity is only read in the catalogue unit the server canonicalises from.
struct HealthSampleMapper {
    private static let secondsPerMinute = 60

    /// The device zone; a sample that recorded its own zone (`HKMetadataKeyTimeZone`) wins.
    let timeZone: TimeZone

    func dto(_ sample: HKQuantitySample, metric: HealthMetricDefinition) -> HealthSampleDTO {
        HealthSampleDTO(
            identifier: metric.identifier,
            value: sample.quantity.doubleValue(for: HKUnit(from: metric.unit)),
            unit: metric.unit,
            start: Self.wireInstant(sample.startDate),
            end: Self.wireInstant(sample.endDate),
            utcOffsetMinutes: zone(of: sample).secondsFromGMT(for: sample.startDate) / Self.secondsPerMinute
        )
    }

    private func zone(of sample: HKQuantitySample) -> TimeZone {
        if let name = sample.metadata?[HKMetadataKeyTimeZone] as? String,
           let recorded = TimeZone(identifier: name) {
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
