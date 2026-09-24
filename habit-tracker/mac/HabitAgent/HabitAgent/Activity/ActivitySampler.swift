// [review:approved] PHASE-03/155
// summary: samples the foreground app on a timer and on every switch, builds intervals and hands them to the outbox
import AppKit
import Combine
import Foundation

@MainActor
final class ActivitySampler: ObservableObject {
    static let samplingInterval: TimeInterval = 5
    private static let serverAddressKey = "server-address"

    @Published private(set) var status = "Ожидание настройки"
    @Published var serverAddress = UserDefaults.standard.string(forKey: ActivitySampler.serverAddressKey) ?? ""

    private let keychain = KeychainStore()
    private var timer: Timer?
    private var activationObserver: NSObjectProtocol?
    private var builder = IntervalBuilder()
    // The agent itself comes to the front whenever its menu opens; the
    // catalogue does not carry it, so its time never leaves the mac.
    private let outbox = IntervalOutbox(excluding: Set([Bundle.main.bundleIdentifier].compactMap { $0 }))

    func start() {
        guard timer == nil else { return }
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
        outbox.enqueue(builder.finish(at: Date()))
        await flush(force: true)
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

    private func sample(bundleID: String?) {
        guard let bundleID, !bundleID.isEmpty else { return }
        outbox.enqueue(builder.record(AppSighting(bundleID: bundleID, date: Date())))
        status = "Собирается активное приложение"
        Task { await flush(force: false) }
    }

    private func flush(force: Bool) async {
        guard let apiKey = keychain.read(), !serverAddress.isEmpty else { return }
        let client = AgentAPIClient(serverAddress: serverAddress, apiKey: apiKey)
        guard let summary = await outbox.flush(force: force, send: { try await client.send($0) }) else { return }
        status = Self.describe(summary)
    }

    private static func describe(_ summary: FlushSummary) -> String {
        var parts = ["Отправлено интервалов: \(summary.sent)"]
        if !summary.droppedBundles.isEmpty {
            parts.append("нет в каталоге, не отправляются: \(summary.droppedBundles.joined(separator: ", "))")
        }
        if summary.droppedInvalid > 0 {
            parts.append("сервер отверг и они отброшены: \(summary.droppedInvalid)")
        }
        if summary.failed {
            parts.append("сервер недоступен, повтор позже")
        }
        return parts.joined(separator: "; ")
    }
}
