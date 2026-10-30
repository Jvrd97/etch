// [review:need-review] PHASE-01/268
// summary: state of one metric's detail screen — the daily series of a switchable period (7/30/90), the chosen day (the latest while none is picked, dropped when a shorter period no longer holds it), its 24 hours for a quantity metric or the nights of the period ending at that day for sleep; every read goes through the read cache, a late answer of a superseded period or day is dropped
import Foundation

@MainActor
final class HealthMetricDetailViewModel: ObservableObject {
    enum Phase<Value: Equatable>: Equatable {
        case loading
        case failure(String)
        case ready(Value)
    }

    let identifier: String
    let title: String

    @Published private(set) var periodDays = HealthMetricsFormat.defaultPeriodDays
    @Published private(set) var days: Phase<HealthMetricDaysResponseDTO> = .loading
    @Published private(set) var pickedDay: String?
    @Published private(set) var hours: Phase<HealthMetricHoursResponseDTO> = .loading
    @Published private(set) var nights: Phase<[HealthSleepNightDTO]> = .loading
    /// Set while the series on screen is the cached one: when it was fetched.
    @Published private(set) var offlineAsOf: Date?

    private let apiProvider: () -> HealthMetricsAPI?
    private let cache: ReadThroughCache
    private let now: () -> Date
    private let calendar: Calendar
    private var daysGeneration = 0
    private var dayGeneration = 0

    init(
        identifier: String,
        title: String,
        apiProvider: @escaping () -> HealthMetricsAPI?,
        cacheStore: CacheStore,
        now: @escaping () -> Date = Date.init,
        calendar: Calendar = .current
    ) {
        self.identifier = identifier
        self.title = title
        self.apiProvider = apiProvider
        self.cache = ReadThroughCache(store: cacheStore, now: now)
        self.now = now
        self.calendar = calendar
    }

    static func live(identifier: String, title: String) -> HealthMetricDetailViewModel {
        HealthMetricDetailViewModel(
            identifier: identifier, title: title, apiProvider: { APIClient.live() }, cacheStore: ReadCacheLive.shared
        )
    }

    static func daysKey(_ identifier: String, period: Int) -> String { "health.days.\(identifier).\(period)" }
    static func hoursKey(_ identifier: String, day: String) -> String { "health.hours.\(identifier).\(day)" }
    static func nightsKey(_ period: Int, to day: String) -> String { "health.nights.\(period).\(day)" }

    /// Sleep is told by the kind the server sends, as on the web; its nights replace the hours.
    var isSleep: Bool { series?.kind == "sleep" }

    var series: HealthMetricDaysResponseDTO? {
        if case .ready(let value) = days { return value }
        return nil
    }

    /// The picked day while the series still holds it, otherwise the latest day.
    var shownDay: String? {
        guard let series else { return nil }
        if let pickedDay, series.days.contains(where: { $0.date == pickedDay }) { return pickedDay }
        return series.days.last?.date
    }

    func load() async {
        await readDays()
    }

    func selectPeriod(_ period: Int) async {
        guard period != periodDays, HealthMetricsFormat.periods.contains(where: { $0.days == period }) else { return }
        periodDays = period
        await readDays()
    }

    func selectDay(_ day: String) async {
        guard let series, series.days.contains(where: { $0.date == day }), day != shownDay else { return }
        pickedDay = day
        await readDay()
    }

    private func readDays() async {
        daysGeneration += 1
        let mine = daysGeneration
        days = .loading
        guard let api = apiProvider() else {
            days = .failure(HealthMetricsFormat.notConfiguredMessage)
            return
        }
        let today = HealthMetricsFormat.localDate(now(), calendar: calendar)
        let from = HealthMetricsFormat.shiftDate(today, by: 1 - periodDays)
        let identifier = identifier
        do {
            let outcome = try await cache.load(key: Self.daysKey(identifier, period: periodDays)) {
                try await api.fetchHealthMetricDays(identifier: identifier, dateFrom: from, dateTo: today)
            }
            guard mine == daysGeneration else { return }
            switch outcome {
            case .fresh(let value):
                offlineAsOf = nil
                days = .ready(value)
            case .stale(let value, let updatedAt):
                offlineAsOf = updatedAt
                days = .ready(value)
            }
        } catch let error as APIClientError {
            guard mine == daysGeneration else { return }
            days = .failure(HealthMetricsFormat.message(for: error))
            return
        } catch {
            guard mine == daysGeneration else { return }
            days = .failure(HealthMetricsFormat.loadFailedMessage)
            return
        }
        await readDay()
    }

    /// The part under the day list: the hours of the shown day, or for sleep the nights ending at it.
    private func readDay() async {
        guard let day = shownDay, let api = apiProvider() else { return }
        dayGeneration += 1
        let mine = dayGeneration
        let identifier = identifier
        if isSleep {
            nights = .loading
            let period = periodDays
            let from = HealthMetricsFormat.shiftDate(day, by: 1 - period)
            let result = await phase(key: Self.nightsKey(period, to: day)) {
                try await api.fetchHealthSleep(dateFrom: from, dateTo: day)
            }
            guard mine == dayGeneration else { return }
            nights = result.map { $0.nights }
        } else {
            hours = .loading
            let result = await phase(key: Self.hoursKey(identifier, day: day)) {
                try await api.fetchHealthMetricHours(identifier: identifier, date: day)
            }
            guard mine == dayGeneration else { return }
            hours = result
        }
    }

    private func phase<T: Codable & Equatable>(
        key: String, fetch: () async throws -> T
    ) async -> Phase<T> {
        do {
            switch try await cache.load(key: key, fetch: fetch) {
            case .fresh(let value), .stale(let value, _): return .ready(value)
            }
        } catch let error as APIClientError {
            return .failure(HealthMetricsFormat.message(for: error))
        } catch {
            return .failure(HealthMetricsFormat.loadFailedMessage)
        }
    }
}

private extension HealthMetricDetailViewModel.Phase {
    func map<Other: Equatable>(_ transform: (Value) -> Other) -> HealthMetricDetailViewModel.Phase<Other> {
        switch self {
        case .loading: return .loading
        case .failure(let message): return .failure(message)
        case .ready(let value): return .ready(transform(value))
        }
    }
}
