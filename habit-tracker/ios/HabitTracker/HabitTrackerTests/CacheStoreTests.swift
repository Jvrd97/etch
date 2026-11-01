// [review:need-review] PHASE-01/11-ios-read-cache
// summary: unit tests for the read-cache layer — SwiftData round-trip/overwrite, connectivity classifier, and ReadThroughCache fresh/stale/rethrow outcomes
// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 round 2 — an answer that comes back after the address changed is not cached under the new server (load and a screen's own save); unscoped snapshots move once under the server that owned them
// summary: PHASE-03/310 — peek without the network, recency by age and by writes sent since, an older answer that lands late does not overwrite the cache, snapshots of another server are not shown
import XCTest
@testable import HabitTracker

private struct Sample: Codable, Equatable {
    let id: Int
    let name: String
}

final class CacheStoreTests: XCTestCase {
    private func makeDate(_ offset: TimeInterval = 0) -> Date {
        Date(timeIntervalSince1970: 1_700_000_000 + offset)
    }

    // MARK: - SwiftDataCacheStore

    func testSwiftDataStoreRoundTripsSavedValue() throws {
        let store = try SwiftDataCacheStore(inMemory: true)
        let stamp = makeDate()

        store.save(Sample(id: 1, name: "pushups"), forKey: "k", updatedAt: stamp)
        let loaded = store.load(Sample.self, forKey: "k")

        XCTAssertEqual(loaded?.value, Sample(id: 1, name: "pushups"))
        XCTAssertEqual(loaded?.updatedAt, stamp)
    }

    func testSwiftDataStoreOverwritesSameKeyInPlace() throws {
        let store = try SwiftDataCacheStore(inMemory: true)

        store.save(Sample(id: 1, name: "old"), forKey: "k", updatedAt: makeDate(0))
        store.save(Sample(id: 2, name: "new"), forKey: "k", updatedAt: makeDate(60))
        let loaded = store.load(Sample.self, forKey: "k")

        XCTAssertEqual(loaded?.value, Sample(id: 2, name: "new"))
        XCTAssertEqual(loaded?.updatedAt, makeDate(60))
    }

    func testSwiftDataStoreReturnsNilForMissingKey() throws {
        let store = try SwiftDataCacheStore(inMemory: true)
        XCTAssertNil(store.load(Sample.self, forKey: "absent"))
    }

    // MARK: - Connectivity classification

    func testConnectivityErrorsAreOnlyTimeoutAndTransport() {
        XCTAssertTrue(APIClientError.timeout.isConnectivity)
        XCTAssertTrue(APIClientError.transport(code: -1009).isConnectivity)
        XCTAssertFalse(APIClientError.unauthorized.isConnectivity)
        XCTAssertFalse(APIClientError.unexpectedStatus(500).isConnectivity)
        XCTAssertFalse(APIClientError.invalidResponse.isConnectivity)
        XCTAssertFalse(APIClientError.invalidBaseURL.isConnectivity)
    }

    // MARK: - ReadThroughCache

    func testLoadReturnsFreshAndWritesCache() async throws {
        let store = InMemoryCacheStore()
        let stamp = makeDate()
        let cache = ReadThroughCache(store: store, now: { stamp })

        let outcome = try await cache.load(key: "k") { Sample(id: 7, name: "fresh") }

        guard case .fresh(let value) = outcome else {
            return XCTFail("Expected fresh, got \(outcome)")
        }
        XCTAssertEqual(value, Sample(id: 7, name: "fresh"))
        // The successful response is now persisted with the clock's timestamp.
        let cached = store.load(Sample.self, forKey: "k")
        XCTAssertEqual(cached?.value, Sample(id: 7, name: "fresh"))
        XCTAssertEqual(cached?.updatedAt, stamp)
    }

    func testLoadServesStaleCacheOnConnectivityError() async throws {
        let store = InMemoryCacheStore()
        let firstStamp = makeDate(0)
        let firstCache = ReadThroughCache(store: store, now: { firstStamp })
        _ = try await firstCache.load(key: "k") { Sample(id: 1, name: "cached") }

        let secondCache = ReadThroughCache(store: store, now: { self.makeDate(999) })
        let outcome: CacheOutcome<Sample> = try await secondCache.load(key: "k") {
            throw APIClientError.timeout
        }

        guard case .stale(let value, let updatedAt) = outcome else {
            return XCTFail("Expected stale, got \(outcome)")
        }
        XCTAssertEqual(value, Sample(id: 1, name: "cached"))
        XCTAssertEqual(updatedAt, firstStamp)
    }

    func testLoadRethrowsConnectivityErrorWhenCacheEmpty() async {
        let cache = ReadThroughCache(store: InMemoryCacheStore(), now: { self.makeDate() })
        do {
            _ = try await cache.load(key: "k") { () throws -> Sample in
                throw APIClientError.timeout
            }
            XCTFail("Expected error to propagate when nothing is cached")
        } catch let error as APIClientError {
            XCTAssertEqual(error, .timeout)
        } catch {
            XCTFail("Unexpected error type: \(error)")
        }
    }

