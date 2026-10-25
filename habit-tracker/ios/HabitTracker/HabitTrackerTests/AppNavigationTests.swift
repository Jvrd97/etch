// [review:need-review] PHASE-01/208
// summary: tests for the root navigation — five tabs in mobile-web order, opening on Today, every former screen behind More
import XCTest
@testable import HabitTracker

final class AppNavigationTests: XCTestCase {
    func testTabBarHasFiveTabsInMobileWebOrder() {
        XCTAssertEqual(AppTab.allCases, [.today, .day, .chat, .health, .more])
        XCTAssertEqual(AppTab.allCases.map(\.title), ["Today", "Day", "Chat", "Health", "More"])
    }

    func testAppOpensOnTodayWithEmptyMoreStack() {
        let navigation = AppNavigation()

        XCTAssertEqual(navigation.selectedTab, .today)
        XCTAssertEqual(navigation.morePath, [])
    }

    func testMoreKeepsEveryScreenThatUsedToBeATab() {
        let formerTabs: [MoreDestination] = [
            .dashboard, .categories, .table, .entries, .journal, .insights, .settings,
        ]

        XCTAssertTrue(Set(formerTabs).isSubset(of: Set(MoreDestination.allCases)))
    }

    func testMoreListsComingSoonScreens() {
        XCTAssertTrue(MoreDestination.allCases.contains(.quickMarks))
        XCTAssertTrue(MoreDestination.allCases.contains(.dailySummary))
    }

    func testOpeningTabSwitchesSelection() {
        var navigation = AppNavigation()
        navigation.selectedTab = .more

        navigation.open(.tab(.today))

        XCTAssertEqual(navigation.selectedTab, .today)
    }

    func testOpeningMoreScreenSelectsMoreAndPushesOnTopOfCurrentStack() {
        var navigation = AppNavigation()
        navigation.open(.more(.dashboard))

        navigation.open(.more(.journal))

        XCTAssertEqual(navigation.selectedTab, .more)
        XCTAssertEqual(navigation.morePath, [.dashboard, .journal])
    }
}
