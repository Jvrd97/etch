// [review:need-review] PHASE-01/03-ios-scaffold-settings, PHASE-01/214
// summary: minimal Keychain-backed string store (SecItem generic password) for the API key; optional Face ID access control on save and an authenticated context on read
import Foundation
import LocalAuthentication
import Security

/// Error thrown when a Keychain operation returns an unexpected status.
struct KeychainError: Error, Equatable {
    let status: OSStatus
}

/// Stores small string secrets in the iOS Keychain as generic-password items.
/// This is the only allowed storage for the API key (never UserDefaults).
struct KeychainStore {
    static let defaultService = "com.habittracker.api"

    let service: String

    init(service: String = KeychainStore.defaultService) {
        self.service = service
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
    func save(_ value: String, for key: String, protection: KeyProtection = .none) throws {
        try delete(key)
        var query = baseQuery(for: key)
        query[kSecValueData as String] = Data(value.utf8)
        switch protection {
        case .none:
            query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        case .biometry, .biometryOrPasscode:
            query[kSecAttrAccessControl as String] = try Self.accessControl(for: protection)
        }
        let status = SecItemAdd(query as CFDictionary, nil)
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
        var query = baseQuery(for: key)
        query[kSecUseAuthenticationContext as String] = context ?? BiometricSession.shared.readContext()
        query[kSecReturnData as String] = kCFBooleanTrue
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        switch status {
        case errSecSuccess:
            guard let data = result as? Data else {
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
        let status = SecItemDelete(baseQuery(for: key) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainError(status: status)
        }
    }
}
