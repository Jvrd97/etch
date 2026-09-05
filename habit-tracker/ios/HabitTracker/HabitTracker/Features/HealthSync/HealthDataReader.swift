// [review:need-review] PHASE-02/65
// summary: read-only HealthKit authorization and latest-sample queries for every catalog type

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
    private let store: HKHealthStore

    init(store: HKHealthStore = HKHealthStore()) {
        self.store = store
    }

    func requestReadAuthorization(for identifiers: Set<String>) async throws {
        guard HKHealthStore.isHealthDataAvailable() else {
            throw HealthDataReaderError.healthDataUnavailable
        }
        let selected = HealthMetricCatalog.metrics.filter { identifiers.contains($0.identifier) }
        guard selected.count == identifiers.count else {
            throw HealthDataReaderError.unknownIdentifiers
        }
        let readTypes: Set<HKObjectType> = Set(
            selected.map { HKQuantityType($0.typeIdentifier) }
        )
        try await store.requestAuthorization(toShare: [], read: readTypes)
    }

    func readLatestValues(for metrics: [HealthMetricDefinition]) async throws -> [String: Double] {
        var values: [String: Double] = [:]
        for metric in metrics {
            let type = HKQuantityType(metric.typeIdentifier)
            let descriptor = HKSampleQueryDescriptor(
                predicates: [.quantitySample(type: type)],
                sortDescriptors: [SortDescriptor(\.startDate, order: .reverse)],
                limit: 1
            )
            if let sample = try await descriptor.result(for: store).first {
                values[metric.identifier] = sample.quantity.doubleValue(for: HKUnit(from: metric.unit))
            }
        }
        return values
    }
}
