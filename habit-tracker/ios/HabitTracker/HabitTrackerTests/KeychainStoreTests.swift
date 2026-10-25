// [review:need-review] PHASE-01/03-ios-scaffold-settings
// summary: unit tests for KeychainStore — round-trip, overwrite, delete, missing key, and a save that fails halfway never loses the old key; KeychainFaults makes single SecItem steps fail
import Security
import XCTest
@testable import HabitTracker

/// Wraps the real Keychain and makes chosen steps fail, to walk the failure paths of `save`.
final class KeychainFaults: @unchecked Sendable {
    // Guarded by `lock`: the closures run on whatever thread calls the store.
    private let lock = NSLock()
    private var failingAddAccounts: Set<String> = []
    private var readFailure: OSStatus?
    private var hidesAllItemsAfterFailedAdd = false
    private var itemsHidden = false

    /// `add` of these accounts returns an error.
    func failAdds(for accounts: Set<String>, thenHideItems: Bool = false) {
        lock.lock()
        defer { lock.unlock() }
        failingAddAccounts = accounts
        hidesAllItemsAfterFailedAdd = thenHideItems
    }

    /// Every read returns this status instead of touching the Keychain.
    func failReads(with status: OSStatus?) {
        lock.lock()
        defer { lock.unlock() }
        readFailure = status
    }

    var backend: KeychainBackend {
        let system = KeychainBackend.system
        return KeychainBackend(
            add: { [self] query in
                if shouldFailAdd(query) {
                    return errSecIO
                }
                return system.add(query)
            },
            delete: system.delete,
            copyData: { [self] query in
                if let (status, hidden) = readOutcome() {
                    return (status, hidden)
                }
                return system.copyData(query)
            }
        )
    }

    private func shouldFailAdd(_ query: CFDictionary) -> Bool {
        let account = (query as NSDictionary)[kSecAttrAccount as String] as? String ?? ""
        lock.lock()
        defer { lock.unlock() }
        guard failingAddAccounts.contains(account) else { return false }
        itemsHidden = hidesAllItemsAfterFailedAdd
        return true
    }

    private func readOutcome() -> (OSStatus, Data?)? {
        lock.lock()
        defer { lock.unlock() }
        if itemsHidden {
            return (errSecItemNotFound, nil)
        }
        return readFailure.map { ($0, nil) }
    }
}

final class KeychainStoreTests: XCTestCase {
    private let store = KeychainStore(service: "com.habittracker.tests")
    private let key = "api-key"

    override func tearDownWithError() throws {
        try store.delete(key)
        try super.tearDownWithError()
    }

    func testSaveThenReadRoundTrip() throws {
        try store.save("secret-123", for: key)
        XCTAssertEqual(try store.read(key), "secret-123")
    }

    func testSaveOverwritesExistingValue() throws {
        try store.save("old-value", for: key)
        try store.save("new-value", for: key)
        XCTAssertEqual(try store.read(key), "new-value")
    }

    func testReadMissingKeyReturnsNil() throws {
        XCTAssertNil(try store.read("never-written"))
    }

    func testDeleteRemovesValue() throws {
        try store.save("to-be-deleted", for: key)
        try store.delete(key)
        XCTAssertNil(try store.read(key))
    }

    func testDeleteMissingKeyDoesNotThrow() throws {
        XCTAssertNoThrow(try store.delete("never-written"))
    }

    func testFailedPendingWriteKeepsTheOldValue() throws {
        try store.save("old-value", for: key)
        let faults = KeychainFaults()
        faults.failAdds(for: [key + ".pending"])
        let faulty = KeychainStore(service: "com.habittracker.tests", backend: faults.backend)

        XCTAssertThrowsError(try faulty.save("new-value", for: key))

        XCTAssertEqual(try store.read(key), "old-value")
    }

    func testFailedFinalWriteKeepsTheNewValueReadable() throws {
        try store.save("old-value", for: key)
        let faults = KeychainFaults()
        faults.failAdds(for: [key])
        let faulty = KeychainStore(service: "com.habittracker.tests", backend: faults.backend)

        XCTAssertThrowsError(try faulty.save("new-value", for: key))

        XCTAssertEqual(try store.read(key), "new-value", "the value must survive under the pending account")
    }

    func testDeleteAlsoRemovesAValueLeftUnderThePendingAccount() throws {
        let faults = KeychainFaults()
        faults.failAdds(for: [key])
        let faulty = KeychainStore(service: "com.habittracker.tests", backend: faults.backend)
        XCTAssertThrowsError(try faulty.save("stranded", for: key))

        try store.delete(key)

        XCTAssertNil(try store.read(key))
    }

    func testSaveAfterAStrandedValueReplacesIt() throws {
        let faults = KeychainFaults()
        faults.failAdds(for: [key])
        let faulty = KeychainStore(service: "com.habittracker.tests", backend: faults.backend)
        XCTAssertThrowsError(try faulty.save("stranded", for: key))

        try store.save("fresh", for: key)

        XCTAssertEqual(try store.read(key), "fresh")
    }
}
