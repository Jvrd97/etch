// [review:need-review] PHASE-03/132
// summary: failure reports of dead sync runs that the server did not receive, kept in UserDefaults until the next run delivers them; classes only, no health value and no error text
import Foundation

/// A dead run waiting to be told to the server: its id and the report body.
struct HealthPendingFailure: Codable, Equatable {
    let runId: String
    let report: HealthSyncFailureDTO
}

protocol HealthPendingFailureStoring: AnyObject {
    func load() -> [HealthPendingFailure]
    func save(_ failures: [HealthPendingFailure])
}

/// The unsent reports live in `UserDefaults`: a network failure is exactly the case
/// where the report cannot be sent now, and it must survive until the phone is back.
final class UserDefaultsPendingFailures: HealthPendingFailureStoring {
    static let key = "health.pendingFailures"
    /// Older reports are dropped: the server names an unreported run abandoned anyway.
    static let capacity = 10

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func load() -> [HealthPendingFailure] {
        guard let data = defaults.data(forKey: Self.key) else {
            return []
        }
        return (try? JSONDecoder().decode([HealthPendingFailure].self, from: data)) ?? []
    }

    func save(_ failures: [HealthPendingFailure]) {
        let kept = Array(failures.suffix(Self.capacity))
        guard let data = try? JSONEncoder().encode(kept) else {
            return
        }
        defaults.set(data, forKey: Self.key)
    }
}
