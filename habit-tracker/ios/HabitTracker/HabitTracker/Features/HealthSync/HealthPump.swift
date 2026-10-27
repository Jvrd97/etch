// [review:need-review] PHASE-03/131
// summary: HealthKit pump — reads steps and resting heart rate for the last 7 days, packs whole metrics into chunks of at most 50 000 samples, posts them with retries on transient failures only, joins concurrent callers into one run, and on launch runs only when the permission sheet was already answered
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
    case skipped
    case failed(HealthSyncFailure)
}

enum HealthSyncFailure: String, Error, Equatable {
    case healthDataUnavailable
    case readFailed
    /// One metric alone has more samples than a chunk may hold.
    case chunkTooLarge
    case network
    case server
    case unauthorized
    /// 4xx other than 401, e.g. 422 for an unknown unit; resending would fail again.
    case rejected

    var isTransient: Bool {
        self == .network || self == .server
    }
}

/// The sync entry point the Health screen calls.
@MainActor
protocol HealthSyncing: AnyObject {
    func sync() async -> HealthSyncOutcome
}

/// Reads raw samples from HealthKit and sends them to `POST /health/samples`.
///
/// The client computes nothing (ADR-0020, A2). Retrying is safe because the server
/// overwrites hourly buckets on their natural key, so a chunk sent twice changes
/// nothing. Nothing is queued on disk: HealthKit already keeps the samples, and the
/// next run reads the same window again. Health values never leave memory except
/// in the request body.
@MainActor
final class HealthPump: HealthSyncing {
    static let windowDays = 7
    /// Server bound `MAX_SAMPLES_PER_CHUNK` in `app/schemas/health.py`.
    static let maxSamplesPerChunk = 50_000
    static let maxAttempts = 3
    /// Up to 50 000 samples in one body: longer than the default request budget.
    static let uploadTimeout: TimeInterval = 60
    /// The n-th retry waits n steps.
    static let retryDelayStep: Duration = .seconds(2)

    static let pumpedMetrics: [HealthMetricDefinition] = HealthMetricCatalog.metrics.filter {
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
    private let mapper: HealthSampleMapper
    private let calendar: Calendar
    private let now: () -> Date
    private let chunkLimit: Int
    private let pause: (Int) async throws -> Void
    private var inFlight: Task<HealthSyncOutcome, Never>?

    init(
        store: HealthStoreQuerying,
        api: @escaping () -> HealthSamplesAPI?,
        metrics: [HealthMetricDefinition] = HealthPump.pumpedMetrics,
        mapper: HealthSampleMapper = HealthSampleMapper(timeZone: .current),
        calendar: Calendar = .current,
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
        } catch {
            return .failed(.healthDataUnavailable)
        }
        guard let api = api() else {
            return .notConfigured
        }

        let perMetric: [[HealthSampleDTO]]
        do {
            perMetric = try await readWindow()
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

    /// Today and the six days before it, from local midnight until now.
    private func readWindow() async throws -> [[HealthSampleDTO]] {
        let end = now()
        let today = calendar.startOfDay(for: end)
        guard let start = calendar.date(byAdding: .day, value: 1 - Self.windowDays, to: today) else {
            return []
        }
        var perMetric: [[HealthSampleDTO]] = []
        for metric in metrics {
            let samples = try await store.quantitySamples(
                of: HKQuantityType(metric.typeIdentifier), from: start, to: end
            )
            perMetric.append(samples.map { mapper.dto($0, metric: metric) })
        }
        return perMetric
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
