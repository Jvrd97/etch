// [review:need-review] PHASE-03/294
// summary: the sheet behind «Когда?» on an avoid card — pick the day the relapse happened on (today, yesterday, the day before, or any day of the month grid) and record it there; the streak and the last relapse are recomputed by the server
import SwiftUI

struct RelapseWhenSheet: View {
    let category: CategoryDTO
    @ObservedObject var viewModel: TodayViewModel

    @Environment(\.dismiss) private var dismiss
    @State private var day: String
    @State private var isSaving = false

    init(category: CategoryDTO, viewModel: TodayViewModel) {
        self.category = category
        self.viewModel = viewModel
        _day = State(initialValue: viewModel.todayString)
    }

    private var quickDays: [(title: String, day: String)] {
        let today = viewModel.todayString
        return [
            ("Сегодня", today),
            ("Вчера", DayCalendar.day(today, plusDays: -1)),
            ("Позавчера", DayCalendar.day(today, plusDays: -2)),
        ]
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: DS.Spacing.lg) {
                    HStack(spacing: DS.Spacing.sm) {
                        ForEach(quickDays, id: \.day) { quick in
                            Button { day = quick.day } label: {
                                Text(quick.title)
                                    .font(DS.Typography.caption)
                                    .foregroundStyle(day == quick.day ? Color.black : DS.Palette.textPrimary)
                                    .padding(.vertical, DS.Spacing.sm)
                                    .padding(.horizontal, DS.Spacing.md)
                                    .frame(minHeight: 44)
                                    .background(Capsule().fill(day == quick.day ? DS.Palette.lime : DS.Palette.card))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    DayCalendarPicker(selection: $day, maxDay: viewModel.todayString)
                    Text("Срыв: \(RelapseAnalysis.formatDay(day)), \(RelapseAnalysis.formatWeekday(day)). Серия пересчитается по этому дню.")
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                    if let message = viewModel.saveErrorMessage {
                        Text(message)
                            .font(DS.Typography.caption)
                            .foregroundStyle(DS.Palette.danger)
                            .accessibilityIdentifier("relapse.when.error")
                    }
                }
                .padding(DS.Spacing.lg)
            }
            .dsScreenBackground()
            .navigationTitle("\(category.name): когда")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Отмена") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Записать") { Task { await save() } }
                        .disabled(isSaving)
                        .accessibilityIdentifier("relapse.when.save")
                }
            }
            .onAppear { viewModel.saveErrorMessage = nil }
        }
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
    }

    private func save() async {
        isSaving = true
        defer { isSaving = false }
        if await viewModel.recordRelapse(categoryID: category.id, on: day) {
            dismiss()
        }
    }
}
