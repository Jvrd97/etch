// [review:need-review] PHASE-03/162
// summary: the window grew taller (248 to 296) to make room for the day-mode switcher
// [review:need-review] PHASE-03/159
// summary: the floating window — a non-activating NSPanel that floats over full-screen apps and follows the person between Spaces, draggable by any part, remembers its frame to the pixel, and is hidden into and shown from the menu bar without losing the timer
import AppKit
import SwiftUI

/// Never takes focus: the app in front (Xcode) keeps its key window and its menu bar.
final class FloatingPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

/// A first click on a button must press it. In a window that is not key AppKit
/// otherwise spends the first click on focusing the window.
private final class FirstMouseHostingView<Content: View>: NSHostingView<Content> {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
}

@MainActor
final class FloatingPanelController {
    nonisolated static let frameAutosaveName = "HabitAgentFloatingPanel"
    static let visibleDefaultsKey = "panel-visible"
    static let contentSize = NSSize(width: 264, height: 296)
    private static let screenMargin: CGFloat = 16

    let panel: FloatingPanel
    private let defaults: UserDefaults
    /// Called after the panel is shown or hidden, so the menu can name the action it offers.
    var onVisibilityChange: (Bool) -> Void = { _ in }

    init(model: PanelModel, autosaveName: String = FloatingPanelController.frameAutosaveName, defaults: UserDefaults = .standard) {
        self.defaults = defaults
        panel = FloatingPanel(
            contentRect: NSRect(origin: .zero, size: Self.contentSize),
            // `.nonactivatingPanel` has to be in the initial mask: set later it does
            // not reach the window server, and the click would activate the app.
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.level = .floating
        // Floats over a full-screen app (`fullScreenAuxiliary`) and is on every Space (`canJoinAllSpaces`).
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isFloatingPanel = true
        panel.hidesOnDeactivate = false
        panel.becomesKeyOnlyIfNeeded = true
        panel.isMovableByWindowBackground = true
        panel.isReleasedWhenClosed = false
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.contentView = FirstMouseHostingView(rootView: PanelView(model: model, onMinimize: { [weak self] in self?.hide() }))
        restoreFrame(autosaveName: autosaveName)
    }

    var isVisible: Bool { panel.isVisible }

    /// What the person last chose; a first launch shows the window.
    var wasVisibleLastTime: Bool {
        defaults.object(forKey: Self.visibleDefaultsKey) as? Bool ?? true
    }

    func show() {
        // Not `makeKeyAndOrderFront`: that would take focus from the app in front.
        panel.orderFrontRegardless()
        remember(visible: true)
    }

    func hide() {
        panel.orderOut(nil)
        remember(visible: false)
    }

    func toggle() {
        isVisible ? hide() : show()
    }

    /// The frame saved under `autosaveName` wins; the size is always the current
    /// one, with the top-left corner kept, so a later version with a taller
    /// window grows downwards from where the person left the top.
    private func restoreFrame(autosaveName: String) {
        let restored = panel.setFrameUsingName(autosaveName)
        if restored {
            let top = panel.frame.maxY
            panel.setFrame(
                NSRect(x: panel.frame.minX, y: top - Self.contentSize.height, width: Self.contentSize.width, height: Self.contentSize.height),
                display: false
            )
        } else {
            placeInTopRightCorner()
        }
        // After the first placement, so the default position is saved too.
        panel.setFrameAutosaveName(autosaveName)
    }

    private func placeInTopRightCorner() {
        guard let area = NSScreen.main?.visibleFrame else { return }
        panel.setFrameOrigin(NSPoint(
            x: area.maxX - Self.contentSize.width - Self.screenMargin,
            y: area.maxY - Self.contentSize.height - Self.screenMargin
        ))
    }

    private func remember(visible: Bool) {
        defaults.set(visible, forKey: Self.visibleDefaultsKey)
        onVisibilityChange(visible)
    }
}
