// [review:need-review] PHASE-01/11-ios-read-cache
// summary: read-cache primitives — CacheStore protocol, in-memory impl, connectivity classifier, and ReadThroughCache that serves cached data (with a stale timestamp) when the network is down
// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 — `peek` gives a screen its last snapshot without the network, `isRecent` lets an appearance skip the read while the snapshot is younger than `minAge` and no write went out since (`ServerWrites`), and an answer older than the one already cached no longer overwrites it
import Foundation
import os

/// A cached payload together with the moment it was written. `updatedAt` is what
/// the offline banner shows ("data from <time>").
struct CachedValue<T> {
    let value: T
    let updatedAt: Date
}

/// Persists Codable snapshots keyed by a stable string, with the write timestamp.
/// Implementations are the transparent persistence behind `ReadThroughCache`; the
/// interface stays intentionally small so a feature only ever sees whole snapshots.
protocol CacheStore {
    /// Overwrites the entry at `key` with `value`, stamping it `updatedAt`.
    func save<T: Encodable>(_ value: T, forKey key: String, updatedAt: Date)
    /// Returns the cached value at `key`, or nil when absent or undecodable.
    func load<T: Decodable>(_ type: T.Type, forKey key: String) -> CachedValue<T>?
    /// What this run read from the server into the store, so screens sharing it agree on what is recent.
    var reads: CacheReadLog { get }
}

/// Counts the writes this run sent to the server. A snapshot read before a write may miss it, so it is not
/// recent any more, whatever its age. `APIClient.send` notes every request that is not a GET when it ends.
enum ServerWrites {
    private static let counter = OSAllocatedUnfairLock(initialState: 0)

    static var count: Int { counter.withLock { $0 } }

    static func note() {
        counter.withLock { $0 += 1 }
    }
}

/// Per key: the newest read sent through `ReadThroughCache.load`, and the newest one that reached the store,
/// with its moment and the count of writes when it left. Lives in memory only: after a restart every
/// snapshot is read again once.
final class CacheReadLog {
    struct Landed {
        let read: Int
        let at: Date
        let writes: Int
    }

    private let lock = NSLock()
    private var sent: [String: Int] = [:]
    private var landed: [String: Landed] = [:]

    /// Numbers a read of `key` as it leaves.
    func send(_ key: String) -> Int {
        lock.withLock {
            let read = (sent[key] ?? 0) + 1
            sent[key] = read
            return read
        }
    }

    /// Records the answer of `read` unless a newer read of the key already landed; returns whether it may be cached.
    func land(_ key: String, read: Int, at: Date, writes: Int) -> Bool {
        lock.withLock {
            if let newer = landed[key], newer.read > read { return false }
            landed[key] = Landed(read: read, at: at, writes: writes)
            return true
        }
    }

    func lastLanded(_ key: String) -> Landed? {
        lock.withLock { landed[key] }
    }
}

/// Coder shared by every `CacheStore`: both ends are this app, so the on-disk form
/// is the DTOs' native casing (no snake_case conversion) — it never crosses the wire.
enum CacheCoding {
    static func encoder() -> JSONEncoder { JSONEncoder() }
    static func decoder() -> JSONDecoder { JSONDecoder() }
}

/// Process-lifetime cache backed by a dictionary. Used as the default in unit tests
/// and as the fallback when the on-disk store cannot be created.
final class InMemoryCacheStore: CacheStore {
    private struct Record {
        let payload: Data
        let updatedAt: Date
    }

    private var records: [String: Record] = [:]
    let reads = CacheReadLog()

    func save<T: Encodable>(_ value: T, forKey key: String, updatedAt: Date) {
        guard let data = try? CacheCoding.encoder().encode(value) else { return }
        records[key] = Record(payload: data, updatedAt: updatedAt)
    }

    func load<T: Decodable>(_ type: T.Type, forKey key: String) -> CachedValue<T>? {
        guard let record = records[key],
              let value = try? CacheCoding.decoder().decode(T.self, from: record.payload) else {
            return nil
        }
        return CachedValue(value: value, updatedAt: record.updatedAt)
    }
}

extension APIClientError {
    /// Whether the error means the server was unreachable (timeout / transport). Only
    /// these justify serving stale cache: a reachable server that answered 401/500 is
    /// a real error the user must see, not an excuse to show old data.
    var isConnectivity: Bool {
        switch self {
        case .timeout, .transport:
            return true
        case .invalidBaseURL, .unauthorized, .unexpectedStatus, .invalidResponse:
            return false
        }
    }
}

/// Outcome of a read-through load: either freshly fetched, or served from cache
/// because the network was down (carrying the timestamp for the offline banner).
enum CacheOutcome<T> {
    case fresh(T)
    case stale(T, updatedAt: Date)
}

/// The transparent read cache. A feature runs its fetch through `load`: a successful
/// response overwrites the cache and returns `.fresh`; a connectivity failure with a
/// cached snapshot returns `.stale` instead of throwing, so the UI keeps its last data.
/// A screen opens on `peek` (the last snapshot, no network) and reads again only when the
/// snapshot is not `isRecent`.
struct ReadThroughCache {
    /// How long a snapshot read from the server counts as current: a screen that appears again within it
    /// does not ask the server.
    static let minAge: TimeInterval = 30

    let store: CacheStore
    let now: () -> Date

    init(store: CacheStore, now: @escaping () -> Date = Date.init) {
        self.store = store
        self.now = now
    }

    /// Fetches, caching on success. On a connectivity error, falls back to the cached
    /// snapshot when one exists; otherwise the original error is rethrown (nothing to show).
    /// An answer that comes back after a newer read of the same key has landed is returned, but not cached.
    func load<T: Codable>(
        key: String, fetch: () async throws -> T
    ) async throws -> CacheOutcome<T> {
        let read = store.reads.send(key)
        let writes = ServerWrites.count
        do {
            let value = try await fetch()
            let at = now()
            if store.reads.land(key, read: read, at: at, writes: writes) {
                store.save(value, forKey: key, updatedAt: at)
            }
            return .fresh(value)
        } catch let error as APIClientError where error.isConnectivity {
            guard let cached = store.load(T.self, forKey: key) else {
                throw error
            }
            return .stale(cached.value, updatedAt: cached.updatedAt)
        }
    }

    /// The last snapshot at `key`, without the network: what a screen draws on its first frame.
    func peek<T: Decodable>(_ type: T.Type, key: String) -> CachedValue<T>? {
        store.load(type, forKey: key)
    }

    /// Whether `key` was read from the server less than `minAge` ago with no write sent since:
    /// an appearance may then skip the network. A key not read in this run is never recent.
    func isRecent(key: String, minAge: TimeInterval = ReadThroughCache.minAge) -> Bool {
        guard let landed = store.reads.lastLanded(key) else { return false }
        let age = now().timeIntervalSince(landed.at)
        return age >= 0 && age < minAge && landed.writes == ServerWrites.count
    }
}
