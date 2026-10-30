// [review:need-review] PHASE-02/65, PHASE-03/233, PHASE-03/238, PHASE-03/272, PHASE-02/70
// summary: read-only HealthKit authorization (the whole quantity and category catalogue and the workout type, cycle tracking never, in one sheet) and latest-sample reads for every catalog type, a type without read access left empty, over the same HealthStoreQuerying seam the pump uses

import Foundation
import HealthKit

@MainActor
protocol HealthDataReading {
    func requestReadAuthorization(for identifiers: Set<String>) async throws
    func readLatestValues(for metrics: [HealthMetricDefinition]) async throws -> [String: Double]
}

enum HealthDataReaderError: Error {
    case healthDataUnavailable
    case unknownIdentifiers
}

@MainActor
final class HealthKitDataReader: HealthDataReading {
    private let store: HealthStoreQuerying

    init(store: HealthStoreQuerying = HKHealthStore()) {
        self.store = store
    }

    func requestReadAuthorization(for identifiers: Set<String>) async throws {
        guard store.healthDataAvailable else {
            throw HealthDataReaderError.healthDataUnavailable
        }
        let quantities: [HKObjectType] = HealthMetricCatalog.metrics
            .filter { identifiers.contains($0.identifier) }
            .map { HKQuantityType($0.typeIdentifier) }
        let categories: [HKObjectType] = HealthCategoryCatalog.categories
            .filter { identifiers.contains($0.identifier) }
            .map { HKCategoryType($0.typeIdentifier) }
        let workouts: [HKObjectType] = identifiers.contains(HealthWorkoutCatalog.identifier)
            ? [HealthWorkoutCatalog.objectType] : []
        guard quantities.count + categories.count + workouts.count == identifiers.count else {
            throw HealthDataReaderError.unknownIdentifiers
        }
        try await store.requestReadAuthorization(for: Set(quantities + categories + workouts))
    }

    /// A type the person did not allow (or was never asked about) has no value; the rest
    /// still read. Any other HealthKit error fails the read.
    func readLatestValues(for metrics: [HealthMetricDefinition]) async throws -> [String: Double] {
        var values: [String: Double] = [:]
        for metric in metrics {
            let sample: HKQuantitySample?
            do {
                sample = try await store.latestSample(of: HKQuantityType(metric.typeIdentifier))
            } catch let error as HKError where Self.notAllowed.contains(error.code) {
                continue
            }
            if let sample {
                values[metric.identifier] = sample.quantity.doubleValue(for: HKUnit(from: metric.unit))
            }
        }
        return values
    }

    private static let notAllowed: [HKError.Code] = [.errorAuthorizationDenied, .errorAuthorizationNotDetermined]
}
