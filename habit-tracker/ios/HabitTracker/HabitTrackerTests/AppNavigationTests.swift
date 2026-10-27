// [review:need-review] PHASE-01/208, PHASE-03/230
// summary: tests for the root navigation — five tabs in mobile-web order, opening on Today, every former screen behind More; a More screen holding an unconfirmed write cannot be popped by the system (a second tap on the selected tab), every other pop and every push goes through
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

    // MARK: - A screen that must not be left unasked

    func testTheSystemPopsTheMoreStackToItsRootWhenNothingIsHeld() {
        var navigation = AppNavigation()
        navigation.open(.more(.dailySummary))

        navigation.setMorePath([])

        XCTAssertEqual(navigation.morePath, [])
    }

    func testAHeldMoreScreenRefusesThePopToTheRoot() {
        var navigation = AppNavigation()
        navigation.open(.more(.dailySummary))
        navigation.moreLeaveBlocked = true

        navigation.setMorePath([])

        XCTAssertEqual(navigation.morePath, [.dailySummary])
    }

    func testAHeldMoreScreenStillAllowsPushesAndTheScreensOwnLeave() {
        var navigation = AppNavigation()
        navigation.open(.more(.dashboard))
        navigation.moreLeaveBlocked = true

        navigation.setMorePath([.dashboard, .journal])
        XCTAssertEqual(navigation.morePath, [.dashboard, .journal])

        navigation.moreLeaveBlocked = false
        navigation.setMorePath([])
        XCTAssertEqual(navigation.morePath, [])
    }

    func testARefusedPopChangesTheStateSoTheStackIsDrawnAgain() {
        var navigation = AppNavigation()
        navigation.open(.more(.dailySummary))
        navigation.moreLeaveBlocked = true
        let before = navigation

        navigation.setMorePath([])

        XCTAssertNotEqual(navigation, before, "an unchanged value would not redraw the stack the system already popped")
    }
}
