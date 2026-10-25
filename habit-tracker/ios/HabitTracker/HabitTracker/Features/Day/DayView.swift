// [review:need-review] PHASE-01/208
// summary: "coming soon" placeholder for the Day screen; #211 replaces this file
import SwiftUI

/// Placeholder until #211 ports the screen. The replacement keeps a no-argument
/// `init()` (building its view model with `.live()` itself), so `RootView` needs no edit.
struct DayView: View {
    var body: some View {
        ContentUnavailableView(
            AppTab.day.title,
            systemImage: AppTab.day.systemImage,
            description: Text("Скоро здесь будет план дня и факты по нему.")
        )
        .navigationTitle(AppTab.day.title)
        .dsScreenBackground()
    }
}
