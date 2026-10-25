// [review:need-review] PHASE-01/208
// summary: "coming soon" placeholder for the DailySummary screen; #213 replaces this file
import SwiftUI

/// Placeholder until #213 ports the screen. The replacement keeps a no-argument
/// `init()` (building its view model with `.live()` itself), so `RootView` needs no edit.
struct DailySummaryView: View {
    var body: some View {
        ContentUnavailableView(
            MoreDestination.dailySummary.title,
            systemImage: MoreDestination.dailySummary.systemImage,
            description: Text("Скоро здесь будет итог дня голосом или текстом, с предпросмотром до записи.")
        )
        .navigationTitle(MoreDestination.dailySummary.title)
        .dsScreenBackground()
    }
}
