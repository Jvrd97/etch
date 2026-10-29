// [review:need-review] PHASE-01/208, PHASE-03/229, PHASE-03/230, PHASE-03/250
// [review:need-review] PHASE-03/240 — the «Добавки» row under More (one case, one title, one icon, one screen line)
// summary: root tab bar (Today, Day, Chat, Health, More) — each tab owns one NavigationStack, More lists the remaining screens (+ the Неделя row under More, #229; the More stack hands its pushed screens a hold/release by token, so several instances of one screen cannot lift each other's block, #250)
import SwiftUI

/// The app's root: one `NavigationStack` per tab, screens never create their own.
struct RootView: View {
    @State private var navigation = AppNavigation()
    @State private var summaryRetainer = DailySummaryRetainer()

    var body: some View {
        TabView(selection: $navigation.selectedTab) {
            ForEach(AppTab.allCases) { tab in
                content(for: tab)
                    .tabItem { Label(tab.title, systemImage: tab.systemImage) }
                    .tag(tab)
            }
        }
        .tint(DS.Palette.lime)
    }

    @ViewBuilder
    private func content(for tab: AppTab) -> some View {
        switch tab {
        case .today:
            NavigationStack { TodayView(viewModel: .live()) }
        case .day:
            NavigationStack { DayView() }
        case .chat:
            NavigationStack { ChatView() }
        case .health:
            NavigationStack { HealthSyncView(viewModel: .live()) }
        case .more:
            NavigationStack(path: Binding(get: { navigation.morePath }, set: { navigation.setMorePath($0) })) {
                MoreList()
                    .navigationDestination(for: MoreDestination.self) { screen(for: $0) }
            }
            .environment(
                \.moreLeaveHold,
                MoreLeaveHold(
                    // Only a real change touches the state: a write that changes nothing still redraws the root.
                    hold: { if !navigation.moreLeaveHolders.contains($0) { navigation.holdMoreLeave($0) } },
                    release: { if navigation.moreLeaveHolders.contains($0) { navigation.releaseMoreLeave($0) } }
                )
            )
        }
    }

    @ViewBuilder
    private func screen(for destination: MoreDestination) -> some View {
        switch destination {
        case .dashboard:
            DashboardView(viewModel: .live()) { navigation.open($0) }
        case .quickMarks:
            QuickMarksView()
        case .dailySummary:
            DailySummaryView(retainer: summaryRetainer)
        case .week:
            WeekView()
        case .supplements:
            SupplementsView()
        case .roles:
            RolesView()
        case .categories:
            CategoriesView(viewModel: .live())
        case .table:
            TableView(viewModel: .live())
        case .entries:
            EntriesView(viewModel: .live())
        case .journal:
            JournalView(viewModel: .live())
        case .insights:
            InsightsView(viewModel: .live())
        case .settings:
            SettingsView()
        }
    }
}

/// Root of the More tab: every screen that has no tab of its own.
private struct MoreList: View {
    var body: some View {
        List(MoreDestination.allCases) { destination in
            NavigationLink(value: destination) {
                Label(destination.title, systemImage: destination.systemImage)
                    .foregroundStyle(DS.Palette.textPrimary)
            }
            .listRowBackground(DS.Palette.card)
        }
        .navigationTitle(AppTab.more.title)
        // Inline, and inherited by every screen pushed here: on the iOS 26 simulator a
        // large title of a scrolling screen that was not on screen at launch renders
        // blank (the baseline History tab shows the same); inline titles render.
        .navigationBarTitleDisplayMode(.inline)
        .dsScreenBackground()
    }
}
