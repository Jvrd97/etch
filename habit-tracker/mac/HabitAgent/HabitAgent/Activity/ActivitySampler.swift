// [review:need-review] PHASE-03/155, PHASE-03/163, PHASE-03/217, PHASE-03/172
// summary: samples the foreground app on a timer (5 s, 30 s while idle) and on every switch, builds intervals and queues them on disk; stops for sleep and a locked screen; the flusher sends them
import AppKit
import Combine
import Foundation
import os

@MainActor
final class ActivitySampler: ObservableObject {
    private static let logger = Logger(subsystem: AgentPaths.identifier, category: "ActivitySampler")
    private static let serverAddressKey = "server-address"

    @Published private(set) var status = "Ожидание настройки"
    @Published var serverAddress = UserDefaults.standard.string(forKey: ActivitySampler.serverAddressKey) ?? ""

    private let keychain = KeychainStore()
    private let queueDirectory: URL
    private let idle: IdleMonitor
    private var timer: Timer?
    private var started = false
    private var wakeMonitor: Any?
    private var activationObserver: NSObjectProtocol?
    private var power: PowerObserver?
    private var builder = IntervalBuilder()
    /// True from sleep or screen lock until wake or unlock: nothing is sampled in between.
    private(set) var isPaused = false
    // Opened on the first start: building the sampler touches no file.
    private(set) var store: OutboxStore?
    private var flusher: Flusher?
    private var queueNote = ""

    init(queueDirectory: URL = AgentPaths.directory, idle: IdleMonitor = IdleMonitor()) {
        self.queueDirectory = queueDirectory
        self.idle = idle
    }

