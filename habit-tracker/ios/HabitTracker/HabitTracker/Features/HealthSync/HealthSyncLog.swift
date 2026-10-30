// [review:need-review] PHASE-03/273, PHASE-03/272
// summary: on-device journal of health sync runs — a ring buffer of 500 entries in a JSON file (time, source, run kind, counts, outcome class, the type identifier of a metric a run left out; never a metric value), and the pure maths of arrival intervals and day/week summaries
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
    /// Samples the server accepted, summed over the chunks: the size of the 7-day window
    /// that was sent, not the new data. Zero when nothing arrived.
    let samples: Int
    /// Chunks the server answered.
    let chunks: Int
    let outcome: HealthSyncLogOutcome
    /// The one metric this entry is about, when a run left a metric out (its HealthKit
    /// type identifier, never a value); nil for a whole run. Absent in older files.
    var metric: String?

    /// Data reached the server: the only outcome that counts as an arrival.
    var isArrival: Bool { outcome == .ok }
}

protocol HealthSyncLogStoring: AnyObject {
    func load() -> [HealthSyncLogEntry]
    func save(_ entries: [HealthSyncLogEntry])
}

/// The journal in a JSON file in Application Support: it must survive a restart, and
/// 500 short entries are too many for `UserDefaults`.
///
/// A file that exists but cannot be read whole is copied to `.bak` before anything is
/// written over it; a single broken entry is skipped, the rest is kept.
final class FileHealthSyncLogStore: HealthSyncLogStoring {
    private static let logger = Logger(subsystem: "com.habittracker.app", category: "HealthSyncLog")
    /// Readable after the first unlock, so a background write on a locked phone works.
    static let writeOptions: Data.WritingOptions = [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
    private let url: URL
    /// The file could neither be read nor backed up: writing would destroy it.
    private var mustNotOverwrite = false

    init(url: URL) {
        self.url = url
    }

    static func defaultURL() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("health-sync-log.json")
    }

    var backupURL: URL { url.appendingPathExtension("bak") }

    func load() -> [HealthSyncLogEntry] {
        let data: Data
        do {
            data = try Data(contentsOf: url)
        } catch let error as CocoaError where error.code == .fileReadNoSuchFile || error.code == .fileNoSuchFile {
            return []
        } catch {
            Self.logger.error("health sync log not readable")
            keepBackup()
            return []
        }
        guard let lossy = try? Self.decoder.decode([LossyEntry].self, from: data) else {
            Self.logger.error("health sync log is not valid JSON")
            keepBackup()
            return []
        }
        let entries = lossy.compactMap(\.entry)
        if entries.count != lossy.count {
            Self.logger.error("health sync log: broken entries skipped")
            keepBackup()
        }
        return entries
    }

    func save(_ entries: [HealthSyncLogEntry]) {
        guard !mustNotOverwrite else {
            return
        }
        do {
            try FileManager.default.createDirectory(
                at: url.deletingLastPathComponent(), withIntermediateDirectories: true
            )
            try Self.encoder.encode(entries).write(to: url, options: Self.writeOptions)
        } catch {
            Self.logger.error("health sync log not saved")
        }
    }

    private func keepBackup() {
        let manager = FileManager.default
        try? manager.removeItem(at: backupURL)
        do {
            try manager.copyItem(at: url, to: backupURL)
        } catch {
            Self.logger.error("health sync log backup failed")
            mustNotOverwrite = true
        }
    }

    /// One entry that fails to decode becomes nil instead of failing the whole array.
    private struct LossyEntry: Decodable {
        let entry: HealthSyncLogEntry?

        init(from decoder: Decoder) throws {
            entry = try? HealthSyncLogEntry(from: decoder)
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
    func record(_ outcome: HealthSyncOutcome, source: HealthSyncSource, kind: HealthSyncRunKind, at: Date)
    /// One metric a run left out, by class (`chunkTooLarge`), next to the run's own entry.
    func recordSkipped(
        metric: String, because failure: HealthSyncFailure, source: HealthSyncSource, kind: HealthSyncRunKind, at: Date
    )
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
    func record(_ outcome: HealthSyncOutcome, source: HealthSyncSource, kind: HealthSyncRunKind, at: Date) {
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
            kind: kind,
            samples: samples, chunks: chunks, outcome: logged
        ))
    }

    func recordSkipped(
        metric: String, because failure: HealthSyncFailure, source: HealthSyncSource, kind: HealthSyncRunKind, at: Date
    ) {
        append(HealthSyncLogEntry(
            id: makeId(), at: at, source: source, kind: kind,
            samples: 0, chunks: 0, outcome: .failed(failure), metric: metric
        ))
    }

    func append(_ entry: HealthSyncLogEntry) {
        let kept = Array((entries + [entry]).suffix(capacity))
        cached = kept
        store.save(kept)
    }
}

/// Arrivals in a window: how many, how far apart (the open pause included), when the last one was.
struct HealthSyncLogSummary: Equatable {
    let arrivals: Int
    /// Gaps between neighbouring arrivals that end in the window, plus the open one; nil with no arrival at all.
    let medianInterval: TimeInterval?
    let longestInterval: TimeInterval?
    /// Latest arrival of the whole journal, not only of the window.
    let lastArrival: Date?
    /// `now` minus the last arrival: the pause that is still going on. Nil before the first arrival.
    let openInterval: TimeInterval?
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

    /// Gaps count when they end inside the window, so a pause that began before its edge
    /// is not cut off, and the pause still going on counts as the newest gap.
    static func summary(_ entries: [HealthSyncLogEntry], window: TimeInterval, now: Date) -> HealthSyncLogSummary {
        let start = now.addingTimeInterval(-window)
        let times = entries.filter { $0.isArrival && $0.at <= now }.map(\.at)
        var gaps = zip(times, times.dropFirst()).filter { $1 >= start }.map { $1.timeIntervalSince($0) }
        let open = times.last.map { now.timeIntervalSince($0) }
        if let open {
            gaps.append(open)
        }
        gaps.sort()
        return HealthSyncLogSummary(
            arrivals: times.filter { $0 >= start }.count,
            medianInterval: median(gaps),
            longestInterval: gaps.last,
            lastArrival: times.last,
            openInterval: open
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
