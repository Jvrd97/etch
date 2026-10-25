// [review:need-review] PHASE-03/159
// summary: what the floating panel shows and does — the polled config, the timer, whether the config is stale, start and stop on the current task, and the button that opens the day page on the date the window shows
import Combine
import Foundation

@MainActor
final class PanelModel: ObservableObject {
    let config: ConditionalPoller<PanelConfig>
    let timer: TaskTimer
    /// The config part of the window has been silent longer than its threshold.
    @Published private(set) var configIsStale = false

    private let outbox: ManualIntervalOutbox?
    private let serverAddress: () -> String?
    private let openURL: (URL) -> Void
    private let now: () -> Date
    private var observers: [AnyCancellable] = []

    init(
        config: ConditionalPoller<PanelConfig>,
        timer: TaskTimer,
        outbox: ManualIntervalOutbox? = nil,
        serverAddress: @escaping () -> String?,
        openURL: @escaping (URL) -> Void,
        now: @escaping () -> Date = Date.init
    ) {
        self.config = config
        self.timer = timer
        self.outbox = outbox
        self.serverAddress = serverAddress
        self.openURL = openURL
        self.now = now
        // The poller is a nested object: its changes reach the view through here.
        observers = [
            config.objectWillChange.sink { [weak self] in self?.objectWillChange.send() },
            timer.objectWillChange.sink { [weak self] in self?.objectWillChange.send() },
        ]
    }

    var currentTask: PanelConfig.Task? { config.value?.currentTask }

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

    private var dayPageURL: URL? {
        guard let config = config.value, let address = serverAddress() else { return nil }
        return PanelAPIClient.dayPageURL(serverAddress: address, dayPath: config.dayPath)
    }
}
