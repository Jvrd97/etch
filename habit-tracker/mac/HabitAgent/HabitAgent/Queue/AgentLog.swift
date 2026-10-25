// [review:need-review] PHASE-03/163
// summary: what an error may say in the agent's log — its domain and code, never the description, which can carry paths or titles
import Foundation

enum AgentLog {
    /// `NSURLErrorDomain -1004`: enough to tell what went wrong, nothing about the person's files or apps.
    static func code(of error: Error) -> String {
        let bridged = error as NSError
        return "\(bridged.domain) \(bridged.code)"
    }
}
