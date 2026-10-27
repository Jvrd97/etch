// [review:need-review] PHASE-03/230
// summary: how a pushed More screen tells the root it holds a write nobody answered — an environment binding to AppNavigation.moreLeaveBlocked and a modifier that raises it while the screen is shown and held
import SwiftUI

private struct MoreLeaveBlockedKey: EnvironmentKey {
    static let defaultValue: Binding<Bool> = .constant(false)
}

extension EnvironmentValues {
    /// `AppNavigation.moreLeaveBlocked`, as set by the screen on top of the More stack.
    var moreLeaveBlocked: Binding<Bool> {
        get { self[MoreLeaveBlockedKey.self] }
        set { self[MoreLeaveBlockedKey.self] = newValue }
    }
}

private struct HoldsMoreScreen: ViewModifier {
    let held: Bool
    @Environment(\.moreLeaveBlocked) private var blocked

    func body(content: Content) -> some View {
        content
            .onAppear { blocked.wrappedValue = held }
            .onChange(of: held) { _, now in blocked.wrappedValue = now }
            .onDisappear { blocked.wrappedValue = false }
    }
}

extension View {
    /// While `held`, the system may not pop this screen off the More stack: it would drop a write
    /// whose answer never came.
    func holdsMoreScreen(_ held: Bool) -> some View {
        modifier(HoldsMoreScreen(held: held))
    }
}
