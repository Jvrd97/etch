// [review:need-review] PHASE-01/268
// summary: the sleep section of the metric detail screen as a List section — the last night (asleep, bedtime and wake time on the phone's own clock, minutes per stage) with the nights under it; an honest line when nothing arrived
import SwiftUI

/// `nights` is oldest first, as the server sends it.
struct HealthSleepSection: View {
    let nights: [HealthSleepNightDTO]
    let title: String

    var body: some View {
        Section(title) {
            if let last = nights.last {
                VStack(alignment: .leading, spacing: DS.Spacing.sm) {
                    Text(HealthMetricsFormat.sleepDuration(last.asleepMin))
                        .font(DS.Typography.section)
                    Text("Ночь на \(HealthMetricsFormat.dayLabel(last.date)): отбой \(HealthMetricsFormat.wallClock(last.bedtime)), подъём \(HealthMetricsFormat.wallClock(last.wakeTime))")
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                    ForEach(HealthMetricsFormat.sleepStages(last), id: \.label) { stage in
                        HStack {
                            Text(stage.label)
                            Spacer()
                            Text(HealthMetricsFormat.sleepDuration(stage.minutes)).monospacedDigit()
                        }
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                    }
                }
                .padding(.vertical, DS.Spacing.xs)
                ForEach(nights.reversed(), id: \.date) { night in
                    HStack {
                        Text(HealthMetricsFormat.dayLabel(night.date))
                            .foregroundStyle(DS.Palette.textSecondary)
                        Spacer()
                        Text(HealthMetricsFormat.sleepDuration(night.asleepMin)).monospacedDigit()
                    }
                }
            } else {
                Text(HealthMetricsFormat.sleepEmptyText)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textSecondary)
            }
        }
        .listRowBackground(DS.Palette.card)
    }
}
