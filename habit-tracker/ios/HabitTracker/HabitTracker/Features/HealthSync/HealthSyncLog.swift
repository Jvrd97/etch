// [review:need-review] PHASE-03/273
// summary: on-device journal of health sync runs — a ring buffer of 500 entries in a JSON file (time, source, run kind, counts, outcome class; never a metric value), and the pure maths of arrival intervals and day/week summaries
import Foundation
import os

/// What started a run.
enum HealthSyncSource: String, Codable, Equatable, CaseIterable {
    /// The app came to the front and ran the pump.
    case appLaunch
    /// HealthKit woke the app in the background (#133).
    case backgroundWake
    /// A button press on the Health screen.
    case manual
}

/// Failure classes are plain strings, so the journal can store them.
extension HealthSyncFailure: Codable {}

/// How a run ended, by class. Holds no health value and no error text.
enum HealthSyncLogOutcome: Codable, Equatable {
    /// Samples reached the server.
    case ok
    case nothingToSend
    case notConfigured
    case skipped
    case failed(HealthSyncFailure)
}

/// One run. The only numbers are counts of samples and chunks.
struct HealthSyncLogEntry: Codable, Equatable, Identifiable {
    let id: UUID
    let at: Date
    let source: HealthSyncSource
    let kind: HealthSyncRunKind
    /// Samples the server accepted, summed over the chunks. Zero when nothing arrived.
    let samples: Int
    /// Chunks the server answered.
    let chunks: Int
    let outcome: HealthSyncLogOutcome

    /// Data reached the server: the only outcome that counts as an arrival.
    var isArrival: Bool { outcome == .ok }
}

protocol HealthSyncLogStoring: AnyObject {
    func load() -> [HealthSyncLogEntry]
    func save(_ entries: [HealthSyncLogEntry])
}

/// The journal in a JSON file in Application Support: it must survive a restart, and
/// 500 short entries are too many for `UserDefaults`.
final class FileHealthSyncLogStore: HealthSyncLogStoring {
    private static let logger = Logger(subsystem: "com.habittracker.app", category: "HealthSyncLog")
    private let url: URL

    init(url: URL) {
        self.url = url
    }

    static func defaultURL() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("health-sync-log.json")
    }

    func load() -> [HealthSyncLogEntry] {
        guard let data = try? Data(contentsOf: url) else {
            return []
        }
        return (try? Self.decoder.decode([HealthSyncLogEntry].self, from: data)) ?? []
    }

    func save(_ entries: [HealthSyncLogEntry]) {
        do {
            try FileManager.default.createDirectory(
                at: url.deletingLastPathComponent(), withIntermediateDirectories: true
            )
            try Self.encoder.encode(entries).write(to: url, options: .atomic)
        } catch {
            Self.logger.error("health sync log not saved")
        }
    }

    private static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }()

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }()
}

@MainActor
protocol HealthSyncLogging: AnyObject {
    func record(_ outcome: HealthSyncOutcome, source: HealthSyncSource, at: Date)
}

/// The ring buffer. The oldest entries go first once `capacity` is reached.
@MainActor
final class HealthSyncLog: HealthSyncLogging {
    static let capacity = 500

    static let shared = HealthSyncLog(store: FileHealthSyncLogStore(url: FileHealthSyncLogStore.defaultURL()))

    private let store: HealthSyncLogStoring
    private let capacity: Int
    private let makeId: () -> UUID
    private var cached: [HealthSyncLogEntry]?

    init(
        store: HealthSyncLogStoring,
        capacity: Int = HealthSyncLog.capacity,
        makeId: @escaping () -> UUID = UUID.init
    ) {
        self.store = store
        self.capacity = capacity
        self.makeId = makeId
    }

    /// Oldest first.
    var entries: [HealthSyncLogEntry] {
        if let cached {
            return cached
        }
        let loaded = store.load()
        cached = loaded
        return loaded
    }

    /// Writes down the end of one run. Takes only the counts out of the outcome.
    func record(_ outcome: HealthSyncOutcome, source: HealthSyncSource, at: Date) {
        var samples = 0
        var chunks = 0
        let logged: HealthSyncLogOutcome
        switch outcome {
        case .sent(let answers):
            samples = answers.reduce(0) { $0 + $1.samplesReceived }
            chunks = answers.count
            logged = .ok
        case .nothingToSend:
            logged = .nothingToSend
        case .notConfigured:
            logged = .notConfigured
        case .skipped:
            logged = .skipped
        case .failed(let failure):
            logged = .failed(failure)
        }
        append(HealthSyncLogEntry(
            id: makeId(), at: at, source: source,
            kind: source == .manual ? .manual : .rolling,
            samples: samples, chunks: chunks, outcome: logged
        ))
    }

    func append(_ entry: HealthSyncLogEntry) {
        let kept = Array((entries + [entry]).suffix(capacity))
        cached = kept
        store.save(kept)
    }
}

/// Arrivals in a window: how many, how far apart, when the last one was.
struct HealthSyncLogSummary: Equatable {
    let arrivals: Int
    /// Gaps between neighbouring arrivals inside the window; nil with fewer than two arrivals.
    let medianInterval: TimeInterval?
    let longestInterval: TimeInterval?
    /// Latest arrival of the whole journal, not only of the window.
    let lastArrival: Date?
}

enum HealthSyncLogMath {
    static let day: TimeInterval = 24 * 60 * 60
    static let week: TimeInterval = 7 * day

    /// Gaps between neighbouring arrivals, oldest first. `entries` come oldest first.
    static func intervals(_ entries: [HealthSyncLogEntry]) -> [TimeInterval] {
        let times = entries.filter(\.isArrival).map(\.at)
        return zip(times, times.dropFirst()).map { $1.timeIntervalSince($0) }
    }

    /// Time since the previous arrival for every arrival; nil for the first one.
    static func gapsBeforeArrivals(_ entries: [HealthSyncLogEntry]) -> [UUID: TimeInterval] {
        var result: [UUID: TimeInterval] = [:]
        var previous: Date?
        for entry in entries where entry.isArrival {
            if let previous {
                result[entry.id] = entry.at.timeIntervalSince(previous)
            }
            previous = entry.at
        }
        return result
    }

    static func summary(_ entries: [HealthSyncLogEntry], window: TimeInterval, now: Date) -> HealthSyncLogSummary {
        let inWindow = entries.filter { $0.at >= now.addingTimeInterval(-window) && $0.at <= now }
        let gaps = intervals(inWindow).sorted()
        return HealthSyncLogSummary(
            arrivals: inWindow.filter(\.isArrival).count,
            medianInterval: median(gaps),
            longestInterval: gaps.last,
            lastArrival: entries.last(where: \.isArrival)?.at
        )
    }

    private static func median(_ sorted: [TimeInterval]) -> TimeInterval? {
        guard !sorted.isEmpty else {
            return nil
        }
        let middle = sorted.count / 2
        return sorted.count.isMultiple(of: 2) ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle]
    }
}
