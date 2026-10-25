// [review:need-review] PHASE-03/155, PHASE-03/163
// summary: samples the foreground app on a timer and on every switch, builds intervals and queues them on disk; the flusher sends them
import AppKit
import Combine
import Foundation
import os

@MainActor
final class ActivitySampler: ObservableObject {
    static let samplingInterval: TimeInterval = 5
    private static let logger = Logger(subsystem: AgentPaths.identifier, category: "ActivitySampler")
    private static let serverAddressKey = "server-address"

    @Published private(set) var status = "Ожидание настройки"
    @Published var serverAddress = UserDefaults.standard.string(forKey: ActivitySampler.serverAddressKey) ?? ""

    private let keychain = KeychainStore()
    private var timer: Timer?
    private var activationObserver: NSObjectProtocol?
    private var builder = IntervalBuilder()
    // Opened on the first start: building the sampler touches no file.
    private var store: OutboxStore?
    private var flusher: Flusher?
    private var queueNote = ""

    func start() {
        guard timer == nil else { return }
        guard let flusher = openQueue() else { return }
        flusher.start()
        activationObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification,
            object: nil,
            queue: .main
        ) { [weak self] notification in
            guard let app = notification.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication else { return }
            Task { @MainActor in self?.sample(bundleID: app.bundleIdentifier) }
        }
        timer = Timer.scheduledTimer(withTimeInterval: Self.samplingInterval, repeats: true) { [weak self] _ in
            let app = NSWorkspace.shared.frontmostApplication
            Task { @MainActor in self?.sample(bundleID: app?.bundleIdentifier) }
        }
        sample(bundleID: NSWorkspace.shared.frontmostApplication?.bundleIdentifier)
    }

    /// Stops sampling, closes the open interval and sends everything pending.
    func stop() async {
        timer?.invalidate()
        timer = nil
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

    /// The queue lives on disk, so a kill or a week offline loses nothing. If the
    /// disk is unusable the agent keeps collecting in memory and says so.
    private func openQueue() -> Flusher? {
        if let flusher { return flusher }
        // The agent itself comes to the front whenever its menu opens; the
        // catalogue does not carry it, so its time never leaves the mac.
        let own = Set([Bundle.main.bundleIdentifier].compactMap { $0 })
        let opened: OutboxStore
        do {
            opened = try OutboxStore.openWithFallback(excluding: own)
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

    private func sample(bundleID: String?) {
        guard let bundleID, !bundleID.isEmpty, let store, let flusher else { return }
        let closed = builder.record(AppSighting(bundleID: bundleID, date: Date()))
        if !closed.isEmpty {
            store.enqueue(closed)
            flusher.intervalClosed()
        }
        status = "Собирается активное приложение" + queued()
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
