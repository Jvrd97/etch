// [review:need-review] PHASE-03/172
// summary: reads the time since the last keyboard or mouse event (no permission, no key content) and picks the sampling period from it: 5 seconds while the person works, 30 after a minute of idle
import Foundation

struct IdleMonitor {
    /// Idle longer than this stretches the sampling period and counts as a pause inside an interval.
    static let idleThreshold: TimeInterval = 60
    /// Idle this long means the person left: the open interval ends at the last input.
    /// Same as the task timer's idle threshold, so both stop counting at one moment.
    static let awayThreshold: TimeInterval = 10 * 60
    static let activePeriod: TimeInterval = 5
    static let idlePeriod: TimeInterval = 30

    /// Seconds since the last keyboard, mouse or trackpad event of the session.
    var secondsSinceLastInput: () -> TimeInterval = TaskTimer.systemSecondsSinceLastInput

    static func samplingPeriod(idleSeconds: TimeInterval) -> TimeInterval {
        idleSeconds > idleThreshold ? idlePeriod : activePeriod
    }
}
