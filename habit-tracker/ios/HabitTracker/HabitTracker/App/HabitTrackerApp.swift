// [review:need-review] PHASE-01/32-ios-lime-tech-design-pass, PHASE-01/37-ios-insights, PHASE-02/65
// summary: app entry point and tabs, including Health access that starts only when its tab appears
import SwiftUI
import UIKit

/// Tabs of the root `TabView`. Tags let the Dashboard jump to another tab programmatically.
enum AppTab: Hashable {
    case dashboard
    case today
    case table
    case history
    case journal
    case categories
    case insights
    case health
    case settings
}

@main
struct HabitTrackerApp: App {
    @State private var selectedTab: AppTab = .dashboard

    init() {
        Self.configureAppearance()
    }

    var body: some Scene {
        WindowGroup {
            TabView(selection: $selectedTab) {
                DashboardView(viewModel: .live()) { selectedTab = $0 }
                    .tabItem {
                        Label("Dashboard", systemImage: "square.grid.2x2")
                    }
                    .tag(AppTab.dashboard)
                TodayView(viewModel: .live())
                    .tabItem {
                        Label("Today", systemImage: "checkmark.circle")
                    }
                    .tag(AppTab.today)
                TableView(viewModel: .live())
                    .tabItem {
                        Label("Table", systemImage: "tablecells")
                    }
                    .tag(AppTab.table)
                EntriesView(viewModel: .live())
                    .tabItem {
                        Label("History", systemImage: "clock.arrow.circlepath")
                    }
                    .tag(AppTab.history)
                JournalView(viewModel: .live())
                    .tabItem {
                        Label("Journal", systemImage: "book")
                    }
                    .tag(AppTab.journal)
                CategoriesView(viewModel: .live())
                    .tabItem {
                        Label("Categories", systemImage: "folder")
                    }
                    .tag(AppTab.categories)
                InsightsView(viewModel: .live())
                    .tabItem {
                        Label("Insights", systemImage: "sparkles")
                    }
                    .tag(AppTab.insights)
                HealthSyncView(viewModel: .live())
                    .tabItem {
                        Label("Health", systemImage: "heart.text.square")
                    }
                    .tag(AppTab.health)
                SettingsView()
                    .tabItem {
                        Label("Settings", systemImage: "gear")
                    }
                    .tag(AppTab.settings)
            }
            .tint(DS.Palette.lime)
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
