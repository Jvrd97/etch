// [review:need-review] PHASE-03/159, PHASE-03/170
// summary: since #170 also builds the quick marks row and polls it only while the window is visible; puts the floating panel together and runs it (since #162 also the write of the day mode through the same client) — the config poller, the one-second tick, the window, the outbox of timer intervals — and stops the timer when the app quits
import AppKit
import Combine
import Foundation

@MainActor
final class PanelHost: ObservableObject {
    /// How often the window asks for the config. The ETag makes an unchanged answer a 304.
    static let configPollInterval: TimeInterval = 30
    /// Silence longer than this marks the config part of the window as not fresh.
    static let configStaleAfter: TimeInterval = 120
    /// The shared backoff grows to ten minutes; a window that must notice the network coming back waits less.
    static let configMaxRetryDelay: TimeInterval = 60
    private static let tickInterval: TimeInterval = 1

    /// The server address is read on every redraw; the key sits in the Keychain
    /// and is read only when a request is about to go out.
    typealias ServerAddress = () -> String?
    typealias APIKey = () -> String?

    /// The label of the menu item that shows or hides the window follows this.
    @Published private(set) var isPanelVisible = false

    private let outbox: ManualIntervalOutbox
    private let model: PanelModel
    private let quickMarks: QuickMarksModel
    private var controller: FloatingPanelController?
    private var pollTask: Task<Void, Never>?
    private var ticker: Timer?
    private var terminationObserver: NSObjectProtocol?

    /// The test host launches the real app; it must neither open a window nor
    /// touch the person's saved frame and settings.
    static var isRunningTests: Bool {
        ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil
    }

    init(serverAddress: @escaping ServerAddress, apiKey: @escaping APIKey) {
        let client: () throws -> PanelAPIClient = {
            guard let address = serverAddress(), let key = apiKey() else { throw PanelAPIError.notConfigured }
            return PanelAPIClient(serverAddress: address, apiKey: key)
        }
        let outbox = ManualIntervalOutbox(fileURL: ManualIntervalOutbox.defaultFileURL()) { interval in
            try await client().send(interval)
        }
        let config = ConditionalPoller<PanelConfig>(
            interval: Self.configPollInterval,
            staleAfter: Self.configStaleAfter,
            maxRetryDelay: Self.configMaxRetryDelay
        ) { etag in
            try await client().fetchConfig(etag: etag)
        }
        let agentClient: () throws -> AgentAPIClient = {
            guard let address = serverAddress(), let key = apiKey() else { throw PanelAPIError.notConfigured }
            return AgentAPIClient(serverAddress: address, apiKey: key)
        }
        let quickMarks = QuickMarksModel(
            outboxFile: QuickMarkOutbox.defaultFileURL(),
            serverAddress: serverAddress,
            openURL: { NSWorkspace.shared.open($0) },
            fetch: { etag in try await agentClient().fetchQuickMarks(etag: etag) },
            post: { tap in try await agentClient().send(tap) }
        )
        self.outbox = outbox
        self.quickMarks = quickMarks
        model = PanelModel(
            config: config,
            timer: TaskTimer(emit: { outbox.enqueue($0) }),
            quickMarks: quickMarks,
            outbox: outbox,
            serverAddress: serverAddress,
            openURL: { NSWorkspace.shared.open($0) },
            modeWrite: { date, change in try await client().change(mode: change, date: date) }
        )
    }

    func start() {
        guard !Self.isRunningTests, controller == nil else { return }
        let controller = FloatingPanelController(model: model)
        controller.onVisibilityChange = { [weak self] visible in
            self?.isPanelVisible = visible
            // A hidden window asks nobody: the row behind it is for no one.
            if visible { self?.quickMarks.startPolling() } else { self?.quickMarks.stopPolling() }
        }
        self.controller = controller
        if controller.wasVisibleLastTime { controller.show() }

        let config = model.config
        pollTask = Task { await config.run() }
        // In the common modes, so that the clock keeps running while the panel is
        // being dragged or a menu is open, not only while the run loop is idle.
        let ticker = Timer(timeInterval: Self.tickInterval, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.model.tick() }
        }
        RunLoop.main.add(ticker, forMode: .common)
        self.ticker = ticker
        // Quitting through the system (log out, update) skips the menu: the open
        // interval is still written down, to the file the next launch resends.
        terminationObserver = NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.model.timer.stop() }
        }
        Task { await outbox.flush() }
    }

    func togglePanel() {
        controller?.toggle()
    }

    /// Closes the open interval and sends what is waiting. The file keeps the rest.
    func shutdown() async {
        pollTask?.cancel()
        quickMarks.stopPolling()
        ticker?.invalidate()
        model.timer.stop()
        await outbox.flush(force: true)
        await quickMarks.outbox.flush(force: true)
    }
}
