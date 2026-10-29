// [review:need-review] PHASE-01/265
// summary: the day square in five states that differ by shape, not shade (won filled lime, lost filled grey, open an empty lime outline, empty a faint fill, future a dashed outline), the ring for today, and the legend
import SwiftUI

extension LifeStatus {
    var fill: Color {
        switch self {
        case .won: return DS.Palette.lime
        case .lost: return DS.Palette.textDisabled
        case .open: return .clear
        case .empty: return Color.white.opacity(0.05)
        case .future: return .clear
        }
    }

    var stroke: Color {
        switch self {
        case .won: return DS.Palette.lime
        case .lost: return DS.Palette.textDisabled
        case .open: return DS.Palette.lime
        case .empty: return Color.white.opacity(0.05)
        case .future: return Color.white.opacity(0.25)
        }
    }

    var dash: [CGFloat] { self == .future ? [3, 2] : [] }
}

struct LifeSquare: View {
    let status: LifeStatus
    var size: CGFloat = 28
    var isToday = false

    var body: some View {
        RoundedRectangle(cornerRadius: size / 5)
            .fill(status.fill)
            .overlay(
                RoundedRectangle(cornerRadius: size / 5)
                    .strokeBorder(status.stroke, style: StrokeStyle(lineWidth: 1.5, dash: status.dash))
            )
            .overlay(
                RoundedRectangle(cornerRadius: size / 5)
                    .inset(by: -3)
                    .stroke(Color.white.opacity(isToday ? 0.7 : 0), lineWidth: 1.5)
            )
            .frame(width: size, height: size)
    }
}

struct LifeLegend: View {
    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), alignment: .leading)], alignment: .leading, spacing: DS.Spacing.sm) {
            ForEach(LifeStatus.allCases, id: \.self) { status in
                HStack(spacing: DS.Spacing.sm) {
                    LifeSquare(status: status, size: 12)
                    Text(status.label)
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                }
            }
        }
    }
}