    func testLoadRethrowsNonConnectivityErrorEvenWithCache() async throws {
        let store = InMemoryCacheStore()
        let cache = ReadThroughCache(store: store, now: { self.makeDate() })
        _ = try await cache.load(key: "k") { Sample(id: 1, name: "cached") }

        do {
            _ = try await cache.load(key: "k") { () throws -> Sample in
                throw APIClientError.unauthorized
            }
            XCTFail("A reachable-server error must not be masked by stale cache")
        } catch let error as APIClientError {
            XCTAssertEqual(error, .unauthorized)
        } catch {
            XCTFail("Unexpected error type: \(error)")
        }
    }

    // MARK: - Cache-first reads (#310)

    func testPeekReturnsTheSnapshotWithoutFetching() async throws {
        let store = InMemoryCacheStore()
        let cache = ReadThroughCache(store: store, now: { self.makeDate() })
        _ = try await cache.load(key: "k") { Sample(id: 1, name: "cached") }

        XCTAssertEqual(cache.peek(Sample.self, key: "k")?.value, Sample(id: 1, name: "cached"))
        XCTAssertNil(cache.peek(Sample.self, key: "other"))
    }

    func testIsRecentFollowsTheAgeOfTheLastRead() async throws {
        var clock = makeDate()
        let cache = ReadThroughCache(store: InMemoryCacheStore(), now: { clock })
        XCTAssertFalse(cache.isRecent(key: "k"), "a key never read in this run is not recent")

        _ = try await cache.load(key: "k") { Sample(id: 1, name: "a") }
        clock = makeDate(ReadThroughCache.minAge - 1)
        XCTAssertTrue(cache.isRecent(key: "k"))
        clock = makeDate(ReadThroughCache.minAge)
        XCTAssertFalse(cache.isRecent(key: "k"))
    }

    func testASnapshotSavedOutsideTheReadIsNotRecent() {
        let store = InMemoryCacheStore()
        store.save(Sample(id: 1, name: "a"), forKey: "k", updatedAt: makeDate())
        let cache = ReadThroughCache(store: store, now: { self.makeDate() })

        XCTAssertFalse(cache.isRecent(key: "k"), "a snapshot from the disk was read in an earlier run")
    }

    func testAWriteSentAfterTheReadMakesItNotRecent() async throws {
        let cache = ReadThroughCache(store: InMemoryCacheStore(), now: { self.makeDate() })
        _ = try await cache.load(key: "k") { Sample(id: 1, name: "a") }

        ServerWrites.note()

        XCTAssertFalse(cache.isRecent(key: "k"))
    }

    func testAWriteThatEndsDuringTheReadMakesItNotRecent() async throws {
        let cache = ReadThroughCache(store: InMemoryCacheStore(), now: { self.makeDate() })
        _ = try await cache.load(key: "k") { () -> Sample in
            ServerWrites.note()
            return Sample(id: 1, name: "a")
        }

        XCTAssertFalse(cache.isRecent(key: "k"), "the read left before the write landed and may miss it")
    }

    @MainActor
    func testAnOlderAnswerLandingLateDoesNotOverwriteTheCache() async throws {
        let store = InMemoryCacheStore()
        let cache = ReadThroughCache(store: store, now: { self.makeDate() })
        let gate = ReadGate()
        let older = Task { @MainActor in
            try await cache.load(key: "k") { () async -> Sample in
                await gate.wait()
                return Sample(id: 1, name: "older")
            }
        }
        await waitUntil { gate.isWaiting }
        _ = try await cache.load(key: "k") { Sample(id: 2, name: "newer") }

        gate.open()
        let outcome = try await older.value

        guard case .fresh(let value) = outcome else { return XCTFail("Expected fresh, got \(outcome)") }
        XCTAssertEqual(value.name, "older", "the caller still gets its answer")
        XCTAssertEqual(store.load(Sample.self, forKey: "k")?.value.name, "newer")
    }

    func testSnapshotsOfAnotherServerAreNotShown() {
        var server = "http://a:8000"
        let store = ServerScopedCacheStore(base: InMemoryCacheStore(), server: { server })
        store.save(Sample(id: 1, name: "from a"), forKey: "k", updatedAt: makeDate())

        server = "http://b:8000"
        XCTAssertNil(store.load(Sample.self, forKey: "k"))
        store.save(Sample(id: 2, name: "from b"), forKey: "k", updatedAt: makeDate())

        server = "http://a:8000"
        XCTAssertEqual(store.load(Sample.self, forKey: "k")?.value.name, "from a")
    }

    func testARecentReadOfAnotherServerIsNotRecent() async throws {
        var server = "http://a:8000"
        let store = ServerScopedCacheStore(base: InMemoryCacheStore(), server: { server })
        let cache = ReadThroughCache(store: store, now: { self.makeDate() })
        _ = try await cache.load(key: "k") { Sample(id: 1, name: "a") }
        XCTAssertTrue(cache.isRecent(key: "k"))

        server = "http://b:8000"

        XCTAssertFalse(cache.isRecent(key: "k"))
    }