    func start() {
        guard !started else { return }
        guard let flusher = openQueue() else { return }
        started = true
        isPaused = false
        flusher.start()
        activationObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification,
            object: nil,
            queue: .main
        ) { [weak self] notification in
            guard let app = notification.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication else { return }
            Task { @MainActor in self?.sample(bundleID: app.bundleIdentifier) }
        }
        let observer = PowerObserver { [weak self] paused in self?.setPaused(paused) }
        observer.start()
        power = observer
        sampleFrontmost()
        scheduleNextSample()
    }

    /// Stops sampling, closes the open interval and sends everything pending.
    func stop() async {
        started = false
        stopTimers()
        power?.stop()
        power = nil
        if let activationObserver { NSWorkspace.shared.notificationCenter.removeObserver(activationObserver) }
        activationObserver = nil
        guard let store, let flusher else { return }
        store.enqueue(builder.finish(at: Date()))
        let summary = await flusher.flush(force: true)
        flusher.stop()
        if summary == nil { status = "Остановлено" + queued() }
    }

    func saveSettings(apiKey: String) {
        UserDefaults.standard.set(serverAddress, forKey: Self.serverAddressKey)
        do {
            try keychain.save(apiKey.trimmingCharacters(in: .whitespacesAndNewlines))
            status = "Настройки сохранены"
        } catch {
            status = "Не удалось сохранить ключ"
        }
    }

    /// Sleep and a locked screen stop collection: the open interval ends at the last input
    /// (the person left then, not when the system noticed) and nothing is sampled until wake or unlock.
    func setPaused(_ paused: Bool, now: Date = Date()) {
        guard paused != isPaused else { return }
        isPaused = paused
        if paused {
            stopTimers()
            let lastInput = now.addingTimeInterval(-idle.secondsSinceLastInput())
            enqueue(builder.finish(at: now, lastInput: lastInput))
            status = "Сбор приостановлен: сон или блокировка экрана"
        } else if started {
            sampleFrontmost()
            scheduleNextSample()
        }
    }

    /// The queue lives on disk, so a kill or a week offline loses nothing. If the
    /// disk is unusable the agent keeps collecting in memory and says so.
    func openQueue() -> Flusher? {
        if let flusher { return flusher }
        // The agent itself comes to the front whenever its menu opens; the
        // catalogue does not carry it, so its time never leaves the mac.
        let own = Set([Bundle.main.bundleIdentifier].compactMap { $0 })
        let opened: OutboxStore
        do {
            opened = try OutboxStore.openWithFallback(directory: queueDirectory, excluding: own)
        } catch {
            Self.logger.error("Queue unavailable: \(AgentLog.code(of: error), privacy: .public); \(String(describing: error), privacy: .private)")
            status = "Очередь недоступна, сбор не запущен"
            return nil
        }
        if !opened.isOnDisk {
            queueNote = "; очередь на диске недоступна, интервалы хранятся только в памяти"
        }
        let opening = Flusher(
            store: opened,
            sender: { [weak self] in self?.makeSender() },
            onFlush: { [weak self] summary in
                guard let self else { return }
                status = describe(summary)
            }
        )
        store = opened
        flusher = opening
        return opening
    }

    private func makeSender() -> Flusher.Sender? {
        guard let apiKey = keychain.read(), !serverAddress.isEmpty else { return nil }
        let client = AgentAPIClient(serverAddress: serverAddress, apiKey: apiKey)
        return { try await client.send($0) }
    }

    private func sampleFrontmost() {
        sample(bundleID: NSWorkspace.shared.frontmostApplication?.bundleIdentifier)
    }

    private func sample(bundleID: String?) {
        sample(bundleID: bundleID, at: Date(), idle: idle.secondsSinceLastInput())
    }

    func sample(bundleID: String?, at date: Date, idle idleSeconds: TimeInterval) {
        guard !isPaused, let bundleID, !bundleID.isEmpty, store != nil else { return }
        enqueue(builder.record(AppSighting(bundleID: bundleID, date: date, idleSeconds: idleSeconds)) + builder.checkpoint())
        status = "Собирается активное приложение" + queued()
    }

    private func enqueue(_ closed: [ActivityInterval]) {
        guard !closed.isEmpty, let store, let flusher else { return }
        store.enqueue(closed)
        flusher.intervalClosed()
    }

    /// One-shot timer: the period follows the idle reading, so an idle mac wakes twice a minute, not twelve times.
    private func scheduleNextSample() {
        timer?.invalidate()
        let period = IdleMonitor.samplingPeriod(idleSeconds: idle.secondsSinceLastInput())
        let next = Timer(timeInterval: period, repeats: false) { [weak self] _ in
            Task { @MainActor in self?.timerFired() }
        }
        next.tolerance = period / 5
        RunLoop.main.add(next, forMode: .common)
        timer = next
        if period == IdleMonitor.idlePeriod {
            armWakeMonitor()
        } else {
            disarmWakeMonitor()
        }
    }

    private func timerFired() {
        guard started, !isPaused else { return }
        sampleFrontmost()
        scheduleNextSample()
    }

    /// While the sampling period is long, the first mouse or scroll event brings the short one back at once.
    /// Mouse events need no permission and the handler reads nothing from them.
    private func armWakeMonitor() {
        guard wakeMonitor == nil else { return }
        wakeMonitor = NSEvent.addGlobalMonitorForEvents(
            matching: [.mouseMoved, .leftMouseDown, .rightMouseDown, .scrollWheel]
        ) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.wakeMonitor != nil else { return }
                self.timerFired()
            }
        }
    }

    private func disarmWakeMonitor() {
        if let wakeMonitor { NSEvent.removeMonitor(wakeMonitor) }
        wakeMonitor = nil
    }

    private func stopTimers() {
        timer?.invalidate()
        timer = nil
        disarmWakeMonitor()
    }

    private func queued() -> String {
        let depth = store?.count ?? 0
        return (depth > 0 ? "; в очереди: \(depth)" : "") + queueNote
    }

    private func describe(_ summary: FlushSummary) -> String {
        var parts = ["Отправлено интервалов: \(summary.sent)"]
        if !summary.droppedBundles.isEmpty {
            parts.append("нет в каталоге, не отправляются: \(summary.droppedBundles.joined(separator: ", "))")
        }
        if summary.droppedInvalid > 0 {
            parts.append("сервер отверг и они отброшены: \(summary.droppedInvalid)")
        }
        if summary.expired > 0 {
            parts.append("не дошли за 14 дней и отброшены: \(summary.expired)")
        }
        if summary.serverRefuses {
            parts.append("сервер отвергает интервалы, повтор позже")
        } else if summary.failed {
            parts.append("сервер недоступен, повтор позже")
        }
        return parts.joined(separator: "; ") + queued()
    }
}
