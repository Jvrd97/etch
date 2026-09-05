// [review:need-review] PHASE-02/65
// summary: Health section tests for its 24-type catalog, first-entry authorization, complete reads, and empty values

import XCTest
@testable import HabitTracker

@MainActor
final class HealthSyncViewModelTests: XCTestCase {
    func testCatalogContainsExactlyTwentyFourTypesInFourGroups() {
        let metrics = HealthMetricCatalog.metrics

        XCTAssertEqual(metrics.count, 24)
        XCTAssertEqual(Set(metrics.map(\.identifier)).count, 24)
        XCTAssertEqual(Dictionary(grouping: metrics, by: \.group).mapValues(\.count), [
            .movement: 7,
            .heart: 7,
            .body: 5,
            .nutrition: 5,
        ])
    }

    func testFirstEntryRequestsReadOnlyAuthorizationAndReadsEveryTypeOnce() async {
        let reader = HealthDataReaderSpy()
        let viewModel = HealthSyncViewModel(reader: reader)

        await viewModel.enterSection()
        await viewModel.enterSection()

        XCTAssertEqual(reader.authorizationRequests, 1)
        XCTAssertEqual(reader.requestedIdentifiers, Set(HealthMetricCatalog.metrics.map(\.identifier)))
        XCTAssertEqual(reader.readIdentifiers, Set(HealthMetricCatalog.metrics.map(\.identifier)))
        XCTAssertEqual(reader.readCalls, 1)
    }

    func testMissingSamplesRemainExplicitlyEmpty() async {
        let viewModel = HealthSyncViewModel(reader: HealthDataReaderSpy())

        await viewModel.enterSection()

        XCTAssertEqual(viewModel.rows.count, 24)
        XCTAssertTrue(viewModel.rows.allSatisfy { $0.value == nil })
    }
}

@MainActor
private final class HealthDataReaderSpy: HealthDataReading {
    private(set) var authorizationRequests = 0
    private(set) var requestedIdentifiers: Set<String> = []
    private(set) var readCalls = 0
    private(set) var readIdentifiers: Set<String> = []

    func requestReadAuthorization(for identifiers: Set<String>) async throws {
        authorizationRequests += 1
        requestedIdentifiers = identifiers
    }

    func readLatestValues(for metrics: [HealthMetricDefinition]) async throws -> [String: Double] {
        readCalls += 1
        readIdentifiers = Set(metrics.map(\.identifier))
        return [:]
    }
}
