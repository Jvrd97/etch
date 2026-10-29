// [review:need-review] PHASE-03/132
// summary: a stable per-install device id for the sync journal — a random UUID kept in UserDefaults, never the advertising id
import Foundation

/// Names this install to the server journal, so a second phone or a reinstall is
/// visible as a different device. A random UUID rather than the advertising id or
/// the vendor id: it identifies nothing outside this app and is not tracking.
enum HealthDeviceID {
    static let key = "health.deviceId"

    /// The saved id, minted on first use.
    static func current() -> String {
        current(in: .standard)
    }

    static func current(in defaults: UserDefaults) -> String {
        if let saved = defaults.string(forKey: key) {
            return saved
        }
        let minted = UUID().uuidString
        defaults.set(minted, forKey: key)
        return minted
    }
}
