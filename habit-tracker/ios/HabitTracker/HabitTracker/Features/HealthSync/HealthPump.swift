// [review:need-review] PHASE-03/131, PHASE-03/234, PHASE-03/233, PHASE-03/254, PHASE-03/132, PHASE-03/238, PHASE-03/272
// summary: HealthKit pump — reads the last 7 days of the whole catalogue off the main thread (cumulative types as HealthKit's deduplicated hourly sums anchored at local midnight, discrete types as samples, sleep as raw stage intervals from 18:00 the evening before the window so its first night is whole, other category types as intervals clipped to the window; a type with no data or no read access is skipped, not a failed run), asks read access for all of them in one sheet, packs whole metrics into chunks of at most 50 000 records, posts them with retries on transient failures only, names a failed permission request and an unencodable body, joins concurrent callers into one run, on launch runs only when the permission sheet was already answered, and tags every chunk with a run id, kind, device id and position so the server journal sees one run — a run that dies on a chunk is reported by class (kept in UserDefaults until the server has it) and never shown as a success
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
/// match the Health app. Discrete metrics go as raw samples, sleep as raw stage intervals
/// that the server folds into nights. The client adds nothing up
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

    nonisolated static let pumpedMetrics: [HealthMetricDefinition] = HealthMetricCatalog.metrics
    nonisolated static let pumpedCategories: [HealthCategoryDefinition] = HealthCategoryCatalog.categories

    static let shared = HealthPump(
        store: HKHealthStore(),
        api: { APIClient.live(timeout: HealthPump.uploadTimeout) },
        syncLog: HealthSyncLog.shared
    )

    private static let logger = Logger(subsystem: "com.habittracker.app", category: "HealthPump")

    private let store: HealthStoreQuerying
    private let api: () -> HealthSamplesAPI?
    private let metrics: [HealthMetricDefinition]
    private let categories: [HealthCategoryDefinition]
    let mapper: HealthSampleMapper
    let calendar: Calendar
    private let now: () -> Date
    private let deviceId: () -> String
    private let makeRunId: () -> UUID
    private let pendingFailures: HealthPendingFailureStoring
    private let chunkLimit: Int
    private let pause: (Int) async throws -> Void
    private let syncLog: HealthSyncLogging
    private var inFlight: Task<HealthSyncOutcome, Never>?

    init(
        store: HealthStoreQuerying,
        api: @escaping () -> HealthSamplesAPI?,
        syncLog: HealthSyncLogging,
        metrics: [HealthMetricDefinition] = HealthPump.pumpedMetrics,
        categories: [HealthCategoryDefinition] = HealthPump.pumpedCategories,
        mapper: HealthSampleMapper = HealthSampleMapper(),
        calendar: Calendar = .autoupdatingCurrent,
        now: @escaping () -> Date = Date.init,
        deviceId: @escaping () -> String = HealthDeviceID.current,
        makeRunId: @escaping () -> UUID = UUID.init,
        pendingFailures: HealthPendingFailureStoring = UserDefaultsPendingFailures(),
        chunkLimit: Int = HealthPump.maxSamplesPerChunk,
        pause: @escaping (Int) async throws -> Void = { attempt in
            try await Task.sleep(for: HealthPump.retryDelayStep * attempt)
        }
    ) {
        self.store = store
        self.api = api
        self.syncLog = syncLog
        self.metrics = metrics
        self.categories = categories
        self.mapper = mapper
        self.calendar = calendar
        self.now = now
        self.deviceId = deviceId
        self.makeRunId = makeRunId
        self.pendingFailures = pendingFailures
        self.chunkLimit = chunkLimit
        self.pause = pause
    }

    /// Button run: asks for read access if still unanswered, then sends the window.
    func sync() async -> HealthSyncOutcome {
        await joinOrStart(asking: true, source: .manual)
    }

    /// Launch run: never shows the sheet. Sends only after the person has answered it.
    func syncIfAuthorized(source: HealthSyncSource = .appLaunch) async -> HealthSyncOutcome {
        await joinOrStart(asking: false, source: source)
    }

    private func joinOrStart(asking: Bool, source: HealthSyncSource) async -> HealthSyncOutcome {
        if let inFlight {
            return await inFlight.value
        }
        let run = Task { await self.run(asking: asking) }
        inFlight = run
        let outcome = await run.value
        inFlight = nil
        syncLog.record(outcome, source: source, kind: asking ? .manual : .rolling, at: now())
        if case .failed(let failure) = outcome {
            Self.logger.error("health sync failed: \(failure.rawValue, privacy: .public)")
        }
        return outcome
    }

    private func run(asking: Bool) async -> HealthSyncOutcome {
        guard store.healthDataAvailable else {
            return asking ? .failed(.healthDataUnavailable) : .skipped
        }
        let quantityTypes: [HKObjectType] = metrics.map { HKQuantityType($0.typeIdentifier) }
        let categoryTypes: [HKObjectType] = categories.map { HKCategoryType($0.typeIdentifier) }
        let types = Set(quantityTypes + categoryTypes)
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

        await deliverPendingFailures(to: api)

        let perMetric: [HealthChunk]
        do {
            perMetric = try await Self.readWindow(
                store: store, metrics: metrics, categories: categories, mapper: mapper,
                calendar: calendar, end: now()
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

        let runId = makeRunId().uuidString
        let kind: HealthSyncRunKind = asking ? .manual : .rolling
        let device = deviceId()
        var answers: [HealthSamplesResponseDTO] = []
        for (index, chunk) in chunks.enumerated() {
            let request = HealthSamplesRequestDTO(
                samples: chunk.samples, categorySamples: chunk.categorySamples,
                syncRunId: runId, kind: kind, deviceId: device,
                chunkIndex: index, chunksTotal: chunks.count
            )
            switch await send(request, to: api) {
            case .success(let answer):
                answers.append(answer)
            case .failure(let failure):
                await report(failure, runId: runId, kind: kind, device: device, chunksTotal: chunks.count, to: api)
                return .failed(failure)
            }
        }
        return .sent(answers)
    }

    /// Today and the six days before it, from local midnight until `end`; a category type
    /// starts its `lead` earlier (sleep: 18:00 the evening before). Nonisolated,
    /// so turning thousands of samples into DTOs does not run on the main thread.
    /// The calendar and the mapper both follow the device zone, read at different moments:
    /// a zone change in the middle of one run (rare) can leave the window and the offsets
    /// in different zones. The buckets it leaves are the zone-change cost of ADR-0020, A2.
    private nonisolated static func readWindow(
        store: HealthStoreQuerying,
        metrics: [HealthMetricDefinition],
        categories: [HealthCategoryDefinition],
        mapper: HealthSampleMapper,
        calendar: Calendar,
        end: Date
    ) async throws -> [HealthChunk] {
        let today = calendar.startOfDay(for: end)
        guard let start = calendar.date(byAdding: .day, value: 1 - windowDays, to: today) else {
            return []
        }
        var perMetric: [HealthChunk] = []
        for metric in metrics {
            let type = HKQuantityType(metric.typeIdentifier)
            switch metric.kind {
            case .cumulative:
                let hours = try await Self.readable { try await store.hourlySums(of: type, from: start, to: end) }
                perMetric.append(HealthChunk(samples: hours.compactMap { mapper.dto($0, metric: metric) }))
            case .discrete:
                let samples = try await Self.readable { try await store.quantitySamples(of: type, from: start, to: end) }
                perMetric.append(HealthChunk(samples: samples.map { mapper.dto($0, metric: metric) }))
            }
        }
        for category in categories {
            let from = start.addingTimeInterval(-category.lead)
            let samples = try await Self.readable {
                try await store.categorySamples(of: HKCategoryType(category.typeIdentifier), from: from, to: end)
            }
            let notBefore = category.clipsToWindow ? from : nil
            perMetric.append(HealthChunk(categorySamples: samples.map {
                mapper.dto($0, category: category, notBefore: notBefore)
            }))
        }
        return perMetric
    }

    /// Errors that say "nothing to read for this type", not "the read broke".
    private nonisolated static let unreadable: [HKError.Code] = [
        // A window HealthKit holds nothing in (the statistics query throws it).
        .errorNoData,
        // Read access to this one type is off, or was never asked: a type the catalogue
        // gained after the person answered the sheet.
        .errorAuthorizationDenied,
        .errorAuthorizationNotDetermined,
    ]

    /// One type's read, where a type HealthKit will not give is an empty week for that
    /// type and the run goes on with the others. Any other error fails the run.
    private nonisolated static func readable<Record>(
        _ read: () async throws -> [Record]
    ) async throws -> [Record] {
        do {
            return try await read()
        } catch let error as HKError where unreadable.contains(error.code) {
            return []
        }
    }

    /// Whole metrics per chunk. The server overwrites an hour (or a night) with what the
    /// chunk holds for it, so one metric split over two chunks would lose part of it.
    /// Returns nil when a single metric does not fit.
    private func pack(_ perMetric: [HealthChunk]) -> [HealthChunk]? {
        var chunks: [HealthChunk] = []
        var current = HealthChunk()
        for metric in perMetric where !metric.isEmpty {
            guard metric.count <= chunkLimit else {
                return nil
            }
            if current.count + metric.count > chunkLimit {
                chunks.append(current)
                current = HealthChunk()
            }
            current.append(metric)
        }
        if !current.isEmpty {
            chunks.append(current)
        }
        return chunks
    }

    /// Tells the server its run died, by class. The report is written down first and
    /// removed only once the server has it: when the cause is the network the report
    /// cannot arrive now, and the next run delivers it. A 4xx refusal is already
    /// journaled by the server itself, and a 401 cannot be reported to the server that
    /// just refused the key.
    private func report(
        _ failure: HealthSyncFailure, runId: String, kind: HealthSyncRunKind, device: String,
        chunksTotal: Int, to api: HealthSamplesAPI
    ) async {
        let failureKind: HealthSyncFailureKindDTO
        switch failure {
        case .network:
            failureKind = .network
        case .server, .encodingFailed:
            failureKind = .unknown
        default:
            return
        }
        let pending = HealthPendingFailure(
            runId: runId,
            report: HealthSyncFailureDTO(
                failureKind: failureKind, kind: kind, deviceId: device, chunksTotal: chunksTotal
            )
        )
        pendingFailures.save(pendingFailures.load() + [pending])
        await deliverPendingFailures(to: api)
    }

    /// Sends the kept reports oldest first and stops at the first that does not arrive.
    private func deliverPendingFailures(to api: HealthSamplesAPI) async {
        var waiting = pendingFailures.load()
        while let next = waiting.first {
            do {
                _ = try await api.postHealthSyncFailure(runId: next.runId, next.report)
            } catch {
                Self.logger.info("health sync failure report not delivered")
                return
            }
            waiting.removeFirst()
            pendingFailures.save(waiting)
        }
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

/// The records of one chunk, or of one metric before packing: quantity samples and
/// category samples travel in the same request under two keys.
struct HealthChunk: Equatable {
    var samples: [HealthSampleDTO] = []
    var categorySamples: [HealthCategorySampleDTO] = []

    var count: Int { samples.count + categorySamples.count }
    var isEmpty: Bool { count == 0 }

    mutating func append(_ other: HealthChunk) {
        samples += other.samples
        categorySamples += other.categorySamples
    }
}
