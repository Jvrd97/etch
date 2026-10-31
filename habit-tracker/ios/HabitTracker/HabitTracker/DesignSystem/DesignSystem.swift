// [review:need-review] PHASE-01/32-ios-lime-tech-design-pass
// summary: Lime Tech design tokens (palette, radii, spacing, typography) + shared building blocks used across all screens
import SwiftUI

/// Central namespace for the "Lime Tech" design system.
///
/// Everything visual (colors, corner radii, spacing scale, type ramp) is a token
/// here so screens never hard-code a hex string or a magic number. The look is a
/// dark, high-contrast "instrument" aesthetic with a single lime accent.
enum DS {
    /// Color tokens from `docs/PHASE-01/design/design-system.md`.
    enum Palette {
        static let background = Color(hex6: 0x090909)
        static let surface = Color(hex6: 0x141414)
        static let card = Color(hex6: 0x1A1A1A)
        static let cardStroke = Color(hex6: 0x2A2A2A)
        static let lime = Color(hex6: 0xB8FF36)
        static let green = Color(hex6: 0x69E76A)
        static let textPrimary = Color(hex6: 0xFFFFFF)
        static let textSecondary = Color(hex6: 0xA3A3A3)
        static let textDisabled = Color(hex6: 0x666666)
        static let success = Color(hex6: 0x4ADE80)
        static let warning = Color(hex6: 0xFACC15)
        static let danger = Color(hex6: 0xEF4444)
        static let info = Color(hex6: 0x60A5FA)
    }

    /// Corner radii. The reference uses generous rounding (20–28 px) on cards and sheets.
    enum Radius {
        static let chip: CGFloat = 12
        static let control: CGFloat = 16
        static let card: CGFloat = 22
        static let sheet: CGFloat = 28
    }

    /// 4-pt spacing scale.
    enum Spacing {
        static let xs: CGFloat = 4
        static let sm: CGFloat = 8
        static let md: CGFloat = 12
        static let lg: CGFloat = 16
        static let xl: CGFloat = 24
        static let xxl: CGFloat = 32
    }

    /// SF Pro type ramp from the design system.
    enum Typography {
        static let h1 = Font.system(size: 36, weight: .bold)
        static let section = Font.system(size: 22, weight: .semibold)
        static let card = Font.system(size: 18, weight: .medium)
        static let body = Font.system(size: 16, weight: .regular)
        static let caption = Font.system(size: 13, weight: .medium)
        /// Oversized number used on quick-entry / detail hero values.
        static let hero = Font.system(size: 56, weight: .bold, design: .rounded)
    }

    /// Standard timings for the "alive but calm" motion language.
    enum Motion {
        static let cardLift = Animation.spring(response: 0.3, dampingFraction: 0.7)
        static let sheet = Animation.spring(response: 0.45, dampingFraction: 0.8)
    }
}

extension Color {
    /// Builds a color from a 24-bit `0xRRGGBB` literal (opaque).
    ///
    /// Distinct from the string `init?(hex:)` used by category swatches — this one is
    /// for compile-time design tokens where the value is known and always valid.
    init(hex6 value: UInt32) {
        self.init(
            .sRGB,
            red: Double((value >> 16) & 0xFF) / 255,
            green: Double((value >> 8) & 0xFF) / 255,
            blue: Double(value & 0xFF) / 255,
            opacity: 1
        )
    }
}

// MARK: - Screen background

private struct ScreenBackground: ViewModifier {
    func body(content: Content) -> some View {
        content
            .scrollContentBackground(.hidden)
            .background(DS.Palette.background.ignoresSafeArea())
    }
}

extension View {
    /// Paints the near-black app background behind a screen and hides the default
    /// system list/form chrome so cards read against true black.
    func dsScreenBackground() -> some View {
        modifier(ScreenBackground())
    }
}

// MARK: - Card

/// Matte elevated surface used for every content block in the app.
/// It carries no gesture of its own: a zero-distance drag on a card swallowed the
/// vertical pan of the enclosing ScrollView, so a swipe starting on a card did not scroll.
struct Card<Content: View>: View {
    private let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .padding(DS.Spacing.lg)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(DS.Palette.card)
            .clipShape(RoundedRectangle(cornerRadius: DS.Radius.card, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: DS.Radius.card, style: .continuous)
                    .stroke(DS.Palette.cardStroke, lineWidth: 1)
            )
    }
}

// MARK: - Lime button

/// Primary call-to-action: filled lime pill with black text and a press-scale.
struct LimeButtonStyle: ButtonStyle {
    var prominent: Bool = true

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(DS.Typography.card)
            .foregroundStyle(prominent ? Color.black : DS.Palette.lime)
            .frame(maxWidth: .infinity)
            .padding(.vertical, DS.Spacing.md)
            .background(
                RoundedRectangle(cornerRadius: DS.Radius.control, style: .continuous)
                    .fill(prominent ? DS.Palette.lime : DS.Palette.card)
            )
            .overlay(
                RoundedRectangle(cornerRadius: DS.Radius.control, style: .continuous)
                    .stroke(prominent ? .clear : DS.Palette.lime.opacity(0.5), lineWidth: 1)
            )
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .animation(DS.Motion.cardLift, value: configuration.isPressed)
    }
}

// MARK: - Neon loader

/// Thin rotating lime ring used instead of the system spinner.
struct NeonLoader: View {
    var label: String?
    @State private var spin = false

    var body: some View {
        VStack(spacing: DS.Spacing.lg) {
            Circle()
                .trim(from: 0, to: 0.28)
                .stroke(
                    DS.Palette.lime,
                    style: StrokeStyle(lineWidth: 4, lineCap: .round)
                )
                .frame(width: 44, height: 44)
                .rotationEffect(.degrees(spin ? 360 : 0))
                .shadow(color: DS.Palette.lime.opacity(0.6), radius: 6)
                .animation(.linear(duration: 0.9).repeatForever(autoreverses: false), value: spin)
            if let label {
                Text(label)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear { spin = true }
    }
}

// MARK: - Shared state screens

/// Error state with a lime Retry button, matching the reference "Connection Error" screen.
struct DSErrorState: View {
    let message: String
    let retry: () -> Void

    var body: some View {
        VStack(spacing: DS.Spacing.lg) {
            Image(systemName: "wifi.exclamationmark")
                .font(.system(size: 44, weight: .regular))
                .foregroundStyle(DS.Palette.textSecondary)
            Text(message)
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.textSecondary)
                .multilineTextAlignment(.center)
            Button("Retry", action: retry)
                .buttonStyle(LimeButtonStyle())
                .fixedSize()
        }
        .padding(DS.Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// Empty state: icon, message, and a single lime action, matching the reference.
struct DSEmptyState: View {
    let title: String
    let systemImage: String
    let message: String
    var action: (label: String, run: () -> Void)?

    var body: some View {
        VStack(spacing: DS.Spacing.md) {
            Image(systemName: systemImage)
                .font(.system(size: 40, weight: .regular))
                .foregroundStyle(DS.Palette.lime)
            Text(title)
                .font(DS.Typography.section)
                .foregroundStyle(DS.Palette.textPrimary)
            Text(message)
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.textSecondary)
                .multilineTextAlignment(.center)
            if let action {
                Button(action.label, action: action.run)
                    .buttonStyle(LimeButtonStyle())
                    .fixedSize()
                    .padding(.top, DS.Spacing.sm)
            }
        }
        .padding(DS.Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
