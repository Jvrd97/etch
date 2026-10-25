// [review:need-review] PHASE-01/208
// summary: "coming soon" placeholder for the QuickMarks screen; #210 replaces this file
import SwiftUI

/// Placeholder until #210 ports the screen. The replacement keeps a no-argument
/// `init()` (building its view model with `.live()` itself), so `RootView` needs no edit.
struct QuickMarksView: View {
    var body: some View {
        ContentUnavailableView(
            MoreDestination.quickMarks.title,
            systemImage: MoreDestination.quickMarks.systemImage,
            description: Text("Скоро здесь будут отметки привычек в одно касание.")
        )
        .navigationTitle(MoreDestination.quickMarks.title)
        .dsScreenBackground()
    }
}
