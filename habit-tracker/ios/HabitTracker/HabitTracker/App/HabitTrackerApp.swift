// [review:need-review] PHASE-01/32-ios-lime-tech-design-pass, PHASE-01/37-ios-insights, PHASE-02/65, PHASE-01/208, PHASE-01/214, PHASE-03/131
// summary: app entry point — Lime Tech UIKit appearance, the RootView tab bar, the Face ID lock in front of it, and the HealthKit pump run once the lock opens
import SwiftUI
import UIKit

@main
struct HabitTrackerApp: App {
    init() {
        Self.configureAppearance()
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .task { _ = await HealthPump.shared.syncIfAuthorized() }
                .appLock()
                .preferredColorScheme(.dark)
        }
    }

    /// Paints the tab bar and navigation bars in the near-black Lime Tech surfaces,
    /// with lime tint on the active tab. UIKit appearance is the only place SwiftUI
    /// still defers to the system chrome, so the tokens are mirrored here once.
    private static func configureAppearance() {
        let background = UIColor(DS.Palette.background)
        let lime = UIColor(DS.Palette.lime)
        let secondary = UIColor(DS.Palette.textSecondary)

        let tab = UITabBarAppearance()
        tab.configureWithOpaqueBackground()
        tab.backgroundColor = background
        for item in [tab.stackedLayoutAppearance, tab.inlineLayoutAppearance, tab.compactInlineLayoutAppearance] {
            item.selected.iconColor = lime
            item.selected.titleTextAttributes = [.foregroundColor: lime]
            item.normal.iconColor = secondary
            item.normal.titleTextAttributes = [.foregroundColor: secondary]
        }
        UITabBar.appearance().standardAppearance = tab
        UITabBar.appearance().scrollEdgeAppearance = tab

        let nav = UINavigationBarAppearance()
        nav.configureWithOpaqueBackground()
        nav.backgroundColor = background
        nav.shadowColor = .clear
        nav.titleTextAttributes = [.foregroundColor: UIColor.white]
        nav.largeTitleTextAttributes = [.foregroundColor: UIColor.white]
        UINavigationBar.appearance().standardAppearance = nav
        UINavigationBar.appearance().scrollEdgeAppearance = nav
        UINavigationBar.appearance().compactAppearance = nav
        UINavigationBar.appearance().tintColor = lime
    }
}
