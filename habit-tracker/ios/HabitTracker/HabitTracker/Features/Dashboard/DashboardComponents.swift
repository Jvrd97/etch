// [review:need-review] PHASE-03/304
// summary: the small shared pieces of the dashboard — the mock-up's three colours as a local palette (DesignSystem is not touched), the card header with its aside, the honest one-line empty state, the ring (an empty one is a dashed track, not a zero), and the row of strip dots; every drawing is hidden from VoiceOver and its words are spoken by the card that owns it
import SwiftUI

/// The owner's mock-up fixed these colours; the app's own lime in `DS.Palette` is a shade apart.
enum DashboardPalette {
    static let lime = Color(hex6: 0xC6FF4A)
    static let sky = Color(hex6: 0x7FD6FF)
    static let amber = Color(hex6: 0xFFB454)
    static let track = Color(hex6: 0x2A2A2A)
    static let dotUnknown = Color.white.opacity(0.12)
    /// Fill of a small badge («без срывов») and of the nutrition tile.
    static let badgeFill = Color.white.opacity(0.08)
    static let tileFill = Color.white.opacity(0.06)
    static let recordFill = lime.opacity(0.12)

    static func color(_ tone: DashboardTone) -> Color {
        switch tone {
        case .better: return lime
        case .worse: return amber
        case .same: return DS.Palette.textSecondary
        }
    }

    static func color(_ kind: DashboardRing.Kind) -> Color {
        switch kind {
        case .health: return lime
        case .habits: return sky
        case .challenges: return amber
        }
    }
}

/// Sizes the cards share, named once.
enum DashboardMetrics {
    /// Smallest comfortable target for a tap.
    static let minTap: CGFloat = 44
    /// Gap between a value and its caption.
    static let tightGap: CGFloat = 2
    /// Gap between an icon and its text.
    static let iconGap: CGFloat = 4
    static let badgeVerticalPadding: CGFloat = 2
    /// How far a number or a date may shrink before it wraps.
    static let minScale: CGFloat = 0.7
    static let ringMinScale: CGFloat = 0.5
    static let barRadius: CGFloat = 8
}

/// Title of a card with a quieter line beside or, at large text sizes, under it.
struct DashboardCardHeader: View {
    let title: String
    var aside: String?

    var body: some View {
        if let aside {
            // Side by side while both fit on one line each; otherwise the aside goes under the title.
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline, spacing: DS.Spacing.sm) {
                    titleText.fixedSize(horizontal: true, vertical: false)
                    Spacer(minLength: DS.Spacing.sm)
                    asideText(aside, alignment: .trailing).fixedSize(horizontal: true, vertical: false)
                }
                VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                    titleText
                    asideText(aside, alignment: .leading)
                }
            }
        } else {
            titleText
        }
    }

    private var titleText: some View {
        Text(title)
            .font(.headline)
            .foregroundStyle(DS.Palette.textPrimary)
            .accessibilityAddTraits(.isHeader)
    }

    private func asideText(_ text: String, alignment: TextAlignment) -> some View {
        Text(text)
            .font(.footnote)
            .foregroundStyle(DS.Palette.textSecondary)
            .multilineTextAlignment(alignment)
    }
}

/// The line a block shows when the server sent nothing for it: a statement, never a zero or a blank.
struct DashboardEmptyLine: View {
    let text: String

    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text)
            .font(.subheadline)
            .foregroundStyle(DS.Palette.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}

/// A ring from twelve o'clock. `fraction == nil` draws a dashed empty track.
struct DashboardRingShape: View {
    let fraction: Double?
    let centre: String
    let color: Color

    /// Grows with the text but never past the cap, so three rings keep a row.
    @ScaledMetric(relativeTo: .title) private var side: CGFloat = 84
    private let maxSide: CGFloat = 132
    private let lineWidth: CGFloat = 9
    private let emptyDash: [CGFloat] = [3, 6]

    var body: some View {
        let size = min(side, maxSide)
        ZStack {
            Circle()
                .stroke(
                    DashboardPalette.track,
                    style: StrokeStyle(lineWidth: lineWidth, dash: fraction == nil ? emptyDash : [])
                )
            if let fraction, fraction > 0 {
                Circle()
                    .trim(from: 0, to: fraction)
                    .stroke(color, style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                    .rotationEffect(.degrees(-90))
            }
            Text(centre)
                .font(.system(.title3, design: .rounded).weight(.bold))
                .monospacedDigit()
                .foregroundStyle(DS.Palette.textPrimary)
                .minimumScaleFactor(DashboardMetrics.ringMinScale)
                .lineLimit(1)
                .padding(lineWidth)
        }
        .padding(lineWidth / 2)
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

/// The strip of the window's days, oldest first. Done is a filled dot, a miss is a ring, no data is a faint dot:
/// the shapes differ, so the strip does not lean on colour alone.
struct DashboardDayDots: View {
    let days: [Bool?]

    @ScaledMetric(relativeTo: .caption) private var dot: CGFloat = 12
    private let ringWidth: CGFloat = 2

    var body: some View {
        LazyVGrid(
            columns: [GridItem(.adaptive(minimum: dot + DS.Spacing.xs), spacing: DS.Spacing.xs)],
            alignment: .leading, spacing: DS.Spacing.xs
        ) {
            ForEach(Array(days.enumerated()), id: \.offset) { _, day in
                switch day {
                case .some(true):
                    Circle().fill(DashboardPalette.lime).frame(width: dot, height: dot)
                case .some(false):
                    Circle().strokeBorder(DashboardPalette.amber, lineWidth: ringWidth).frame(width: dot, height: dot)
                case .none:
                    Circle().fill(DashboardPalette.dotUnknown).frame(width: dot, height: dot)
                }
            }
        }
        .accessibilityHidden(true)
    }
}