    func testAnAnswerThatComesBackAfterTheAddressChangedIsNotCachedUnderTheNewServer() async throws {
        var server = "http://a:8000"
        let store = ServerScopedCacheStore(base: InMemoryCacheStore(), server: { server })
        let cache = ReadThroughCache(store: store, now: { self.makeDate() })
        server = "http://b:8000"
        store.save(Sample(id: 2, name: "b's own"), forKey: "k", updatedAt: makeDate())
        server = "http://a:8000"

        _ = try await cache.load(key: "k") { () -> Sample in
            server = "http://b:8000"
            return Sample(id: 1, name: "a's answer")
        }

        XCTAssertEqual(store.load(Sample.self, forKey: "k")?.value.name, "b's own")
        XCTAssertFalse(cache.isRecent(key: "k"))
    }

    func testAScreensOwnSaveIsSkippedWhenTheAddressChangedSinceItsRead() {
        var server = "http://a:8000"
        let store = ServerScopedCacheStore(base: InMemoryCacheStore(), server: { server })
        let cache = ReadThroughCache(store: store, now: { self.makeDate() })
        let sentUnder = cache.scope

        server = "http://b:8000"
        cache.save(Sample(id: 1, name: "a's answer"), forKey: "k", updatedAt: makeDate(), sentUnder: sentUnder)
        XCTAssertNil(store.load(Sample.self, forKey: "k"))

        cache.save(Sample(id: 2, name: "b's answer"), forKey: "k", updatedAt: makeDate(), sentUnder: cache.scope)
        XCTAssertEqual(store.load(Sample.self, forKey: "k")?.value.name, "b's answer")
    }

    func testUnscopedSnapshotsMoveOnceUnderTheServerThatOwnedThem() {
        let base = InMemoryCacheStore()
        base.save(Sample(id: 1, name: "before #310"), forKey: "k", updatedAt: makeDate())
        var server = "http://b:8000"
        let store = ServerScopedCacheStore(base: base, server: { server }, legacyOwner: "http://a:8000")

        XCTAssertNil(store.load(Sample.self, forKey: "k"), "another server never takes them over")
        server = "http://a:8000"
        XCTAssertEqual(store.load(Sample.self, forKey: "k")?.value.name, "before #310")
        XCTAssertEqual(store.load(Sample.self, forKey: "k")?.updatedAt, makeDate(), "the snapshot keeps its age")
        XCTAssertNil(base.load(Sample.self, forKey: "k"), "moved, not copied")
    }

    func testSwiftDataStoreMovesARecordUnlessTheNewKeyIsTaken() throws {
        let store = try SwiftDataCacheStore(inMemory: true)
        store.save(Sample(id: 1, name: "old"), forKey: "k", updatedAt: makeDate())
        store.save(Sample(id: 2, name: "taken"), forKey: "taken", updatedAt: makeDate())

        XCTAssertFalse(store.moveRecord(from: "k", to: "taken"))
        XCTAssertTrue(store.moveRecord(from: "k", to: "moved"))

        XCTAssertNil(store.load(Sample.self, forKey: "k"))
        XCTAssertEqual(store.load(Sample.self, forKey: "moved")?.value.name, "old")
        XCTAssertEqual(store.load(Sample.self, forKey: "taken")?.value.name, "taken")
    }

    func testTheOwnerOfUnscopedSnapshotsIsTheServerOfTheFirstLaunchAfterTheUpdate() throws {
        let suite = "CacheStoreTests.legacyOwner"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defaults.removePersistentDomain(forName: suite)
        defaults.set("http://a:8000", forKey: SettingsViewModel.serverAddressDefaultsKey)
        XCTAssertEqual(ServerScopedCacheStore.legacyOwner(defaults: defaults), "http://a:8000")

        defaults.set("http://b:8000", forKey: SettingsViewModel.serverAddressDefaultsKey)

        XCTAssertEqual(ServerScopedCacheStore.legacyOwner(defaults: defaults), "http://a:8000")
    }

    func testStoredServerIsTheAddressTheClientUses() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "CacheStoreTests.storedServer"))
        defaults.removePersistentDomain(forName: "CacheStoreTests.storedServer")
        XCTAssertEqual(ServerScopedCacheStore.storedServer(defaults: defaults), "")

        defaults.set("  http://100.64.0.1:8000 ", forKey: SettingsViewModel.serverAddressDefaultsKey)

        XCTAssertEqual(ServerScopedCacheStore.storedServer(defaults: defaults), "http://100.64.0.1:8000")
    }
}

/// Holds a fake request until the test opens it.
@MainActor
final class ReadGate {
    private var continuation: CheckedContinuation<Void, Never>?
    private var isOpen = false
    var isWaiting: Bool { continuation != nil }

    func wait() async {
        if isOpen { return }
        await withCheckedContinuation { continuation = $0 }
    }

    func open() {
        isOpen = true
        continuation?.resume()
        continuation = nil
    }
}
