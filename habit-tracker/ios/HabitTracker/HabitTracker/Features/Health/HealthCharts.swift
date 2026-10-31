// [review:need-review] PHASE-03/305
// summary: the drawing of the Health screen in SwiftUI shapes without a chart library — the server-index ring, the mini sparkline with an area (a day without data breaks the line), the seven-night sleep columns, and the bar around zero for a deviation; sizes scale with Dynamic Type, every chart is read aloud as words
import SwiftUI

/// Colours of the Health screen. The owner's mock-up fixed these three; the app's own lime in `DS.Palette` is a shade apart.
enum HealthPalette {
    static let lime = Color(hex6: 0xC6FF4A)
    static let sky = Color(hex6: 0x7FD6FF)
    static let amber = Color(hex6: 0xFFB454)
    static let track = Color(hex6: 0x2A2A2A)
    static let muted = Color(hex6: 0x6B6B6B)

    static func color(_ tone: HealthTone) -> Color {
        switch tone {
        case .better: return lime
        case .worse: return amber
        case .same: return DS.Palette.textSecondary
        }
    }
}

/// Sizes and strengths the charts share, named once.
private enum Drawing {
    static let sparklineInset: CGFloat = 3
    static let sparklineLine: CGFloat = 2
    static let sparklineLoneDot: CGFloat = 4
    static let sparklineLastDot: CGFloat = 6
    static let areaTopOpacity = 0.35
    /// A column never grows taller than this, however large the text is set.
    static let sleepChartMaxHeight: CGFloat = 180
    static let sleepBarRadius: CGFloat = 6
    static let sleepStageGap: CGFloat = 1
    static let sleepGapMarkHeight: CGFloat = 3
    static let deviationBarHeight: CGFloat = 10
    static let deviationAxisWidth: CGFloat = 2
    static let deviationAxisOverhang: CGFloat = 8
    static let deviationAxisOpacity = 0.7
}

/// The server's index as one ring from twelve o'clock. The lime-to-sky run along the arc is only decoration: it carries no second number.
struct HealthStateRing: View {
    /// 0...1; `nil` draws an empty track.
    let index: Double?
    let centerText: String

    @ScaledMetric(relativeTo: .title) private var side: CGFloat = 112
    private let ringWidth: CGFloat = 14

    var body: some View {
        ZStack {
            Circle().stroke(HealthPalette.track, lineWidth: ringWidth)
            if let index, index > 0 {
                let share = min(index, 1)
                Circle()
                    .trim(from: 0, to: share)
                    .stroke(
                        AngularGradient(
                            // Lime at both ends of the circle keeps the round caps of the arc one colour with their neighbours.
                            stops: [
                                .init(color: HealthPalette.lime, location: 0),
                                .init(color: HealthPalette.sky, location: share),
                                .init(color: HealthPalette.lime, location: 1),
                            ],
                            center: .center
                        ),
                        style: StrokeStyle(lineWidth: ringWidth, lineCap: .round)
                    )
                    .rotationEffect(.degrees(-90))
            }
            Text(centerText)
                .font(.system(.title, design: .rounded).weight(.bold))
                .monospacedDigit()
                .foregroundStyle(DS.Palette.textPrimary)
                .minimumScaleFactor(0.5)
        }
        .padding(ringWidth / 2)
        .frame(width: side, height: side)
        .accessibilityHidden(true)
    }
}

/// A line with an area under it. A `nil` point is a gap: the line and the area stop there and start again, a day without data is not a zero.
struct HealthMiniSparkline: View {
    let points: [Double?]
    let color: Color
    @ScaledMetric(relativeTo: .body) private var height: CGFloat = 36

    var body: some View {
        Canvas { context, size in
            let values = points.compactMap { $0 }
            guard let low = values.min(), let high = values.max(), points.count > 1 else { return }
            let span = high - low
            let step = size.width / CGFloat(points.count - 1)
            let inset = Drawing.sparklineInset
            func location(_ index: Int, _ value: Double) -> CGPoint {
                // A flat line sits in the middle rather than on the floor.
                let share = span == 0 ? 0.5 : (value - low) / span
                return CGPoint(x: CGFloat(index) * step, y: inset + (size.height - 2 * inset) * (1 - CGFloat(share)))
            }
            var run: [CGPoint] = []
            func flush() {
                defer { run.removeAll() }
                guard let first = run.first, let last = run.last else { return }
                if run.count == 1 {
                    let dot = Drawing.sparklineLoneDot
                    context.fill(Path(ellipseIn: CGRect(x: first.x - dot / 2, y: first.y - dot / 2, width: dot, height: dot)), with: .color(color))
                    return
                }
                var line = Path()
                line.addLines(run)
                var area = line
                area.addLine(to: CGPoint(x: last.x, y: size.height))
                area.addLine(to: CGPoint(x: first.x, y: size.height))
                area.closeSubpath()
                context.fill(area, with: .linearGradient(
                    Gradient(colors: [color.opacity(Drawing.areaTopOpacity), color.opacity(0)]),
                    startPoint: .zero, endPoint: CGPoint(x: 0, y: size.height)
                ))
                context.stroke(line, with: .color(color), style: StrokeStyle(lineWidth: Drawing.sparklineLine, lineCap: .round, lineJoin: .round))
            }
            for (index, point) in points.enumerated() {
                if let value = point { run.append(location(index, value)) } else { flush() }
            }
            flush()
            if let lastIndex = points.lastIndex(where: { $0 != nil }), let value = points[lastIndex] {
                let spot = location(lastIndex, value)
                let dot = Drawing.sparklineLastDot
                context.fill(Path(ellipseIn: CGRect(x: spot.x - dot / 2, y: spot.y - dot / 2, width: dot, height: dot)), with: .color(color))
            }
        }
        .frame(height: height)
        .accessibilityHidden(true)
    }
}

