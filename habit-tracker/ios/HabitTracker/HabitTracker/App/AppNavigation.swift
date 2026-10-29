// [review:need-review] PHASE-01/265 — the «Жизнь» row under More (one case, one title, one icon)
// [review:need-review] PHASE-01/267 — the «Онбординг» row under More (one case, one title, one icon)
// [review:need-review] PHASE-01/208, PHASE-03/229, PHASE-03/230, PHASE-03/250
// [review:need-review] PHASE-03/240 — the «Добавки» row under More (one case, one title, one icon, one screen line)
// [review:need-review] PHASE-01/216 — the «Цели» row under More (one case, one title, one icon)
// summary: root navigation model — five tabs in mobile-web order, the screens behind More, and the routing of in-app jumps (+ the Неделя row under More, #229); More screens that hold an unconfirmed write block the system's pop to the root (a second tap on the selected tab), #230; the block is a set of holders, one token per screen instance, so an old screen going away cannot lift the block of the new one (#250)
import Foundation

/// Tabs of the root bar, in the order the mobile web shows them.
enum AppTab: String, CaseIterable, Identifiable {
    case today
    case day
    case chat
    case health
    case more

    var id: String { rawValue }

    var title: String {
        switch self {
        case .today: return "Today"
        case .day: return "Day"
        case .chat: return "Chat"
        case .health: return "Health"
        case .more: return "More"
        }
    }

    var systemImage: String {
        switch self {
        case .today: return "sun.max"
        case .day: return "calendar.badge.checkmark"
        case .chat: return "bubble.left.and.bubble.right"
        case .health: return "heart.text.square"
        case .more: return "ellipsis.circle"
        }
    }
}

/// Screens listed under the More tab, in list order.
enum MoreDestination: String, CaseIterable, Identifiable, Hashable {
    case dashboard
    case quickMarks
    case dailySummary
    case week
    case supplements
    case goals
    case categories
    case table
    case entries
    case journal
    case insights
    case life
    case onboarding
    case settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .dashboard: return "Dashboard"
        case .quickMarks: return "Быстрые отметки"
        case .dailySummary: return "Day summary"
        case .week: return "Неделя"
        case .supplements: return "Добавки"
        case .goals: return "Цели"
        case .categories: return "Categories"
        case .table: return "Table"
        case .entries: return "History"
        case .journal: return "Journal"
        case .insights: return "Insights"
        case .life: return "Жизнь"
        case .onboarding: return "Онбординг"
        case .settings: return "Settings"
        }
    }

    var systemImage: String {
        switch self {
        case .dashboard: return "square.grid.2x2"
        case .quickMarks: return "bolt"
        case .dailySummary: return "square.and.pencil"
        case .week: return "calendar"
        case .supplements: return "pills"
        case .goals: return "flag.checkered"
        case .categories: return "folder"
        case .table: return "tablecells"
        case .entries: return "clock.arrow.circlepath"
        case .journal: return "book"
        case .insights: return "sparkles"
        case .life: return "square.grid.3x3"
        case .onboarding: return "wand.and.stars"
        case .settings: return "gear"
        }
    }
}

/// Where an in-app jump lands: a tab of the bar, or a screen behind More.
enum AppDestination: Hashable {
    case tab(AppTab)
    case more(MoreDestination)
}

/// Root navigation state: the selected tab and the More stack. A value type, so the
/// routing rules are testable without a view.
struct AppNavigation: Equatable {
    var selectedTab: AppTab = .today
    private(set) var morePath: [MoreDestination] = []
    /// Pushed More screens that ask not to be left: each holds a write whose answer never came, and
    /// leaving drops the key that keeps a retry from writing the day twice. The screen has its own
    /// Back that asks first; this stops the way around it. One token per screen instance: the old
    /// instance going away after the new one appeared lifts only its own hold.
    private(set) var moreLeaveHolders: Set<UUID> = []
    var moreLeaveBlocked: Bool { !moreLeaveHolders.isEmpty }
    /// Counts the pops refused. The system has already popped its stack when it reports the new
    /// path, so a refusal must change this value for the stack to be drawn from the path again.
    private(set) var refusedPops = 0

    /// A More screen is pushed on top of what More already shows, so Back from a
    /// Journal opened off the Dashboard returns to the Dashboard.
    mutating func open(_ destination: AppDestination) {
        switch destination {
        case .tab(let tab):
            selectedTab = tab
        case .more(let screen):
            selectedTab = .more
            morePath.append(screen)
        }
    }

    mutating func holdMoreLeave(_ token: UUID) {
        moreLeaveHolders.insert(token)
    }

    mutating func releaseMoreLeave(_ token: UUID) {
        moreLeaveHolders.remove(token)
    }

    /// The path as the system reports it. A second tap on the selected More tab pops the stack to
    /// its root without asking the screen on top; that, and any other pop, is refused while
    /// `moreLeaveBlocked`. Pushes pass.
    mutating func setMorePath(_ path: [MoreDestination]) {
        if moreLeaveBlocked, path.count < morePath.count {
            refusedPops += 1
            return
        }
        morePath = path
    }
}
