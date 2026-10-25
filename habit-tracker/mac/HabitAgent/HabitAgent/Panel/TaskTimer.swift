// [review:need-review] PHASE-03/159
// summary: the panel's stopwatch — start and stop write one manual interval for the task; a stretch with no keyboard or mouse input past the threshold, or a sleep of the Mac, stops it and cuts the end at the last input rather than at the moment the person came back
import AppKit
import Foundation

struct TimedTask: Equatable {
    let id: UUID
    let title: String
}

/// A stretch of work the person timed, as `POST /agent/activity/manual` takes it.
struct ManualInterval: Equatable, Codable {
    /// `Idempotency-Key`. Stays the same through every retry of this interval.
    let key: UUID
    let startedAt: Date
    let endedAt: Date
    let localDate: String
    let utcOffsetMinutes: Int
    let taskID: UUID?
    let taskTitle: String?

    /// Both ends are cut to whole seconds here, once. They are sent and stored in
    /// whole seconds, and a retry of the same key with different ends is a 409.
    init(key: UUID = UUID(), startedAt: Date, endedAt: Date, task: TimedTask?, timeZone: TimeZone = .current) {
        self.key = key
        self.startedAt = Date(timeIntervalSince1970: startedAt.timeIntervalSince1970.rounded(.down))
        self.endedAt = Date(timeIntervalSince1970: endedAt.timeIntervalSince1970.rounded(.down))
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withFullDate]
        formatter.timeZone = timeZone
        localDate = formatter.string(from: startedAt)
        utcOffsetMinutes = timeZone.secondsFromGMT(for: startedAt) / 60
        taskID = task?.id
        taskTitle = task?.title
    }
}

/// Stopwatch of the floating panel.
///
/// It is passive: whoever owns it calls `tick()` about once a second. That keeps
/// the clock and the idle reading injectable, which is what the cases that
/// matter — forty minutes away, a closed lid — need in order to be tested.
@MainActor
final class TaskTimer: ObservableObject {
    /// No input for this long and the timer stops.
    static let idleThreshold: TimeInterval = 10 * 60
    /// Ticks further apart than this mean the process was not running: the Mac slept.
    static let suspendGap: TimeInterval = 60
    /// A shorter stretch carries no time and is not written.
    static let minimumDuration: TimeInterval = 1

    enum State: Equatable {
        case idle
        case running(since: Date, task: TimedTask?)
    }

    enum StopReason: Equatable {
        case manual
        /// No input since this moment, which is where the interval ends.
        case idle(since: Date)
        /// The Mac slept; the interval ends at the last moment the timer knew it was awake.
        case suspended(since: Date)
    }

    @Published private(set) var state: State = .idle
    @Published private(set) var elapsed: TimeInterval = 0
    @Published private(set) var lastStop: StopReason?

    private let now: () -> Date
    private let secondsSinceLastInput: () -> TimeInterval
    private let timeZone: TimeZone
    private let emit: (ManualInterval) -> Void
    private var lastTickAt: Date?
    private var appNapBlock: NSObjectProtocol?

    init(
        emit: @escaping (ManualInterval) -> Void,
        now: @escaping () -> Date = Date.init,
        secondsSinceLastInput: @escaping () -> TimeInterval = TaskTimer.systemSecondsSinceLastInput,
        timeZone: TimeZone = .current
    ) {
        self.emit = emit
        self.now = now
        self.secondsSinceLastInput = secondsSinceLastInput
        self.timeZone = timeZone
    }

    var isRunning: Bool {
        if case .running = state { return true }
        return false
    }

    var task: TimedTask? {
        if case let .running(_, task) = state { return task }
        return nil
    }

    /// Seconds since the last keyboard, mouse or trackpad event of the session.
    /// Needs no permission and cannot see what was pressed.
    nonisolated static func systemSecondsSinceLastInput() -> TimeInterval {
        // kCGAnyInputEventType, which Swift does not export as a case.
        let anyInput = CGEventType(rawValue: ~0)!
        return CGEventSource.secondsSinceLastEventType(.combinedSessionState, eventType: anyInput)
    }

    func start(task: TimedTask?) {
        guard !isRunning else { return }
        let started = now()
        state = .running(since: started, task: task)
        elapsed = 0
        lastTickAt = started
        lastStop = nil
        // A timer that is hidden in the menu bar must not be throttled into
        // ticks far enough apart to look like a sleep.
        appNapBlock = ProcessInfo.processInfo.beginActivity(
            options: .userInitiatedAllowingIdleSystemSleep,
            reason: "Task timer"
        )
    }

    func stop() {
        finish(at: now(), reason: .manual)
    }

    func tick() {
        guard case let .running(startedAt, _) = state else { return }
        let current = now()
        let idle = secondsSinceLastInput()
        let lastInput = current.addingTimeInterval(-idle)
        if let previous = lastTickAt, current.timeIntervalSince(previous) > Self.suspendGap {
            // Whether the idle reading counts the sleep depends on the OS, so the
            // earlier of the two is the end: the person was surely there until then.
            let end = min(previous, lastInput)
            finish(at: end, reason: .suspended(since: end))
            return
        }
        if idle >= Self.idleThreshold {
            finish(at: lastInput, reason: .idle(since: lastInput))
            return
        }
        lastTickAt = current
        elapsed = max(0, current.timeIntervalSince(startedAt))
    }

    private func finish(at end: Date, reason: StopReason) {
        guard case let .running(startedAt, task) = state else { return }
        let closedAt = max(end, startedAt)
        state = .idle
        elapsed = 0
        lastTickAt = nil
        lastStop = reason
        if let appNapBlock { ProcessInfo.processInfo.endActivity(appNapBlock) }
        appNapBlock = nil
        guard closedAt.timeIntervalSince(startedAt) >= Self.minimumDuration else { return }
        emit(ManualInterval(startedAt: startedAt, endedAt: closedAt, task: task, timeZone: timeZone))
    }
}
