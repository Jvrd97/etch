// [review:need-review] PHASE-01/214
// summary: lock screen and the .appLock() modifier — locked app shows only the lock screen; a non-active scene is covered in the app switcher by a separate window above sheets and alerts
import SwiftUI

/// Wraps the app so that, while the lock is closed, the content is not in the view
/// tree at all. Asks Face ID once on launch and once per return from the background.
private struct AppLockModifier: ViewModifier {
    @StateObject private var controller = AppLockController()
    @State private var cover = PrivacyCoverWindow()
    @Environment(\.scenePhase) private var scenePhase

    private var needsCover: Bool {
        scenePhase != .active && !controller.isLocked && LockSettings().isEnabled
    }

    func body(content: Content) -> some View {
        ZStack {
            if controller.isLocked {
                LockScreenView(controller: controller)
            } else {
                content
            }
        }
        .onChange(of: needsCover, initial: true) { _, visible in
            cover.setVisible(visible)
        }
        .onChange(of: scenePhase, initial: true) { _, phase in
            switch phase {
            case .active:
                controller.sceneDidBecomeActive()
                if controller.takeActivationPrompt() {
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
struct PrivacyCover: View {
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

/// Shows `PrivacyCover` in its own window. A view in the root `ZStack` would sit under
/// every `.sheet`, so the snapshot would still show the sheet; a window above `.alert`
/// covers sheets, alerts and the keyboard. Dismissing sheets instead would lose input
/// whenever the scene is merely inactive (Control Center, a system alert).
@MainActor
final class PrivacyCoverWindow {
    /// Above `.alert`, which is where UIKit puts alert controllers.
    static let level = UIWindow.Level.alert + 1

    private var window: UIWindow?
    private let sceneProvider: @MainActor () -> UIWindowScene?

    init(sceneProvider: @escaping @MainActor () -> UIWindowScene? = PrivacyCoverWindow.firstWindowScene) {
        self.sceneProvider = sceneProvider
    }

    var isVisible: Bool {
        window.map { !$0.isHidden } ?? false
    }

    var windowLevel: UIWindow.Level? {
        window?.windowLevel
    }

    func setVisible(_ visible: Bool) {
        if visible {
            show()
        } else {
            window?.isHidden = true
        }
    }

    private func show() {
        if window == nil, let scene = sceneProvider() {
            let cover = UIWindow(windowScene: scene)
            cover.windowLevel = Self.level
            cover.rootViewController = UIHostingController(rootView: PrivacyCover())
            window = cover
        }
        window?.isHidden = false
    }

    static func firstWindowScene() -> UIWindowScene? {
        UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
    }
}
