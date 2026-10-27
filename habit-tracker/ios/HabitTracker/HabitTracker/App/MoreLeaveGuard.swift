// [review:need-review] PHASE-03/230, PHASE-03/250
// summary: how a pushed More screen tells the root it holds a write nobody answered — an environment value that holds and releases by the screen instance's own token (AppNavigation.moreLeaveHolders) and a modifier that holds while the screen is shown and held; the token keeps an old instance's disappearance from lifting the hold of a new one
import SwiftUI

/// The root's side of the guard: hold or release the More stack's pop for one screen instance.
struct MoreLeaveHold {
    let hold: (UUID) -> Void
    let release: (UUID) -> Void

    static let none = MoreLeaveHold(hold: { _ in }, release: { _ in })
}

private struct MoreLeaveHoldKey: EnvironmentKey {
    static let defaultValue = MoreLeaveHold.none
}

extension EnvironmentValues {
    /// `AppNavigation`'s holders, as set by the More stack for the screens pushed on it.
    var moreLeaveHold: MoreLeaveHold {
        get { self[MoreLeaveHoldKey.self] }
        set { self[MoreLeaveHoldKey.self] = newValue }
    }
}

private struct HoldsMoreScreen: ViewModifier {
    let held: Bool
    let token: UUID
    @Environment(\.moreLeaveHold) private var leave

    func body(content: Content) -> some View {
        content
            .onAppear { apply(held) }
            .onChange(of: held) { _, now in apply(now) }
            .onDisappear { leave.release(token) }
    }

    private func apply(_ held: Bool) {
        if held { leave.hold(token) } else { leave.release(token) }
    }
}

extension View {
    /// While `held`, the system may not pop this screen off the More stack: it would drop a write
    /// whose answer never came. `token` names this screen instance; the screen keeps it for its life
    /// so that it can also release the hold itself when the person chooses to leave.
    func holdsMoreScreen(_ held: Bool, token: UUID) -> some View {
        modifier(HoldsMoreScreen(held: held, token: token))
    }
}
