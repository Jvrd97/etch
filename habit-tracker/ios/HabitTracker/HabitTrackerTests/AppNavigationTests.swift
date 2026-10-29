// [review:need-review] PHASE-01/274
// [review:need-review] PHASE-01/270
// [review:need-review] PHASE-01/208, PHASE-03/230, PHASE-03/250
// summary: tests for the root navigation — five tabs in mobile-web order, opening on Today, every former screen behind More; a More screen holding an unconfirmed write cannot be popped by the system (a second tap on the selected tab), every other pop and every push goes through; the block is a set of holders, so an old screen going away does not lift the hold of the new one
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
        navigation.holdMoreLeave(UUID())

        navigation.setMorePath([])

        XCTAssertEqual(navigation.morePath, [.dailySummary])
    }

    func testAHeldMoreScreenStillAllowsPushesAndTheScreensOwnLeave() {
        var navigation = AppNavigation()
        navigation.open(.more(.dashboard))
        let holder = UUID()
        navigation.holdMoreLeave(holder)

        navigation.setMorePath([.dashboard, .journal])
        XCTAssertEqual(navigation.morePath, [.dashboard, .journal])

        navigation.releaseMoreLeave(holder)
        navigation.setMorePath([])
        XCTAssertEqual(navigation.morePath, [])
    }

    func testARefusedPopChangesTheStateSoTheStackIsDrawnAgain() {
        var navigation = AppNavigation()
        navigation.open(.more(.dailySummary))
        navigation.holdMoreLeave(UUID())
        let before = navigation

        navigation.setMorePath([])

        XCTAssertNotEqual(navigation, before, "an unchanged value would not redraw the stack the system already popped")
    }

    func testAnOldScreenGoingAwayAfterTheNewOneAppearedKeepsTheNewOnesHold() {
        var navigation = AppNavigation()
        navigation.open(.more(.dailySummary))
        let old = UUID()
        let new = UUID()
        navigation.holdMoreLeave(old)

        // SwiftUI may show the new instance before the old one has gone.
        navigation.holdMoreLeave(new)
        navigation.releaseMoreLeave(old)

        XCTAssertTrue(navigation.moreLeaveBlocked)
        navigation.setMorePath([])
        XCTAssertEqual(navigation.morePath, [.dailySummary])

        navigation.releaseMoreLeave(new)
        XCTAssertFalse(navigation.moreLeaveBlocked)
    }

    func testReleasingAHoldThatWasNeverTakenChangesNothing() {
        var navigation = AppNavigation()
        let before = navigation

        navigation.releaseMoreLeave(UUID())

        XCTAssertEqual(navigation, before)
    }

    // MARK: Jumps by date (#270)

    func testADayJumpSelectsTheDayTabAndCarriesTheDate() {
        var navigation = AppNavigation()
        navigation.open(.day("2026-10-20"))
        XCTAssertEqual(navigation.selectedTab, .day)
        XCTAssertEqual(navigation.dayJump?.value, "2026-10-20")
        let first = navigation.dayJump
        navigation.open(.day("2026-10-20"))
        XCTAssertNotEqual(navigation.dayJump, first, "the same date twice must still fire")
    }

    func testABadDateOrWeekCodeIsIgnored() {
        var navigation = AppNavigation()
        let before = navigation
        navigation.open(.day("2026-02-30"))
        navigation.open(.week("2026-W99"))
        navigation.open(.week("week 44"))
        XCTAssertEqual(navigation, before)
    }

    func testWeek53OnlyInYearsThatHaveIt() {
        XCTAssertTrue(AppNavigation.isWeekCode("2026-W53"), "2026 has 53 ISO weeks")
        XCTAssertFalse(AppNavigation.isWeekCode("2025-W53"))
        XCTAssertTrue(AppNavigation.isWeekCode("2025-W52"))
        XCTAssertFalse(AppNavigation.isWeekCode("2026-W00"))
        XCTAssertFalse(AppNavigation.isWeekCode("2026-W5"))
        XCTAssertFalse(AppNavigation.isWeekCode("2026-W٠٥"))
    }

    func testAWeekJumpPushesTheWeekScreenOnMoreAndForgetsTheWeekWhenLeft() {
        var navigation = AppNavigation()
        navigation.open(.more(.life))
        navigation.open(.week("2026-W44"))
        XCTAssertEqual(navigation.selectedTab, .more)
        XCTAssertEqual(navigation.morePath, [.life, .week])
        XCTAssertEqual(navigation.weekStart, "2026-W44")
        navigation.setMorePath([.life])
        XCTAssertNil(navigation.weekStart)
        navigation.open(.week("2026-W44"))
        XCTAssertEqual(navigation.weekStart, "2026-W44")
        navigation.open(.more(.week))
        XCTAssertNil(navigation.weekStart, "opened from the list, the screen starts on the running week")
    }
}
