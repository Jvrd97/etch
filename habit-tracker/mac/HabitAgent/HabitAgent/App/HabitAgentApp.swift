// [review:approved] PHASE-03/155
// summary: menu bar app with server and API key settings for the activity sampler; quitting sends what is pending first
import SwiftUI

@main
struct HabitAgentApp: App {
    @StateObject private var sampler = ActivitySampler()
    @State private var apiKey = ""

    var body: some Scene {
        MenuBarExtra("Habit Agent", systemImage: "clock") {
            Text(sampler.status)
            TextField("Адрес сервера", text: $sampler.serverAddress)
                .textFieldStyle(.roundedBorder)
            SecureField("X-API-Key", text: $apiKey)
                .textFieldStyle(.roundedBorder)
            Button("Сохранить настройки") { sampler.saveSettings(apiKey: apiKey) }
            Divider()
            Button("Начать сбор") { sampler.start() }
            Button("Остановить и отправить") { Task { await sampler.stop() } }
            Button("Выйти") {
                Task {
                    await sampler.stop()
                    NSApplication.shared.terminate(nil)
                }
            }
        }
        .menuBarExtraStyle(.window)
    }
}
