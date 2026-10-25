// [review:need-review] PHASE-03/155, PHASE-03/159
// summary: menu bar app with server and API key settings for the activity sampler; quitting sends what is pending first; since #159 it also opens the floating task-and-timer window at launch and lets the menu hide and show it
import SwiftUI

@main
struct HabitAgentApp: App {
    @StateObject private var sampler: ActivitySampler
    @StateObject private var panel: PanelHost
    @State private var apiKey = ""

    init() {
        let sampler = ActivitySampler()
        let keychain = KeychainStore()
        // The window asks with what the sampler sends with: one address, one key.
        let panel = PanelHost(
            serverAddress: { [weak sampler] in sampler.flatMap { $0.serverAddress.isEmpty ? nil : $0.serverAddress } },
            apiKey: { keychain.read() }
        )
        _sampler = StateObject(wrappedValue: sampler)
        _panel = StateObject(wrappedValue: panel)
        // After the launch has finished, not inside `init`.
        Task { @MainActor in panel.start() }
    }

    var body: some Scene {
        MenuBarExtra("Habit Agent", systemImage: "clock") {
            Text(sampler.status)
            TextField("Адрес сервера", text: $sampler.serverAddress)
                .textFieldStyle(.roundedBorder)
            SecureField("X-API-Key", text: $apiKey)
                .textFieldStyle(.roundedBorder)
            Button("Сохранить настройки") { sampler.saveSettings(apiKey: apiKey) }
            Divider()
            Button(panel.isPanelVisible ? "Свернуть окно" : "Показать окно") { panel.togglePanel() }
            Divider()
            Button("Начать сбор") { sampler.start() }
            Button("Остановить и отправить") { Task { await sampler.stop() } }
            Button("Выйти") {
                Task {
                    await panel.shutdown()
                    await sampler.stop()
                    NSApplication.shared.terminate(nil)
                }
            }
        }
        .menuBarExtraStyle(.window)
    }
}
