// [review:need-review] PHASE-01/214
// summary: holds the LAContext that Face ID just evaluated so Keychain reads of the protected API key need no second prompt; KeyProtection names the item's access control
import Foundation
import LocalAuthentication

/// How the API key item in the Keychain is guarded.
enum KeyProtection: Equatable {
    /// Readable after first unlock, as before Face ID existed.
    case none
    /// Readable only with the Face ID set that was enrolled when the item was saved.
    case biometry
    /// Same, and the device passcode also opens it.
    case biometryOrPasscode
}

/// The authenticated context of the current unlocked period. Shared, because
/// `APIClient.live()` builds its own `KeychainStore` and cannot be handed one.
final class BiometricSession: @unchecked Sendable {
    static let shared = BiometricSession()

    // Guarded by `lock`: the API key is read from background request tasks.
    private let lock = NSLock()
    private var context: LAContext?

    var authenticatedContext: LAContext? {
        lock.lock()
        defer { lock.unlock() }
        return context
    }

    func start(with context: LAContext) {
        lock.lock()
        defer { lock.unlock() }
        self.context?.invalidate()
        self.context = context
    }

    func end() {
        lock.lock()
        defer { lock.unlock() }
        context?.invalidate()
        context = nil
    }

    /// The context a Keychain read carries: the authenticated one while unlocked,
    /// otherwise one that refuses to show a prompt. A locked app then fails the read
    /// quietly (the request goes out without a key) instead of raising Face ID over
    /// a screen the person did not open.
    func readContext() -> LAContext {
        if let context = authenticatedContext {
            return context
        }
        let silent = LAContext()
        silent.interactionNotAllowed = true
        return silent
    }
}