/// Seven columns, one per night: deep + REM in blue over light sleep in grey, the best night in lime alone.
struct HealthSleepColumns: View {
    let bars: [HealthOverview.SleepBar]
    @ScaledMetric(relativeTo: .body) private var scaledHeight: CGFloat = 120
    private var chartHeight: CGFloat { min(scaledHeight, Drawing.sleepChartMaxHeight) }
    /// The axis never drops under eight hours, so a short week does not look like a full one.
    private static let minimumAxisMinutes = 480.0
    private let radius = Drawing.sleepBarRadius

    var body: some View {
        let axis = max(Self.minimumAxisMinutes, bars.map(\.totalMin).max() ?? 0)
        HStack(alignment: .bottom, spacing: DS.Spacing.sm) {
            ForEach(bars) { bar in
                VStack(spacing: DS.Spacing.xs) {
                    column(bar, axis: axis)
                        .frame(height: chartHeight)
                    Text(bar.weekday)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(bar.isBest ? HealthPalette.lime : DS.Palette.textSecondary)
                }
                .frame(maxWidth: .infinity)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(Self.spoken(bar))
            }
        }
    }

    @ViewBuilder
    private func column(_ bar: HealthOverview.SleepBar, axis: Double) -> some View {
        if bar.hasData {
            VStack(spacing: 0) {
                Spacer(minLength: 0)
                if bar.isBest {
                    RoundedRectangle(cornerRadius: radius, style: .continuous)
                        .fill(HealthPalette.lime)
                        .frame(height: chartHeight * bar.totalMin / axis)
                } else {
                    VStack(spacing: Drawing.sleepStageGap) {
                        if bar.deepRemMin > 0 {
                            Rectangle().fill(HealthPalette.sky).frame(height: chartHeight * bar.deepRemMin / axis)
                        }
                        Rectangle().fill(HealthPalette.muted).frame(height: chartHeight * bar.lightMin / axis)
                    }
                    .clipShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
                }
            }
        } else {
            VStack {
                Spacer(minLength: 0)
                Capsule().fill(HealthPalette.track).frame(height: Drawing.sleepGapMarkHeight)
            }
        }
    }

    static func spoken(_ bar: HealthOverview.SleepBar) -> String {
        guard bar.hasData else { return "\(bar.weekday): нет данных" }
        let total = HealthMetricsFormat.sleepDuration(bar.totalMin)
        let deep = bar.deepRemMin > 0 ? ", глубокий и REM \(HealthMetricsFormat.sleepDuration(bar.deepRemMin))" : ""
        return "\(bar.weekday): \(total)\(deep)\(bar.isBest ? ", лучшая ночь" : "")"
    }
}

/// A bar that grows from the centre line to the side the value deviates to; the colour says whether that side is good.
struct HealthDeviationBar: View {
    let share: Double
    let tone: HealthTone
    private let barHeight = Drawing.deviationBarHeight

    var body: some View {
        GeometryReader { proxy in
            let half = proxy.size.width / 2
            let length = half * CGFloat(abs(share))
            ZStack(alignment: .leading) {
                Capsule().fill(HealthPalette.track)
                Capsule()
                    .fill(HealthPalette.color(tone))
                    .frame(width: max(length, tone == .same ? 0 : barHeight / 2))
                    .offset(x: share >= 0 ? half : half - length)
                Rectangle()
                    .fill(DS.Palette.textPrimary.opacity(Drawing.deviationAxisOpacity))
                    .frame(width: Drawing.deviationAxisWidth, height: barHeight + Drawing.deviationAxisOverhang)
                    .offset(x: half - Drawing.deviationAxisWidth / 2)
            }
            .frame(height: proxy.size.height)
        }
        .frame(height: barHeight)
        .accessibilityHidden(true)
    }
}
