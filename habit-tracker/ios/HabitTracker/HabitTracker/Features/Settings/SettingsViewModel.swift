// [review:need-review] PHASE-01/05-ios-today-quick-entry, PHASE-01/208, PHASE-01/214
// summary: Settings state — server address in UserDefaults, API key in Keychain (Face ID protected on request); connection check through the production factory APIClient.live
import Foundation
import LocalAuthentication

@MainActor
final class SettingsViewModel: ObservableObject {
    /// Discriminated connection-check state for the UI indicator.
    enum ConnectionState: Equatable {
        case idle
        case checking
        case success
        case failure(String)
    }

    // Immutable strings, so readable off the main actor (APIClient.live builds clients anywhere).
    nonisolated static let serverAddressDefaultsKey = "server_address"
    nonisolated static let apiKeyKeychainKey = "api-key"

    @Published var serverAddress: String
    @Published var apiKey: String
    @Published private(set) var connectionState: ConnectionState = .idle

    @Published private(set) var faceIDLockEnabled: Bool
    @Published private(set) var passcodeFallbackEnabled: Bool
    @Published private(set) var lockMessage: String?

    private let keychain: KeychainStore
    private let defaults: UserDefaults
    private let session: URLSession
    private let authenticator: BiometricAuthenticating
    private let biometricSession: BiometricSession
    private let lockSettings: LockSettings
    /// True when a stored key could not be read (Face ID set changed, app locked). The
    /// empty field then means "unknown", so saving must not delete the stored key.
    private var storedKeyUnreadable = false

    init(
        keychain: KeychainStore = KeychainStore(),
        defaults: UserDefaults = .standard,
        session: URLSession = .shared,
        authenticator: BiometricAuthenticating = LocalAuthenticator(),
        biometricSession: BiometricSession = .shared
    ) {
        self.keychain = keychain
        self.defaults = defaults
        self.session = session
        self.authenticator = authenticator
        self.biometricSession = biometricSession
        self.lockSettings = LockSettings(defaults: defaults)
        self.faceIDLockEnabled = lockSettings.isEnabled
        self.passcodeFallbackEnabled = lockSettings.allowsPasscode
        self.serverAddress = defaults.string(forKey: Self.serverAddressDefaultsKey) ?? ""
        var storedKey = ""
        do {
            storedKey = try keychain.read(Self.apiKeyKeychainKey, context: biometricSession.readContext()) ?? ""
        } catch {
            storedKeyUnreadable = true
        }
        self.apiKey = storedKey
    }

    /// Turns the Face ID lock on or off. Face ID is asked first; a refusal changes nothing.
    func setFaceIDLock(_ enabled: Bool) async {
        await changeProtection(enabled: enabled, passcode: lockSettings.allowsPasscode)
    }

    /// Lets the device passcode open the app and the key when Face ID fails.
    func setPasscodeFallback(_ allowed: Bool) async {
        await changeProtection(enabled: lockSettings.isEnabled, passcode: allowed)
    }

    /// Re-saves the stored key under the new protection. The plain text is held in memory
    /// only for the length of the swap. `KeychainStore.save` keeps the old item until the
    /// new one is stored, so a failure needs no restore; it only checks that the key is
    /// still readable and, if not, hands the plain key back to the field.
    private func changeProtection(enabled: Bool, passcode: Bool) async {
        lockMessage = nil
        let target: KeyProtection = enabled ? (passcode ? .biometryOrPasscode : .biometry) : .none
        var storedKey: String?
        var confirmedContext: LAContext?
        do {
            // The confirmation uses the policy in force now, never the one being switched to.
            let context = try await authenticator.authenticate(
                reason: "Изменить защиту ключа API",
                allowPasscode: lockSettings.allowsPasscode
            )
            confirmedContext = context
            var keyIsReadable = true
            do {
                storedKey = try keychain.read(Self.apiKeyKeychainKey, context: context)
            } catch {
                // An unreadable key cannot be re-wrapped, but the lock itself may still be turned off.
                guard storedKeyUnreadable, !enabled else { throw error }
                keyIsReadable = false
            }
            if let key = storedKey {
                try keychain.save(key, for: Self.apiKeyKeychainKey, protection: target)
            }
            lockSettings.isEnabled = enabled
            lockSettings.allowsPasscode = passcode
            faceIDLockEnabled = enabled
            passcodeFallbackEnabled = passcode
            if enabled {
                biometricSession.start(with: context)
            } else {
                biometricSession.end()
            }
            if keyIsReadable {
                storedKeyUnreadable = false
            } else {
                lockMessage = "Защита выключена, но сохранённый ключ API не читается. Введите его заново и нажмите «Сохранить»."
            }
        } catch let failure as BiometricFailure {
            lockMessage = failure.userMessage
        } catch {
            reportFailedProtectionChange(storedKey: storedKey, context: confirmedContext)
        }
    }

    private func reportFailedProtectionChange(storedKey: String?, context: LAContext?) {
        guard let key = storedKey, let context else {
            lockMessage = "Не удалось сменить защиту ключа API."
            return
        }
        // A read error counts as "not confirmed": the plain key then goes back to the field.
        let stillStored = (try? keychain.read(Self.apiKeyKeychainKey, context: context)) == key
        if stillStored {
            lockMessage = "Не удалось сменить защиту ключа API. Ключ остался прежним."
        } else {
            apiKey = key
            storedKeyUnreadable = false
            lockMessage = "Ключ API не сохранён. Он показан в поле: нажмите «Сохранить»."
        }
    }

    /// Persists the server address to UserDefaults and the API key to the Keychain only.
    func saveSettings() throws {
        defaults.set(serverAddress, forKey: Self.serverAddressDefaultsKey)
        let trimmedKey = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmedKey.isEmpty {
            guard !storedKeyUnreadable else { return }
            try keychain.delete(Self.apiKeyKeychainKey)
        } else {
            try keychain.save(trimmedKey, for: Self.apiKeyKeychainKey, protection: lockSettings.keyProtection)
            storedKeyUnreadable = false
        }
    }

    /// Saves current settings, then pings `GET /` on the configured server.
    func checkConnection() async {
        connectionState = .checking
        do {
            try saveSettings()
        } catch {
            connectionState = .failure("Failed to save settings")
            return
        }

        // The address and key were just saved, so the production factory reads back
        // exactly what the user typed — the check runs the same wiring every screen uses.
        guard let client = APIClient.live(defaults: defaults, keychain: keychain, session: session) else {
            connectionState = .failure("Invalid server address")
            return
        }
        do {
            try await client.checkConnection()
            connectionState = .success
        } catch let error as APIClientError {
            connectionState = .failure(error.userMessage)
        } catch {
            connectionState = .failure("Unexpected error")
        }
    }
}
