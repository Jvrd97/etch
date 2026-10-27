// [review:need-review] PHASE-03/131, PHASE-03/234, PHASE-03/233, PHASE-03/254
// summary: HealthKit pump — reads the last 7 days off the main thread (steps as HealthKit's deduplicated hourly sums anchored at local midnight, resting heart rate as samples), packs whole metrics into chunks of at most 50 000 records, posts them with retries on transient failures only, names a failed permission request and an unencodable body, joins concurrent callers into one run, and on launch runs only when the permission sheet was already answered
import Foundation
import HealthKit
import os

/// What one run of the pump ended with. Carries no health value: the view shows it
/// and the log names only the failure class.
enum HealthSyncOutcome: Equatable {
    /// One server answer per chunk, in sending order.
    case sent([HealthSamplesResponseDTO])
    /// HealthKit returned nothing in the window: no data, or read access is off.
    case nothingToSend
    /// No server address in Settings.
    case notConfigured
    /// Launch run that did not start: the sheet was never answered or there is no HealthKit.
    /// A button press that joined such a run gets it too.
    case skipped
    case failed(HealthSyncFailure)
}

enum HealthSyncFailure: String, Error, Equatable {
    case healthDataUnavailable
    /// HealthKit refused the permission request or the status check.
    case authorizationFailed
    case readFailed
    /// One metric alone has more samples than a chunk may hold.
    case chunkTooLarge
    case network
    case server
    case unauthorized
    /// 4xx other than 401, e.g. 422 for an unknown unit; resending would fail again.
    case rejected
    /// The body could not be encoded (a non-finite value); resending would fail again.
    case encodingFailed

    var isTransient: Bool {
        self == .network || self == .server
    }
}

/// The sync entry point the Health screen calls.
@MainActor
protocol HealthSyncing: AnyObject {
    func sync() async -> HealthSyncOutcome
}

/// Reads HealthKit and sends what it holds to `POST /health/samples`.
///
/// Cumulative metrics go as HealthKit's own hourly sums, one record per hour: only
/// HealthKit knows which of iPhone and Watch to count for a given minute, and the sums
/// match the Health app. Discrete metrics go as raw samples. The client adds nothing up
/// itself (ADR-0020, A2 with its 2026-10-27 amendment). Retrying is safe because the server
/// overwrites hourly buckets on their natural key, so a chunk sent twice changes
/// nothing. Nothing is queued on disk: HealthKit already keeps the samples, and the
/// next run reads the same window again. Health values never leave memory except
/// in the request body.
@MainActor
final class HealthPump: HealthSyncing {
    nonisolated static let windowDays = 7
    /// Server bound `MAX_SAMPLES_PER_CHUNK` in `app/schemas/health.py`.
    nonisolated static let maxSamplesPerChunk = 50_000
    nonisolated static let maxAttempts = 3
    /// Up to 50 000 samples in one body: longer than the default request budget.
    nonisolated static let uploadTimeout: TimeInterval = 60
    /// The n-th retry waits n steps.
    nonisolated static let retryDelayStep: Duration = .seconds(2)

    nonisolated static let pumpedMetrics: [HealthMetricDefinition] = HealthMetricCatalog.metrics.filter {
        [.stepCount, .restingHeartRate].contains($0.typeIdentifier)
    }

    static let shared = HealthPump(
        store: HKHealthStore(),
        api: { APIClient.live(timeout: HealthPump.uploadTimeout) }
    )

    private static let logger = Logger(subsystem: "com.habittracker.app", category: "HealthPump")

    private let store: HealthStoreQuerying
    private let api: () -> HealthSamplesAPI?
    private let metrics: [HealthMetricDefinition]
    let mapper: HealthSampleMapper
    let calendar: Calendar
    private let now: () -> Date
    private let chunkLimit: Int
    private let pause: (Int) async throws -> Void
    private var inFlight: Task<HealthSyncOutcome, Never>?

    init(
        store: HealthStoreQuerying,
        api: @escaping () -> HealthSamplesAPI?,
        metrics: [HealthMetricDefinition] = HealthPump.pumpedMetrics,
        mapper: HealthSampleMapper = HealthSampleMapper(),
        calendar: Calendar = .autoupdatingCurrent,
        now: @escaping () -> Date = Date.init,
        chunkLimit: Int = HealthPump.maxSamplesPerChunk,
        pause: @escaping (Int) async throws -> Void = { attempt in
            try await Task.sleep(for: HealthPump.retryDelayStep * attempt)
        }
    ) {
        self.store = store
        self.api = api
        self.metrics = metrics
        self.mapper = mapper
        self.calendar = calendar
        self.now = now
        self.chunkLimit = chunkLimit
        self.pause = pause
    }

    /// Button run: asks for read access if still unanswered, then sends the window.
    func sync() async -> HealthSyncOutcome {
        await joinOrStart(asking: true)
    }

    /// Launch run: never shows the sheet. Sends only after the person has answered it.
    func syncIfAuthorized() async -> HealthSyncOutcome {
        await joinOrStart(asking: false)
    }

    private func joinOrStart(asking: Bool) async -> HealthSyncOutcome {
        if let inFlight {
            return await inFlight.value
        }
        let run = Task { await self.run(asking: asking) }
        inFlight = run
        let outcome = await run.value
        inFlight = nil
        if case .failed(let failure) = outcome {
            Self.logger.error("health sync failed: \(failure.rawValue, privacy: .public)")
        }
        return outcome
    }

