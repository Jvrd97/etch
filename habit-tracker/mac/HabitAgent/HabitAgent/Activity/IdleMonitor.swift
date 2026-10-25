// [review:need-review] PHASE-03/172
// summary: reads the time since the last keyboard or mouse event (no permission, no key content) and picks the sampling period from it: 5 seconds while the person works, 30 after a minute of idle
import CoreGraphics
import Foundation

struct IdleMonitor {
    /// Idle longer than this stretches the sampling period and counts as a pause inside an interval.
    static let idleThreshold: TimeInterval = 60
    /// Idle this long means the person left: the open interval ends at the last input.
    /// Same as the task timer's idle threshold, so both stop counting at one moment.
    static let awayThreshold: TimeInterval = 10 * 60
    static let activePeriod: TimeInterval = 5
    static let idlePeriod: TimeInterval = 30
    /// Input this recent means the person is at the mac right now.
    static let freshInputThreshold: TimeInterval = 5
    /// While collection is paused, how often to check that the wake or unlock notification did not get lost.
    /// Not shorter than the idle sampling period, so a paused mac wakes no more often than an idle one.
    static let pausedProbePeriod: TimeInterval = idlePeriod
    /// The system may fire a timer this late, as a fraction of its period. App Nap stretches it further.
    static let timerToleranceFraction = 0.2

    /// Seconds since the last keyboard, mouse or trackpad event of the session.
    var secondsSinceLastInput: () -> TimeInterval = TaskTimer.systemSecondsSinceLastInput

    /// True while the session reports a locked screen. The `CGSSessionScreenIsLocked` key exists
    /// only while the screen is locked, so no key means not locked: that is normal, not a failed read.
    static func isScreenLocked() -> Bool {
        let session = CGSessionCopyCurrentDictionary() as? [String: Any]
        return session?["CGSSessionScreenIsLocked"] as? Bool ?? false
    }

    static func samplingPeriod(idleSeconds: TimeInterval) -> TimeInterval {
        idleSeconds > idleThreshold ? idlePeriod : activePeriod
    }
}
