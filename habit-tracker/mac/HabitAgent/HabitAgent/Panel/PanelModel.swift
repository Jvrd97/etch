// [review:need-review] PHASE-03/228
// summary: what the floating panel shows and does — the polled config, the timer, whether the config is stale, start and stop on the current task, and the button that opens the day page on the date the window shows; since #162 the day mode, a decision or a reset written for the date the window shows and repainted from the next config; since #228 one mode write at a time (`modeSaving` locks the switcher, a second change is not sent) and a fresh config clears «не сохранилось»
import Combine
import Foundation

@MainActor
final class PanelModel: ObservableObject {
    /// Writes a change of the day mode for a date; throws when the server refused or was unreachable.
    typealias ModeWrite = (_ date: String, _ change: ModeChange) async throws -> Void

    let config: ConditionalPoller<PanelConfig>
    let timer: TaskTimer
    /// The config part of the window has been silent longer than its threshold.
    @Published private(set) var configIsStale = false
    /// The last write of the day mode did not go through; the mode shown is the old one.
    @Published private(set) var modeWriteFailed = false
    /// A write of the day mode is in flight. The window repaints only from the next
    /// config, so a second change built meanwhile would carry the old half of the
    /// first one and switch it back.
    @Published private(set) var modeSaving = false

    private let outbox: ManualIntervalOutbox?
    private let serverAddress: () -> String?
    private let openURL: (URL) -> Void
    private let now: () -> Date
    private let modeWrite: ModeWrite?
    private var observers: [AnyCancellable] = []

    init(
        config: ConditionalPoller<PanelConfig>,
        timer: TaskTimer,
        outbox: ManualIntervalOutbox? = nil,
        serverAddress: @escaping () -> String?,
        openURL: @escaping (URL) -> Void,
        now: @escaping () -> Date = Date.init,
        modeWrite: ModeWrite? = nil
    ) {
        self.config = config
        self.timer = timer
        self.outbox = outbox
        self.serverAddress = serverAddress
        self.openURL = openURL
        self.now = now
        self.modeWrite = modeWrite
        // The poller is a nested object: its changes reach the view through here.
        observers = [
            config.objectWillChange.sink { [weak self] in self?.objectWillChange.send() },
            timer.objectWillChange.sink { [weak self] in self?.objectWillChange.send() },
            // A poll that went through is a fresh look at the server: the mode on screen
            // is its answer, so a note about an earlier refused write no longer fits.
            config.$lastFailure.dropFirst().sink { [weak self] failure in
                if failure == nil { self?.modeWriteFailed = false }
            },
        ]
    }

    var currentTask: PanelConfig.Task? { config.value?.currentTask }

    var dayMode: PanelDayMode? { config.value?.dayMode }

    var dateLabel: String? { config.value?.dateLabel }

    var needsSetup: Bool {
        (config.lastFailure as? PanelAPIError) == .notConfigured
    }

    var canOpenDay: Bool { dayPageURL != nil }

    /// «09:00–11:00», on the clock the person lives by.
    func windowLabel(of task: PanelConfig.Task) -> String {
        "\(Self.clock.string(from: task.startsAt))–\(Self.clock.string(from: task.endsAt))"
    }

    /// Starts the timer on the task the window shows, or stops it. The task is
    /// fixed at the start: the config may move on to the next one while this one runs.
    func toggleTimer() {
        if timer.isRunning {
            timer.stop()
        } else {
            timer.start(task: currentTask.map { TimedTask(id: $0.id, title: $0.title) })
        }
    }

    /// Decides the mode of the date the window shows. Both fields go: the kind and no-code are independent.
    func decideMode(kind: String, nocode: Bool) async {
        await write(.decide(kind: kind, nocode: nocode))
    }

    /// Gives the date the window shows back to the schedule.
    func resetMode() async {
        await write(.reset)
    }

    func openDayInBrowser() {
        guard let url = dayPageURL else { return }
        openURL(url)
    }

    /// Called about once a second by whoever owns the window.
    func tick() {
        timer.tick()
        configIsStale = config.isStale(at: now())
        if let outbox, outbox.isDue { Task { await outbox.flush() } }
    }

    private static let clock: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "HH:mm"
        return formatter
    }()

    /// The window repaints from the server's own answer, not from what was asked for.
    private func write(_ change: ModeChange) async {
        guard !modeSaving, let date = config.value?.date, let modeWrite else { return }
        modeSaving = true
        defer { modeSaving = false }
        do {
            try await modeWrite(date, change)
            modeWriteFailed = false
            await config.pollOnce()
        } catch {
            modeWriteFailed = true
        }
    }

    private var dayPageURL: URL? {
        guard let config = config.value, let address = serverAddress() else { return nil }
        return PanelAPIClient.dayPageURL(serverAddress: address, dayPath: config.dayPath)
    }
}