    private func run(asking: Bool) async -> HealthSyncOutcome {
        guard store.healthDataAvailable else {
            return asking ? .failed(.healthDataUnavailable) : .skipped
        }
        let types = Set(metrics.map { HKQuantityType($0.typeIdentifier) })
        do {
            if asking {
                try await store.requestReadAuthorization(for: types)
            } else if try await store.readAuthorizationRequestStatus(for: types) != .unnecessary {
                return .skipped
            }
        } catch let error as HKError where error.code == .errorHealthDataUnavailable {
            return .failed(.healthDataUnavailable)
        } catch {
            return .failed(.authorizationFailed)
        }
        guard let api = api() else {
            return .notConfigured
        }

        let perMetric: [[HealthSampleDTO]]
        do {
            perMetric = try await Self.readWindow(
                store: store, metrics: metrics, mapper: mapper, calendar: calendar, end: now()
            )
        } catch {
            return .failed(.readFailed)
        }
        guard perMetric.contains(where: { !$0.isEmpty }) else {
            return .nothingToSend
        }
        guard let chunks = pack(perMetric) else {
            return .failed(.chunkTooLarge)
        }

        var answers: [HealthSamplesResponseDTO] = []
        for chunk in chunks {
            switch await send(HealthSamplesRequestDTO(samples: chunk), to: api) {
            case .success(let answer):
                answers.append(answer)
            case .failure(let failure):
                return .failed(failure)
            }
        }
        return .sent(answers)
    }

    /// Today and the six days before it, from local midnight until `end`. Nonisolated,
    /// so turning thousands of samples into DTOs does not run on the main thread.
    /// The calendar and the mapper both follow the device zone, read at different moments:
    /// a zone change in the middle of one run (rare) can leave the window and the offsets
    /// in different zones. The buckets it leaves are the zone-change cost of ADR-0020, A2.
    private nonisolated static func readWindow(
        store: HealthStoreQuerying,
        metrics: [HealthMetricDefinition],
        mapper: HealthSampleMapper,
        calendar: Calendar,
        end: Date
    ) async throws -> [[HealthSampleDTO]] {
        let today = calendar.startOfDay(for: end)
        guard let start = calendar.date(byAdding: .day, value: 1 - windowDays, to: today) else {
            return []
        }
        var perMetric: [[HealthSampleDTO]] = []
        for metric in metrics {
            let type = HKQuantityType(metric.typeIdentifier)
            switch metric.kind {
            case .cumulative:
                let hours = try await Self.hourlySumsOrEmpty(store, type, from: start, to: end)
                perMetric.append(hours.compactMap { mapper.dto($0, metric: metric) })
            case .discrete:
                let samples = try await store.quantitySamples(of: type, from: start, to: end)
                perMetric.append(samples.map { mapper.dto($0, metric: metric) })
            }
        }
        return perMetric
    }

    /// HealthKit throws `.errorNoData` for a window it holds nothing in: that is an empty
    /// week, not a failed read. Any other error stays one.
    private nonisolated static func hourlySumsOrEmpty(
        _ store: HealthStoreQuerying, _ type: HKQuantityType, from: Date, to: Date
    ) async throws -> [HealthHourSum] {
        do {
            return try await store.hourlySums(of: type, from: from, to: to)
        } catch let error as HKError where error.code == .errorNoData {
            return []
        }
    }

    /// Whole metrics per chunk. The server overwrites an hour with what the chunk
    /// holds for it, so one metric split over two chunks would lose part of an hour.
    /// Returns nil when a single metric does not fit.
    private func pack(_ perMetric: [[HealthSampleDTO]]) -> [[HealthSampleDTO]]? {
        var chunks: [[HealthSampleDTO]] = []
        var current: [HealthSampleDTO] = []
        for samples in perMetric where !samples.isEmpty {
            guard samples.count <= chunkLimit else {
                return nil
            }
            if current.count + samples.count > chunkLimit {
                chunks.append(current)
                current = []
            }
            current.append(contentsOf: samples)
        }
        if !current.isEmpty {
            chunks.append(current)
        }
        return chunks
    }

    private func send(
        _ request: HealthSamplesRequestDTO, to api: HealthSamplesAPI
    ) async -> Result<HealthSamplesResponseDTO, HealthSyncFailure> {
        var attempt = 1
        while true {
            do {
                return .success(try await api.postHealthSamples(request))
            } catch {
                let failure = Self.classify(error)
                guard failure.isTransient, attempt < Self.maxAttempts else {
                    return .failure(failure)
                }
                do {
                    try await pause(attempt)
                } catch {
                    // Cancelled while waiting: stop with the failure that caused the wait.
                    return .failure(failure)
                }
                attempt += 1
            }
        }
    }

    private static func classify(_ error: Error) -> HealthSyncFailure {
        if error is EncodingError {
            return .encodingFailed
        }
        switch error as? APIClientError {
        case .timeout, .transport:
            return .network
        case .unauthorized:
            return .unauthorized
        case .unexpectedStatus(let status) where (400..<500).contains(status):
            return .rejected
        case .invalidBaseURL:
            return .rejected
        case .unexpectedStatus, .invalidResponse:
            return .server
        case nil:
            return .network
        }
    }
}
