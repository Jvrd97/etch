// [review:need-review] PHASE-01/210
// summary: the day of one category behind a Today card, with its earlier days under it as a history — the quick-mark sets of the day (when a button answers for the category) above the day's records, a record deleted by swipe, a new record through the quick-entry sheet, and the buttons' totals re-read after anything that changed them
// [review:need-review] PHASE-03/316
// summary: PHASE-03/316 — a record's «ждёт» tag shows only when its save waits, not while it is merely on its way
import SwiftUI

struct TodayDaySheet: View {
    let target: DaySheetTarget
    @ObservedObject var viewModel: TodayViewModel
    @ObservedObject var quickMarks: QuickMarksViewModel

    @Environment(\.dismiss) private var dismiss
    @State private var adding = false
    /// Earlier days of the category; nil until the read answers or when it fails.
    @State private var history: [HistoryDay]?
    @State private var historyLoaded = false

    private var entries: [EntryDTO] {
        viewModel.entries(forCategory: target.categoryID)
    }

    var body: some View {
        NavigationStack {
            List {
                if let mark = target.mark {
                    QuickMarkDaySetsSection(mark: mark, quickMarks: quickMarks)
                }
                Section {
                    if entries.isEmpty {
                        Text("Записей за сегодня нет.")
                            .foregroundStyle(DS.Palette.textSecondary)
                            .listRowBackground(DS.Palette.card)
                    }
                    ForEach(entries) { entry in
                        entryRow(entry)
                            .listRowBackground(DS.Palette.card)
                    }
                    .onDelete(perform: delete)
                } header: {
                    Text(target.mark == nil ? "Записи за сегодня" : "Записи за день")
                }
                historySections
                if let message = viewModel.saveErrorMessage {
                    Section {
                        Text(message).foregroundStyle(DS.Palette.danger)
                    }
                    .listRowBackground(DS.Palette.card)
                }
            }
            .scrollContentBackground(.hidden)
            .dsScreenBackground()
            .navigationTitle(target.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Готово") { dismiss() }
                }
                if target.category != nil {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Добавить") { adding = true }
                    }
                }
            }
            .sheet(isPresented: $adding, onDismiss: {
                // A record added by hand moves the day's total the buttons show.
                Task { await quickMarks.load() }
            }) {
                if let category = target.category {
                    QuickEntrySheet(category: category, viewModel: viewModel)
                }
            }
            .onAppear { viewModel.saveErrorMessage = nil }
            .task {
                history = await viewModel.historyDays(forCategory: target.categoryID)
                historyLoaded = true
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }

    /// The days before today, each under its date; a failed read and an empty history say so.
    @ViewBuilder
    private var historySections: some View {
        if let days = history, !days.isEmpty {
            ForEach(days) { day in
                Section(day.date) {
                    ForEach(day.entries) { entry in
                        entryRow(entry)
                            .listRowBackground(DS.Palette.card)
                    }
                }
            }
        } else if historyLoaded {
            Section("История") {
                Text(history == nil ? "Не удалось загрузить историю." : "Раньше записей нет.")
                    .foregroundStyle(DS.Palette.textSecondary)
                    .listRowBackground(DS.Palette.card)
            }
        }
    }

    private func entryRow(_ entry: EntryDTO) -> some View {
        HStack(spacing: DS.Spacing.md) {
            Text(EntrySummary.line(for: entry, category: target.category))
                .foregroundStyle(DS.Palette.textPrimary)
                .lineLimit(2)
            Spacer()
            if entry.isPending, viewModel.waitingCategoryIDs.contains(entry.categoryId) {
                PendingRowTag()
            }
        }
        .frame(minHeight: 44)
    }

    private func delete(at offsets: IndexSet) {
        let doomed = offsets.map { entries[$0] }.filter { !$0.isPending }
        Task {
            for entry in doomed {
                _ = await viewModel.deleteEntry(id: entry.id)
            }
            await quickMarks.load()
        }
    }
}
