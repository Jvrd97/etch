// [review:need-review] PHASE-01/214
// summary: Face ID / device-passcode check behind a protocol, so lock logic is testable with a fake; LocalAuthenticator is the LAContext implementation
import Foundation
import LocalAuthentication

/// Why an authentication did not succeed.
enum BiometricFailure: Error, Equatable {
    /// The person dismissed the prompt, or the system did (app went inactive).
    case cancelled
    /// No Face ID enrolled / no passcode set / biometry locked out.
    case unavailable
    /// Face ID did not match and no retry was taken.
    case failed

    var userMessage: String {
        switch self {
        case .cancelled: return "Проверка отменена. Нажмите «Открыть», чтобы повторить."
        case .unavailable: return "Face ID недоступен на этом устройстве. Включите его в настройках iPhone."
        case .failed: return "Face ID не распознал вас. Нажмите «Открыть», чтобы повторить."
        }
    }
}

/// Proves that the device owner is present. Returns the evaluated `LAContext`: a
/// Keychain read that carries it needs no second prompt.
@MainActor
protocol BiometricAuthenticating: AnyObject {
    func authenticate(reason: String, allowPasscode: Bool) async throws -> LAContext
}

@MainActor
final class LocalAuthenticator: BiometricAuthenticating {
    nonisolated init() {}

    func authenticate(reason: String, allowPasscode: Bool) async throws -> LAContext {
        let context = LAContext()
        // Biometry only by default: the passcode is an explicit choice in Settings.
        let policy: LAPolicy = allowPasscode ? .deviceOwnerAuthentication : .deviceOwnerAuthenticationWithBiometrics
        var availabilityError: NSError?
        guard context.canEvaluatePolicy(policy, error: &availabilityError) else {
            throw BiometricFailure.unavailable
        }
        do {
            let matched = try await context.evaluatePolicy(policy, localizedReason: reason)
            guard matched else { throw BiometricFailure.failed }
            return context
        } catch let error as LAError {
            throw Self.failure(for: error.code)
        }
    }

    static func failure(for code: LAError.Code) -> BiometricFailure {
        switch code {
        case .userCancel, .systemCancel, .appCancel, .userFallback:
            return .cancelled
        case .biometryNotAvailable, .biometryNotEnrolled, .biometryLockout, .passcodeNotSet:
            return .unavailable
        default:
            return .failed
        }
    }
}
