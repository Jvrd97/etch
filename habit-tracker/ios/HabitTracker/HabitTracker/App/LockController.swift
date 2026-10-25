// [review:need-review] PHASE-01/214
// summary: lock state machine — locked at launch, locked again after a long stay in the background, unlocked by Face ID, one automatic prompt per lock episode; settings keys in UserDefaults
import Foundation
import SwiftUI

/// The two Settings choices that drive the lock. Plain flags in `UserDefaults`:
/// they are not secrets, and the lock must know them before anything is unlocked.
struct LockSettings {
    nonisolated static let enabledDefaultsKey = "face_id_lock_enabled"
    nonisolated static let passcodeDefaultsKey = "face_id_lock_passcode_fallback"

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    var isEnabled: Bool {
        get { defaults.bool(forKey: Self.enabledDefaultsKey) }
        nonmutating set { defaults.set(newValue, forKey: Self.enabledDefaultsKey) }
    }

    var allowsPasscode: Bool {
        get { defaults.bool(forKey: Self.passcodeDefaultsKey) }
        nonmutating set { defaults.set(newValue, forKey: Self.passcodeDefaultsKey) }
    }

    var keyProtection: KeyProtection {
        guard isEnabled else { return .none }
        return allowsPasscode ? .biometryOrPasscode : .biometry
    }
}

@MainActor
final class AppLockController: ObservableObject {
    /// How long the app may stay in the background before it asks again.
    nonisolated static let lockTimeout: TimeInterval = 5 * 60

    @Published private(set) var isLocked: Bool
    @Published private(set) var message: String?
    @Published private(set) var isAuthenticating = false

    private let settings: LockSettings
    private let authenticator: BiometricAuthenticating
    private let session: BiometricSession
    private let now: () -> Date
    private var backgroundedAt: Date?
    /// True until the automatic Face ID prompt has been shown for the current lock episode.
    /// A cancelled prompt leaves the "Открыть" button instead of raising the prompt again
    /// every time the scene goes inactive and active.
    private var promptsOnActivation: Bool

    init(
        settings: LockSettings = LockSettings(),
        authenticator: BiometricAuthenticating = LocalAuthenticator(),
        session: BiometricSession = .shared,
        now: @escaping () -> Date = Date.init
    ) {
        self.settings = settings
        self.authenticator = authenticator
        self.session = session
        self.now = now
        self.isLocked = settings.isEnabled
        self.promptsOnActivation = settings.isEnabled
    }

    func sceneDidEnterBackground() {
        backgroundedAt = now()
        if isLocked {
            promptsOnActivation = true
        }
    }

    /// True once per launch or return from the background while locked: the caller then
    /// raises Face ID itself. Coming back from `.inactive` (a cancelled prompt, Control
    /// Center) never asks again.
    func takeActivationPrompt() -> Bool {
        defer { promptsOnActivation = false }
        return isLocked && promptsOnActivation
    }

    func sceneDidBecomeActive() {
        defer { backgroundedAt = nil }
        guard settings.isEnabled, !isLocked, let left = backgroundedAt else { return }
        if now().timeIntervalSince(left) >= Self.lockTimeout {
            lock()
        }
    }

    /// Asks for Face ID. A refusal leaves the app locked and the stored key untouched.
    func unlock() async {
        guard isLocked, !isAuthenticating else { return }
        isAuthenticating = true
        defer { isAuthenticating = false }
        do {
            let context = try await authenticator.authenticate(
                reason: "Открыть Habit Tracker",
                allowPasscode: settings.allowsPasscode
            )
            session.start(with: context)
            message = nil
            isLocked = false
        } catch let failure as BiometricFailure {
            message = failure.userMessage
        } catch {
            message = BiometricFailure.failed.userMessage
        }
    }

    private func lock() {
        session.end()
        message = nil
        isLocked = true
        promptsOnActivation = true
    }
}
