// [review:need-review] PHASE-01/268
// summary: tests of the Health tab list and the metric detail state — the three ranges asked, loaded/empty/failed/not configured, offline from the read cache with its moment, a stale lag not shown as current, a failed side read hiding only its block, a refresh failure keeping the screen; detail: the latest day chosen, hours of the picked day, period switch dropping a day it no longer holds, sleep reading nights, errors in words, a late answer of a superseded period dropped
import XCTest
@testable import HabitTracker

@MainActor
final class HealthMetricsViewModelTests: XCTestCase {
    /// 2026-10-29 12:00 UTC.
    private let moment = Date(timeIntervalSince1970: 1_793_275_200)
    private var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        return calendar
    }

    private func make(_ api: MockHealthMetricsAPI, store: CacheStore = InMemoryCacheStore()) -> HealthMetricsViewModel {
        HealthMetricsViewModel(apiProvider: { api }, cacheStore: store, now: { self.moment }, calendar: calendar)
    }

    private func detail(_ api: MockHealthMetricsAPI, id: String = "HKQuantityTypeIdentifierStepCount", store: CacheStore = InMemoryCacheStore()) -> HealthMetricDetailViewModel {
        HealthMetricDetailViewModel(identifier: id, title: "t", apiProvider: { api }, cacheStore: store, now: { self.moment }, calendar: calendar)
    }

    private func offline() -> APIClientError { .transport(code: -1009) }

    // MARK: List

    func testLoadAsksThirtyDaysForMetricsAndTheWeekForNightsAndWorkouts() async {
        let api = MockHealthMetricsAPI()
        api.metricsHandler = { _, _ in HealthMetricsResponseDTO(metrics: [HealthMetricsFixtures.steps(days: [("2026-10-29", 100)])]) }
        let model = make(api)
        await model.load()
        XCTAssertEqual(model.state, .loaded)
        XCTAssertEqual(model.today, "2026-10-29")
        XCTAssertTrue(api.calls.contains("metrics 2026-09-30...2026-10-29"))
        XCTAssertTrue(api.calls.contains("sleep 2026-10-23...2026-10-29"))
        XCTAssertTrue(api.calls.contains("workouts 2026-09-30...2026-10-29"))
        XCTAssertTrue(api.calls.contains("status"))
        XCTAssertFalse(model.isCatalogEmpty)
        XCTAssertNotNil(model.syncStatus)
        XCTAssertNil(model.offlineAsOf)
    }

    func testACatalogWithoutASingleDayIsEmpty() async {
        let api = MockHealthMetricsAPI()
        api.metricsHandler = { _, _ in HealthMetricsResponseDTO(metrics: [HealthMetricsFixtures.steps(days: [])]) }
        let model = make(api)
        await model.load()
        XCTAssertEqual(model.state, .loaded)
        XCTAssertTrue(model.isCatalogEmpty)
    }

    func testOfflineServesTheCachedCatalogWithItsMomentAndDropsAStaleLag() async {
        let store = InMemoryCacheStore()
        let api = MockHealthMetricsAPI()
        api.metricsHandler = { _, _ in HealthMetricsResponseDTO(metrics: [HealthMetricsFixtures.steps(days: [("2026-10-29", 100)])]) }
        api.sleepHandler = { _, _ in HealthSleepResponseDTO(nights: [HealthMetricsFixtures.night("2026-10-29")]) }
        await make(api, store: store).load()

        let down = MockHealthMetricsAPI()
        down.metricsHandler = { _, _ in throw self.offline() }
        down.statusHandler = { throw self.offline() }
        down.sleepHandler = { _, _ in throw self.offline() }
        down.workoutsHandler = { _, _ in throw self.offline() }
        let model = make(down, store: store)
        await model.load()
        XCTAssertEqual(model.state, .loaded)
        XCTAssertEqual(model.offlineAsOf, moment)
        XCTAssertEqual(model.metrics.count, 1)
        XCTAssertNil(model.syncStatus, "a lag cached an hour ago is not the lag now")
        XCTAssertEqual(model.nights?.count, 1)
    }

    func testOfflineWithoutACacheIsAnErrorInWords() async {
        let api = MockHealthMetricsAPI()
        api.metricsHandler = { _, _ in throw self.offline() }
        let model = make(api)
        await model.load()
        XCTAssertEqual(model.state, .failure("Нет связи с сервером"))
    }

    func testAFailedSideReadHidesOnlyItsBlock() async {
        let api = MockHealthMetricsAPI()
        api.metricsHandler = { _, _ in HealthMetricsResponseDTO(metrics: [HealthMetricsFixtures.steps(days: [("2026-10-29", 100)])]) }
        api.workoutsHandler = { _, _ in throw APIClientError.unexpectedStatus(500) }
        api.statusHandler = { throw APIClientError.unexpectedStatus(500) }
        let model = make(api)
        await model.load()
        XCTAssertEqual(model.state, .loaded)
        XCTAssertNil(model.workouts)
        XCTAssertNil(model.syncStatus)
        XCTAssertNotNil(model.nights)
    }

    func testNotConfiguredIsSaidInWords() async {
        let model = HealthMetricsViewModel(apiProvider: { nil }, cacheStore: InMemoryCacheStore(), now: { self.moment }, calendar: calendar)
        await model.load()
        XCTAssertEqual(model.state, .failure("Укажите адрес сервера в More → Settings"))
    }

    func testARefreshThatFailsKeepsTheScreen() async {
        let api = MockHealthMetricsAPI()
        api.metricsHandler = { _, _ in HealthMetricsResponseDTO(metrics: [HealthMetricsFixtures.steps(days: [("2026-10-29", 100)])]) }
        let model = make(api)
        await model.load()
        api.metricsHandler = { _, _ in throw APIClientError.unexpectedStatus(503) }
        await model.refresh()
        XCTAssertEqual(model.state, .loaded)
        XCTAssertEqual(model.metrics.count, 1)
        XCTAssertEqual(model.refreshError, "Сервер ответил ошибкой 503")
    }

    // MARK: Detail

    private func days(_ pairs: [(String, Double)], id: String = "HKQuantityTypeIdentifierStepCount", kind: String = "cumulative") -> HealthMetricDaysResponseDTO {
        HealthMetricDaysResponseDTO(identifier: id, displayName: "t", kind: kind, canonicalUnit: "count", days: pairs.map { HealthDayValueDTO(date: $0.0, value: $0.1) })
    }

    func testDetailReadsThirtyDaysThenTheHoursOfTheLatestDay() async {
        let api = MockHealthMetricsAPI()
        api.daysHandler = { _, _, _ in self.days([("2026-10-27", 1), ("2026-10-28", 2)]) }
        let model = detail(api)
        await model.load()
        XCTAssertEqual(model.shownDay, "2026-10-28")
        XCTAssertEqual(api.calls, ["days HKQuantityTypeIdentifierStepCount 2026-09-30...2026-10-29", "hours HKQuantityTypeIdentifierStepCount 2026-10-28"])
        if case .ready = model.hours {} else { XCTFail("hours not read") }
    }

    func testPickingADayReadsItsHoursAndAnUnknownDayIsIgnored() async {
        let api = MockHealthMetricsAPI()
        api.daysHandler = { _, _, _ in self.days([("2026-10-27", 1), ("2026-10-28", 2)]) }
        let model = detail(api)
        await model.load()
        await model.selectDay("2026-10-27")
        XCTAssertEqual(model.shownDay, "2026-10-27")
        XCTAssertEqual(api.calls.last, "hours HKQuantityTypeIdentifierStepCount 2026-10-27")
        let count = api.calls.count
        await model.selectDay("2000-01-01")
        XCTAssertEqual(api.calls.count, count)
        XCTAssertEqual(model.shownDay, "2026-10-27")
    }

    func testAShorterPeriodDropsAPickedDayItNoLongerHolds() async {
        let api = MockHealthMetricsAPI()
        api.daysHandler = { _, from, _ in
            from == "2026-10-23"
                ? self.days([("2026-10-28", 2)])
                : self.days([("2026-10-10", 1), ("2026-10-28", 2)])
        }
        let model = detail(api)
        await model.load()
        await model.selectDay("2026-10-10")
        XCTAssertEqual(model.shownDay, "2026-10-10")
        await model.selectPeriod(7)
        XCTAssertEqual(model.periodDays, 7)
        XCTAssertEqual(model.shownDay, "2026-10-28")
        await model.selectPeriod(5)
        XCTAssertEqual(model.periodDays, 7, "only the three periods exist")
    }

    func testSleepReadsTheNightsOfThePeriodEndingAtTheShownDay() async {
        let api = MockHealthMetricsAPI()
        let sleep = HealthMetricsFormat.sleepIdentifier
        api.daysHandler = { _, _, _ in self.days([("2026-10-28", 430)], id: sleep, kind: "sleep") }
        api.sleepHandler = { _, _ in HealthSleepResponseDTO(nights: [HealthMetricsFixtures.night("2026-10-28")]) }
        let model = detail(api, id: sleep)
        await model.load()
        XCTAssertTrue(api.calls.contains("sleep 2026-09-29...2026-10-28"))
        XCTAssertFalse(api.calls.contains { $0.hasPrefix("hours") })
        XCTAssertEqual(model.nights, .ready([HealthMetricsFixtures.night("2026-10-28")]))
    }

    func testSleepIsToldByTheKindTheServerSendsNotByTheIdentifier() async {
        let api = MockHealthMetricsAPI()
        api.daysHandler = { id, _, _ in self.days([("2026-10-28", 430)], id: id, kind: "sleep") }
        let model = detail(api, id: "SomeOtherSleepType")
        await model.load()
        XCTAssertTrue(model.isSleep)
        XCTAssertFalse(api.calls.contains { $0.hasPrefix("hours") })
        XCTAssertTrue(api.calls.contains { $0.hasPrefix("sleep") })
    }

    func testDetailFailureIsInWordsAndOfflineServesTheCachedSeries() async {
        let store = InMemoryCacheStore()
        let api = MockHealthMetricsAPI()
        api.daysHandler = { _, _, _ in self.days([("2026-10-28", 2)]) }
        await detail(api, store: store).load()

        let down = MockHealthMetricsAPI()
        down.daysHandler = { _, _, _ in throw self.offline() }
        down.hoursHandler = { _, _ in throw self.offline() }
        let cached = detail(down, store: store)
        await cached.load()
        XCTAssertEqual(cached.offlineAsOf, moment)
        XCTAssertEqual(cached.shownDay, "2026-10-28")

        let broken = MockHealthMetricsAPI()
        broken.daysHandler = { _, _, _ in throw APIClientError.unauthorized }
        let failed = detail(broken)
        await failed.load()
        XCTAssertEqual(failed.days, .failure("Неверный ключ API (401)"))
    }

    func testALateAnswerOfASupersededPeriodIsDropped() async {
        let api = MockHealthMetricsAPI()
        let gate = AsyncGate()
        api.daysHandler = { _, from, _ in
            if from == "2026-10-23" { return self.days([("2026-10-28", 7)]) }
            await gate.wait()
            return self.days([("2026-10-28", 30)])
        }
        let model = detail(api)
        let slow = Task { await model.load() }
        await Task.yield()
        await model.selectPeriod(7)
        await gate.open()
        await slow.value
        XCTAssertEqual(model.series?.days.first?.value, 7)
    }
}

/// Holds an answer back until the test lets it go.
private actor AsyncGate {
    private var waiting: [CheckedContinuation<Void, Never>] = []
    private var isOpen = false

    func wait() async {
        if isOpen { return }
        await withCheckedContinuation { waiting.append($0) }
    }

    func open() {
        isOpen = true
        waiting.forEach { $0.resume() }
        waiting = []
    }
}
