// [review:need-review] PHASE-01/268
// summary: small views of the Health screens — the 30-day sparkline (a missing day breaks the line, never a zero), the «последний синк / отставание» block, the offline note, and a section card with a title
import SwiftUI

/// A line over the days; a `nil` point is a gap, so a day without data is not read as zero.
struct HealthSparkline: View {
    let points: [Double?]
    static let size = CGSize(width: 64, height: 24)

    var body: some View {
        Canvas { context, size in
            let values = points.compactMap { $0 }
            guard let low = values.min(), let high = values.max(), points.count > 1 else { return }
            let span = high - low
            let step = size.width / CGFloat(points.count - 1)
            func location(_ index: Int, _ value: Double) -> CGPoint {
                // A flat line sits in the middle rather than on the floor.
                let share = span == 0 ? 0.5 : (value - low) / span
                return CGPoint(x: CGFloat(index) * step, y: size.height - CGFloat(share) * size.height)
            }
            var line = Path()
            var open = false
            for (index, point) in points.enumerated() {
                guard let value = point else { open = false; continue }
                let spot = location(index, value)
                if open { line.addLine(to: spot) } else { line.move(to: spot) }
                open = true
                let neighbours = [index - 1, index + 1].filter { points.indices.contains($0) && points[$0] != nil }
                if neighbours.isEmpty {
                    line.addEllipse(in: CGRect(x: spot.x - 1.5, y: spot.y - 1.5, width: 3, height: 3))
                }
            }
            context.stroke(line, with: .color(DS.Palette.textSecondary), style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round))
        }
        .frame(width: Self.size.width, height: Self.size.height)
        .accessibilityHidden(true)
    }
}

/// The first thing on the screen: a lag of a day or more must be seen without scrolling.
struct HealthSyncBlock: View {
    let verdict: HealthMetricsFormat.SyncVerdict

    var body: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.xs) {
            Text(verdict.text)
                .font(DS.Typography.card)
            if let detail = verdict.detail {
                Text(detail)
                    .font(DS.Typography.caption)
            }
        }
        .foregroundStyle(verdict.warn ? DS.Palette.warning : DS.Palette.textSecondary)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

struct HealthOfflineNote: View {
    let updatedAt: Date

    var body: some View {
        Label(HealthMetricsFormat.offlineCaption(updatedAt), systemImage: "wifi.slash")
            .font(DS.Typography.caption)
            .foregroundStyle(DS.Palette.textSecondary)
    }
}
