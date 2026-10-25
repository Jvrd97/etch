// [review:need-review] PHASE-01/03-ios-scaffold-settings, PHASE-01/214
// summary: minimal Keychain-backed string store (SecItem generic password) for the API key; optional Face ID access control on save, an authenticated context on read, a save that never drops the old key before the new one is stored, and a SecItem seam for failure tests
import Foundation
import LocalAuthentication
import Security

/// Error thrown when a Keychain operation returns an unexpected status.
struct KeychainError: Error, Equatable {
    let status: OSStatus
}

/// The four SecItem calls the store makes. The default talks to the real Keychain;
/// tests swap single closures to make a step fail.
struct KeychainBackend: Sendable {
    var add: @Sendable (CFDictionary) -> OSStatus
    var delete: @Sendable (CFDictionary) -> OSStatus
    /// Returns the item's data, or nil together with the status when there is none.
    var copyData: @Sendable (CFDictionary) -> (status: OSStatus, data: Data?)

    static let system = KeychainBackend(
        add: { SecItemAdd($0, nil) },
        delete: { SecItemDelete($0) },
        copyData: { query in
            var result: AnyObject?
            let status = SecItemCopyMatching(query, &result)
            return (status, result as? Data)
        }
    )
}

/// Stores small string secrets in the iOS Keychain as generic-password items.
/// This is the only allowed storage for the API key (never UserDefaults).
struct KeychainStore {
    static let defaultService = "com.habittracker.api"

    let service: String
    let backend: KeychainBackend

    init(service: String = KeychainStore.defaultService, backend: KeychainBackend = .system) {
        self.service = service
        self.backend = backend
    }

    /// Account that holds the new value while a save is in flight.
    private static func pendingAccount(for key: String) -> String {
        key + ".pending"
    }

    private func baseQuery(for key: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
    }

    /// Inserts or overwrites the value for `key`. With a `protection` other than `.none`
    /// the item is bound to the enrolled Face ID set and stays on this device.
    ///
    /// The old item is deleted only after the new value is already stored under a pending
    /// account, so a failed save leaves the previous key in place. If the final write fails
    /// after the old item is gone, the value stays under the pending account and `read`
    /// still finds it.
    func save(_ value: String, for key: String, protection: KeyProtection = .none) throws {
        let pending = Self.pendingAccount(for: key)
        // Leftover of an interrupted save; the value being saved replaces it anyway.
        try deleteItem(pending)
        try addItem(value, account: pending, protection: protection)
        do {
            try deleteItem(key)
        } catch {
            // Best effort: a stale pending item is cleared by the next save.
            _ = backend.delete(baseQuery(for: pending) as CFDictionary)
            throw error
        }
        try addItem(value, account: key, protection: protection)
        // The value is stored; a leftover pending item is harmless (`read` prefers the main one).
        _ = backend.delete(baseQuery(for: pending) as CFDictionary)
    }

    private func addItem(_ value: String, account: String, protection: KeyProtection) throws {
        var query = baseQuery(for: account)
        query[kSecValueData as String] = Data(value.utf8)
        switch protection {
        case .none:
            query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        case .biometry, .biometryOrPasscode:
            query[kSecAttrAccessControl as String] = try Self.accessControl(for: protection)
        }
        let status = backend.add(query as CFDictionary)
        guard status == errSecSuccess else {
            throw KeychainError(status: status)
        }
    }

    private static func accessControl(for protection: KeyProtection) throws -> SecAccessControl {
        let flags: SecAccessControlCreateFlags = protection == .biometryOrPasscode
            ? [.biometryCurrentSet, .or, .devicePasscode]
            : [.biometryCurrentSet]
        var error: Unmanaged<CFError>?
        guard let control = SecAccessControlCreateWithFlags(
            nil, kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly, flags, &error
        ) else {
            throw KeychainError(status: errSecParam)
        }
        return control
    }

    /// Returns the stored value, or nil when the key is absent. A protected item opens
    /// with `context` (default: the shared session's, which never raises a prompt itself).
    func read(_ key: String, context: LAContext? = nil) throws -> String? {
        let context = context ?? BiometricSession.shared.readContext()
        if let value = try readItem(key, context: context) {
            return value
        }
        return try readItem(Self.pendingAccount(for: key), context: context)
    }

    private func readItem(_ account: String, context: LAContext) throws -> String? {
        var query = baseQuery(for: account)
        query[kSecUseAuthenticationContext as String] = context
        query[kSecReturnData as String] = kCFBooleanTrue
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        let (status, data) = backend.copyData(query as CFDictionary)
        switch status {
        case errSecSuccess:
            guard let data else {
                throw KeychainError(status: errSecDecode)
            }
            return String(decoding: data, as: UTF8.self)
        case errSecItemNotFound:
            return nil
        default:
            throw KeychainError(status: status)
        }
    }

    /// Removes the value for `key`; absent keys are not an error.
    func delete(_ key: String) throws {
        try deleteItem(key)
        try deleteItem(Self.pendingAccount(for: key))
    }

    private func deleteItem(_ account: String) throws {
        let status = backend.delete(baseQuery(for: account) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainError(status: status)
        }
    }
}
