// [review:need-review] PHASE-03/172
// summary: turns sleep, display sleep and screen lock notifications into one paused/running signal; the screen stays paused until every reason has gone
import AppKit
import Foundation

@MainActor
final class PowerObserver {
    enum Event {
        case willSleep, didWake
        case screensDidSleep, screensDidWake
        case screenLocked, screenUnlocked
    }

    private enum Reason {
        case sleep, display, lock
    }

    private static let lockedName = Notification.Name("com.apple.screenIsLocked")
    private static let unlockedName = Notification.Name("com.apple.screenIsUnlocked")

    private let onChange: (Bool) -> Void
    private var reasons: Set<Reason> = []
    private var tokens: [(center: NotificationCenter, token: NSObjectProtocol)] = []

    var isPaused: Bool { !reasons.isEmpty }

    /// `onChange` is called with `true` when the first reason to pause appears and with `false` when the last one goes.
    init(onChange: @escaping (Bool) -> Void) {
        self.onChange = onChange
    }

    func start() {
        guard tokens.isEmpty else { return }
        let workspace = NSWorkspace.shared.notificationCenter
        let distributed = DistributedNotificationCenter.default()
        observe(workspace, NSWorkspace.willSleepNotification, .willSleep)
        observe(workspace, NSWorkspace.didWakeNotification, .didWake)
        observe(workspace, NSWorkspace.screensDidSleepNotification, .screensDidSleep)
        observe(workspace, NSWorkspace.screensDidWakeNotification, .screensDidWake)
        observe(distributed, Self.lockedName, .screenLocked)
        observe(distributed, Self.unlockedName, .screenUnlocked)
    }

    func stop() {
        for entry in tokens { entry.center.removeObserver(entry.token) }
        tokens = []
        reasons = []
    }

    func handle(_ event: Event) {
        let wasPaused = isPaused
        switch event {
        case .willSleep: reasons.insert(.sleep)
        case .didWake: reasons.remove(.sleep)
        case .screensDidSleep: reasons.insert(.display)
        case .screensDidWake: reasons.remove(.display)
        case .screenLocked: reasons.insert(.lock)
        case .screenUnlocked: reasons.remove(.lock)
        }
        if isPaused != wasPaused { onChange(isPaused) }
    }

    /// The handler runs on the main thread at once: a sleep notification handled later would close the interval after the wake-up.
    private func observe(_ center: NotificationCenter, _ name: Notification.Name, _ event: Event) {
        let token = center.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.handle(event) }
        }
        tokens.append((center, token))
    }
}
