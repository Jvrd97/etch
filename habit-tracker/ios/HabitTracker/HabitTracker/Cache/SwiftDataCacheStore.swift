// [review:need-review] PHASE-01/11-ios-read-cache
// summary: SwiftData-backed CacheStore — one CacheRecord row per key (payload + updatedAt), upserted on save; ReadCacheLive builds the shared on-disk store with an in-memory fallback
// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 round 2 — the store names its server (`scope`); snapshots written before the keys were scoped move once, on first use, under the server stored at the first launch after the update
// summary: PHASE-03/310 — the live cache keeps each server's snapshots apart (`ServerScopedCacheStore`): after the address changes in Settings the screens of the previous server are not shown
import Foundation
import SwiftData
import os

/// One cached snapshot: the feature's key, its encoded payload, and the write time.
@Model
final class CacheRecord {
    @Attribute(.unique) var key: String
    var payload: Data
    var updatedAt: Date

    init(key: String, payload: Data, updatedAt: Date) {
        self.key = key
        self.payload = payload
        self.updatedAt = updatedAt
    }
}

/// Durable `CacheStore` on top of SwiftData. Each key maps to a single `CacheRecord`
/// that `save` upserts wholesale (issue #11 replaces snapshots, never patches cells).
final class SwiftDataCacheStore: CacheStore, CacheRecordMoving {
    private let context: ModelContext
    let reads = CacheReadLog()

    private static let logger = Logger(
        subsystem: "com.habittracker.app", category: "SwiftDataCacheStore"
    )

    /// Wraps an existing context (tests pass an in-memory container's context).
    init(context: ModelContext) {
        self.context = context
    }

    /// Builds the store over its own container. `inMemory` yields an ephemeral store
    /// (used by tests); the default is the app's on-disk cache database.
    convenience init(inMemory: Bool = false) throws {
        let configuration = ModelConfiguration(isStoredInMemoryOnly: inMemory)
        let container = try ModelContainer(for: CacheRecord.self, configurations: configuration)
        self.init(context: ModelContext(container))
    }

    func save<T: Encodable>(_ value: T, forKey key: String, updatedAt: Date) {
        guard let data = try? CacheCoding.encoder().encode(value) else { return }
        do {
            if let existing = try fetchRecord(forKey: key) {
                existing.payload = data
                existing.updatedAt = updatedAt
            } else {
                context.insert(CacheRecord(key: key, payload: data, updatedAt: updatedAt))
            }
            try context.save()
        } catch {
            // A cache write failure must never break the feature: the fresh value is
            // already returned to the caller, so we log (no payload) and move on.
            Self.logger.error("Cache save failed for key \(key): \(String(describing: error))")
        }
    }

    func load<T: Decodable>(_ type: T.Type, forKey key: String) -> CachedValue<T>? {
        guard let record = try? fetchRecord(forKey: key),
              let value = try? CacheCoding.decoder().decode(T.self, from: record.payload) else {
            return nil
        }
        return CachedValue(value: value, updatedAt: record.updatedAt)
    }

    func moveRecord(from oldKey: String, to newKey: String) -> Bool {
        do {
            guard let record = try fetchRecord(forKey: oldKey), try fetchRecord(forKey: newKey) == nil else { return false }
            record.key = newKey
            try context.save()
            return true
        } catch {
            Self.logger.error("Cache record move failed: \(String(describing: error))")
            return false
        }
    }

    private func fetchRecord(forKey key: String) throws -> CacheRecord? {
        let descriptor = FetchDescriptor<CacheRecord>(
            predicate: #Predicate { $0.key == key }
        )
        return try context.fetch(descriptor).first
    }
}

/// Keeps the snapshots of each server apart: a key is stored under the address it was read from, so a
/// screen never opens on the data of a server it no longer talks to. The read log is per server too.
final class ServerScopedCacheStore: CacheStore {
    /// `UserDefaults` key of the server that owns the snapshots written before the keys were scoped.
    static let legacyOwnerDefaultsKey = "read_cache_legacy_owner"

    private let base: CacheStore
    private let server: () -> String
    private let legacyOwner: String?
    private let lock = NSLock()
    private var logs: [String: CacheReadLog] = [:]

    /// `legacyOwner` is the server whose unscoped snapshots (written before #310) may be taken over; nil takes none.
    init(base: CacheStore, server: @escaping () -> String, legacyOwner: String? = nil) {
        self.base = base
        self.server = server
        self.legacyOwner = legacyOwner
    }

    var scope: String { server() }

    var reads: CacheReadLog {
        let current = server()
        return lock.withLock {
            if let log = logs[current] { return log }
            let log = CacheReadLog()
            logs[current] = log
            return log
        }
    }

    func save<T: Encodable>(_ value: T, forKey key: String, updatedAt: Date) {
        base.save(value, forKey: scoped(key, in: server()), updatedAt: updatedAt)
    }

    /// A key the current server has nothing under may still hold a snapshot from before the keys were scoped:
    /// when the current server is the one that owned them, the record moves under the server's key, once.
    func load<T: Decodable>(_ type: T.Type, forKey key: String) -> CachedValue<T>? {
        let current = server()
        let target = scoped(key, in: current)
        if let value = base.load(type, forKey: target) { return value }
        guard current == legacyOwner, let movable = base as? CacheRecordMoving,
              movable.moveRecord(from: key, to: target) else { return nil }
        return base.load(type, forKey: target)
    }

    /// Which server owns the unscoped snapshots: the one stored at the first launch after the update, remembered
    /// from then on, so a server set later never takes over another server's data.
    static func legacyOwner(defaults: UserDefaults = .standard) -> String {
        if let owner = defaults.string(forKey: legacyOwnerDefaultsKey) { return owner }
        let owner = storedServer(defaults: defaults)
        defaults.set(owner, forKey: legacyOwnerDefaultsKey)
        return owner
    }

    private func scoped(_ key: String, in server: String) -> String {
        "\(server)|\(key)"
    }

    /// The server address from Settings in the form the client uses; empty while none is stored.
    static func storedServer(defaults: UserDefaults = .standard) -> String {
        let address = defaults.string(forKey: SettingsViewModel.serverAddressDefaultsKey) ?? ""
        return APIClient.makeBaseURL(from: address)?.absoluteString ?? ""
    }
}

/// The production read cache. Built once, on-disk; if SwiftData cannot open its store
/// the app degrades to an in-memory cache (offline fallback still works within a run)
/// rather than crashing at launch. Keys are scoped by the stored server address.
enum ReadCacheLive {
    private static let logger = Logger(
        subsystem: "com.habittracker.app", category: "ReadCacheLive"
    )

    static let shared: CacheStore = ServerScopedCacheStore(
        base: onDisk,
        server: { ServerScopedCacheStore.storedServer() },
        legacyOwner: ServerScopedCacheStore.legacyOwner()
    )

    private static let onDisk: CacheStore = {
        do {
            return try SwiftDataCacheStore()
        } catch {
            logger.error("On-disk read cache unavailable, using in-memory: \(String(describing: error))")
            return InMemoryCacheStore()
        }
    }()
}
