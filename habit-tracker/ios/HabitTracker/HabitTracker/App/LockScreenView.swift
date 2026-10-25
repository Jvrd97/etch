// [review:need-review] PHASE-01/214
// summary: lock screen and the .appLock() modifier — locked app shows only the lock screen, any non-active scene is covered in the app switcher
import SwiftUI

/// Wraps the app so that, while the lock is closed, the content is not in the view
/// tree at all. Re-asks Face ID whenever the scene becomes active and the lock is closed.
private struct AppLockModifier: ViewModifier {
    @StateObject private var controller = AppLockController()
    @Environment(\.scenePhase) private var scenePhase

    func body(content: Content) -> some View {
        ZStack {
            if controller.isLocked {
                LockScreenView(controller: controller)
            } else {
                content
            }
            if scenePhase != .active && !controller.isLocked && LockSettings().isEnabled {
                PrivacyCover()
            }
        }
        .onChange(of: scenePhase, initial: true) { _, phase in
            switch phase {
            case .active:
                controller.sceneDidBecomeActive()
                if controller.isLocked {
                    Task { await controller.unlock() }
                }
            case .background:
                controller.sceneDidEnterBackground()
            default:
                break
            }
        }
    }
}

extension View {
    /// Puts the Face ID lock in front of this view. Inert while the lock is off in Settings.
    func appLock() -> some View {
        modifier(AppLockModifier())
    }
}

struct LockScreenView: View {
    @ObservedObject var controller: AppLockController

    var body: some View {
        VStack(spacing: DS.Spacing.xl) {
            Image(systemName: "faceid")
                .font(.system(size: 64))
                .foregroundStyle(DS.Palette.lime)
            Text("Habit Tracker заблокирован")
                .font(DS.Typography.section)
                .foregroundStyle(DS.Palette.textPrimary)
            if let message = controller.message {
                Text(message)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textSecondary)
                    .multilineTextAlignment(.center)
            }
            Button {
                Task { await controller.unlock() }
            } label: {
                Text("Открыть")
                    .font(DS.Typography.card)
                    .foregroundStyle(DS.Palette.background)
                    .padding(.horizontal, DS.Spacing.xxl)
                    .padding(.vertical, DS.Spacing.md)
                    .background(DS.Palette.lime, in: Capsule())
            }
            .disabled(controller.isAuthenticating)
        }
        .padding(DS.Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(DS.Palette.background.ignoresSafeArea())
    }
}

/// Opaque cover for the app-switcher snapshot while the app is inactive or in the background.
private struct PrivacyCover: View {
    var body: some View {
        DS.Palette.background
            .ignoresSafeArea()
            .overlay {
                Image(systemName: "lock.fill")
                    .font(.system(size: 40))
                    .foregroundStyle(DS.Palette.textDisabled)
            }
    }
}
