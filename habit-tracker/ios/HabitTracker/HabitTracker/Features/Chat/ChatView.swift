// [review:need-review] PHASE-01/208
// summary: "coming soon" placeholder for the Chat screen; #212 replaces this file
import SwiftUI

/// Placeholder until #212 ports the screen. The replacement keeps a no-argument
/// `init()` (building its view model with `.live()` itself), so `RootView` needs no edit.
struct ChatView: View {
    var body: some View {
        ContentUnavailableView(
            AppTab.chat.title,
            systemImage: AppTab.chat.systemImage,
            description: Text("Скоро здесь будет чат с ассистентом и история разговоров.")
        )
        .navigationTitle(AppTab.chat.title)
        .dsScreenBackground()
    }
}
