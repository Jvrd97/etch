// [review:need-review] PHASE-01/268
// summary: the sleep and workout sections of the Health screens as List sections — the last night (asleep, bedtime and wake time on the phone's own clock, minutes per stage) with the nights under it, and the workouts newest first with only the numbers HealthKit held; an honest line when nothing arrived
import SwiftUI

/// `nights` is oldest first, as the server sends it.
struct HealthSleepSection: View {
    let nights: [HealthSleepNightDTO]
    let title: String
    /// The caller names where «Все ночи» leads; the detail screen itself passes none.
    var allNights: (() -> AnyView)?
    /// The detail screen lists the nights of the period; the tab keeps to the last one and the way to the rest.
    var listsNights = true

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
                ForEach(listsNights ? nights.reversed() : [], id: \.date) { night in
                    HStack {
                        Text(HealthMetricsFormat.dayLabel(night.date))
                            .foregroundStyle(DS.Palette.textSecondary)
                        Spacer()
                        Text(HealthMetricsFormat.sleepDuration(night.asleepMin)).monospacedDigit()
                    }
                }
                if let allNights {
                    NavigationLink("Все ночи", destination: allNights)
                        .foregroundStyle(DS.Palette.lime)
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

/// `workouts` is oldest first, as the server sends it; the section lists the newest first.
struct HealthWorkoutsSection: View {
    let workouts: [HealthWorkoutRecordDTO]

    var body: some View {
        Section("Тренировки") {
            if workouts.isEmpty {
                Text(HealthMetricsFormat.workoutsEmptyText)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textSecondary)
            } else {
                ForEach(workouts.reversed()) { workout in
                    let details = HealthMetricsFormat.workoutDetails(workout)
                    VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                        HStack {
                            Text(workout.activityLabel).font(DS.Typography.card)
                            Spacer()
                            Text(HealthMetricsFormat.sleepDuration(workout.durationMin)).monospacedDigit()
                        }
                        Text(([
                            "\(HealthMetricsFormat.dayLabel(workout.date)), \(HealthMetricsFormat.wallClock(workout.start))",
                        ] + details).joined(separator: " · "))
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.textSecondary)
                    }
                }
            }
        }
        .listRowBackground(DS.Palette.card)
    }
}
