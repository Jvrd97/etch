// [review:need-review] PHASE-02/65, PHASE-03/131, PHASE-03/233, PHASE-03/254
// summary: Health section tests for its 24-type catalog, first-entry authorization, complete reads, empty values, the sync button with its result text (a joined launch run and a failed permission request named in words), and the latest-value reader over the one HealthKit seam

import HealthKit
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
        let viewModel = HealthSyncViewModel(reader: reader, syncer: HealthSyncerSpy())

        await viewModel.enterSection()
        await viewModel.enterSection()

        XCTAssertEqual(reader.authorizationRequests, 1)
        XCTAssertEqual(reader.requestedIdentifiers, Set(HealthMetricCatalog.metrics.map(\.identifier)))
        XCTAssertEqual(reader.readIdentifiers, Set(HealthMetricCatalog.metrics.map(\.identifier)))
        XCTAssertEqual(reader.readCalls, 1)
    }

    func testMissingSamplesRemainExplicitlyEmpty() async {
        let viewModel = HealthSyncViewModel(reader: HealthDataReaderSpy(), syncer: HealthSyncerSpy())

        await viewModel.enterSection()

        XCTAssertEqual(viewModel.rows.count, 24)
        XCTAssertTrue(viewModel.rows.allSatisfy { $0.value == nil })
    }

    func testSyncButtonShowsWhatTheServerWrote() async {
        let syncer = HealthSyncerSpy()
        syncer.outcome = .sent([HealthSamplesResponseDTO(samplesReceived: 412, bucketsWritten: 96)])
        let viewModel = HealthSyncViewModel(reader: HealthDataReaderSpy(), syncer: syncer)

        await viewModel.syncNow()

        XCTAssertEqual(syncer.calls, 1)
        XCTAssertEqual(viewModel.syncState, .finished(syncer.outcome))
        XCTAssertEqual(viewModel.syncMessage, "Отправлено: принято семплов 412, записано часов 96")
    }

    func testEmptyWeekPointsToSettingsInsteadOfAnEmptyChart() async {
        let syncer = HealthSyncerSpy()
        syncer.outcome = .nothingToSend
        let viewModel = HealthSyncViewModel(reader: HealthDataReaderSpy(), syncer: syncer)

        await viewModel.syncNow()

        XCTAssertTrue(viewModel.syncMessage?.contains("Настройк") ?? false)
    }

    func testFailureIsNamedWithoutAnyValue() async {
        let syncer = HealthSyncerSpy()
        syncer.outcome = .failed(.network)
        let viewModel = HealthSyncViewModel(reader: HealthDataReaderSpy(), syncer: syncer)

        await viewModel.syncNow()

        XCTAssertEqual(viewModel.syncMessage, "Сервер недоступен. Данные остались в «Здоровье», повторите позже")
    }

    func testButtonThatJoinedTheSkippedLaunchRunDoesNotPromiseAnotherPressHelps() async throws {
        let syncer = HealthSyncerSpy()
        syncer.outcome = .skipped
        let viewModel = HealthSyncViewModel(reader: HealthDataReaderSpy(), syncer: syncer)

        await viewModel.syncNow()

        // The same outcome also reaches an iPad, where a second press changes nothing.
        XCTAssertEqual(
            viewModel.syncMessage,
            "Отправка при запуске ничего не отправила: на этом устройстве нет данных «Здоровья» или доступ к ним ещё не запрошен"
        )
        XCTAssertFalse(try XCTUnwrap(viewModel.syncMessage).contains("ещё раз"))
    }

    func testFailedPermissionRequestIsNotCalledMissingData() async {
        let syncer = HealthSyncerSpy()
        syncer.outcome = .failed(.authorizationFailed)
        let viewModel = HealthSyncViewModel(reader: HealthDataReaderSpy(), syncer: syncer)

        await viewModel.syncNow()

        XCTAssertEqual(
            viewModel.syncMessage,
            "Не удалось запросить доступ к «Здоровью». Проверьте доступ в Настройках и повторите"
        )
    }

    func testReaderAsksReadOnlyAndReadsLatestValuesThroughTheSharedSeam() async throws {
        let store = FakeHealthStore()
        store.latest[.restingHeartRate] = FakeHealthStore.sample(
            .restingHeartRate, 54, HKUnit(from: "count/min"), "2026-10-20T03:00:00Z"
        )
        let reader = HealthKitDataReader(store: store)
        let metrics = HealthPump.pumpedMetrics

        try await reader.requestReadAuthorization(for: Set(metrics.map(\.identifier)))
        let values = try await reader.readLatestValues(for: metrics)

        XCTAssertEqual(store.authorizationRequests, [Set(metrics.map(\.identifier))])
        XCTAssertEqual(values, [HKQuantityTypeIdentifier.restingHeartRate.rawValue: 54])
    }

    func testReaderOnADeviceWithoutHealthDataAsksNothing() async {
        let store = FakeHealthStore()
        store.available = false
        let reader = HealthKitDataReader(store: store)

        do {
            try await reader.requestReadAuthorization(for: [HKQuantityTypeIdentifier.stepCount.rawValue])
            XCTFail("expected healthDataUnavailable")
        } catch {
            XCTAssertEqual(error as? HealthDataReaderError, .healthDataUnavailable)
        }
        XCTAssertTrue(store.authorizationRequests.isEmpty)
    }
}

@MainActor
private final class HealthSyncerSpy: HealthSyncing {
    var outcome: HealthSyncOutcome = .nothingToSend
    private(set) var calls = 0

    func sync() async -> HealthSyncOutcome {
        calls += 1
        return outcome
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
