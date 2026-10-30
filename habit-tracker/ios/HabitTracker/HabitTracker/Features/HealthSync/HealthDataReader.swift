// [review:need-review] PHASE-02/65, PHASE-03/233, PHASE-03/238
// summary: read-only HealthKit authorization (quantity catalogue and category types such as sleep, in one sheet) and latest-sample reads for every catalog type, over the same HealthStoreQuerying seam the pump uses

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
        guard quantities.count + categories.count == identifiers.count else {
            throw HealthDataReaderError.unknownIdentifiers
        }
        try await store.requestReadAuthorization(for: Set(quantities + categories))
    }

    func readLatestValues(for metrics: [HealthMetricDefinition]) async throws -> [String: Double] {
        var values: [String: Double] = [:]
        for metric in metrics {
            if let sample = try await store.latestSample(of: HKQuantityType(metric.typeIdentifier)) {
                values[metric.identifier] = sample.quantity.doubleValue(for: HKUnit(from: metric.unit))
            }
        }
        return values
    }
}
