// [review:need-review] PHASE-01/36-ios-category-charts, PHASE-01/208
// summary: Single-category detail state — entries + quick-add + shared mutation surface, plus chart state (table history, period/mode toggles, line series, checklist bars, streaks)
import Foundation
import os

@MainActor
final class CategoryDetailViewModel: ObservableObject, EntryMutating {
    private static let logger = Logger(
        subsystem: "com.habittracker.app", category: "CategoryDetailViewModel"
    )

    /// The category this screen is scoped to; drives the header and field labels.
    let category: CategoryDTO

    @Published private(set) var state: EntryLoadState = .idle
    @Published var entries: [EntryDTO] = []
    /// Aggregated per-day history behind the chart, ascending by date. Loaded
    /// from `GET /table` alongside the entry list; empty until the first load.
    @Published private(set) var tableDays: [TableDayDTO] = []
    /// Chart controls (bound to the on-screen toggles).
    @Published var selectedPeriod: ChartPeriod = .thirtyDays
    @Published var chartMode: ChartMode = .perDay
    /// Raw text bound to the quick-add field (the category's first field).
    @Published var quickAddValue: String = ""
    /// The entry currently open in the edit form; `nil` when no form is shown.
    /// A failed save leaves it intact so the user's input is never lost.
    @Published var editDraft: EntryEditDraft?
    @Published var saveErrorMessage: String?

    private let apiProvider: () -> CategoryDetailAPI?
    private let dateFormatter: DateFormatter
    private let now: () -> Date

    /// Primary init: the provider is re-evaluated on every call, so Settings
    /// changes (server address / API key) take effect without an app restart.
    init(
        category: CategoryDTO,
        apiProvider: @escaping () -> CategoryDetailAPI?,
        timeZone: TimeZone = .current,
        now: @escaping () -> Date = Date.init
    ) {
        self.category = category
        self.apiProvider = apiProvider
        self.now = now
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        self.dateFormatter = formatter
    }

    /// Convenience init with a fixed API (used by unit tests).
    convenience init(
        category: CategoryDTO,
        api: CategoryDetailAPI,
        timeZone: TimeZone = .current,
        now: @escaping () -> Date = Date.init
    ) {
        self.init(category: category, apiProvider: { api }, timeZone: timeZone, now: now)
    }

    /// Builds the production view model for a category from stored Settings.
    static func live(category: CategoryDTO) -> CategoryDetailViewModel {
        CategoryDetailViewModel(
            category: category, apiProvider: { APIClient.live() }
        )
    }

    func mutationAPI() -> EntryMutationAPI? { apiProvider() }

    // MARK: - Derived state

    /// Today's date in the backend's `YYYY-MM-DD` format.
    var todayString: String {
        dateFormatter.string(from: now())
    }

    /// The field the quick-add box writes to: the category's first field by order.
    var quickAddField: FieldDTO? {
        category.fields.sorted { $0.order < $1.order }.first
    }

    // MARK: - Chart

    /// Line series for the category's number/time fields (empty for checklists).
    var chartSeries: [ChartSeries] {
        CategoryChart.buildSeries(category.fields)
    }

    /// Whether the chart renders as a checklist "X of N" bar with streaks
    /// instead of value lines.
    var isChecklistChart: Bool {
        category.isChecklist || !CategoryChart.booleanFields(category.fields).isEmpty
    }

    /// Per-day (or cumulative) line points for the selected period. The window
    /// is sliced first, then optionally folded into a running total, so the
    /// cumulative curve starts from zero within the visible range.
    var linePoints: [ChartPoint] {
        let base = CategoryChart.buildChartData(
            days: tableDays, categoryId: category.id, fields: category.fields
        )
        let sliced = CategoryChart.sliceByPeriod(base, period: selectedPeriod)
        return chartMode == .cumulative ? CategoryChart.cumulate(sliced) : sliced
    }

    /// "X of N" bars for the selected period (checklist categories).
    var checklistBarPoints: [ChecklistBarPoint] {
        let base = CategoryChart.buildChecklistBarData(
            days: tableDays, categoryId: category.id, fields: category.fields
        )
        return CategoryChart.sliceByPeriod(base, period: selectedPeriod)
    }

    /// Current streak per boolean field, computed over the full loaded history
    /// (not the sliced window), in field order.
    var fieldStreaks: [(field: FieldDTO, streak: Int)] {
        CategoryChart.booleanFields(category.fields).map { field in
            (
                field: field,
                streak: CategoryChart.currentStreak(
                    days: tableDays,
                    categoryId: category.id,
                    fieldId: field.id,
                    today: todayString
                )
            )
        }
    }

    // MARK: - Loading

    /// Loads this category's entry history (server-side filtered by category id)
    /// and the aggregated table history that backs the chart. The entry list
    /// drives the screen's load state; a table failure only leaves the chart
    /// empty (secondary content) rather than failing the whole screen.
    func load() async {
        state = .loading
        guard let api = apiProvider() else {
            state = .failure(Self.notConfiguredMessage)
            return
        }
        do {
            entries = try await api.fetchEntries(categoryId: category.id)
            await loadChart(using: api)
            state = .loaded
        } catch let error as APIClientError {
            state = .failure(error.userMessage)
        } catch {
            state = .failure("Unexpected error")
        }
    }

    /// Fetches the widest chart window and stores it ascending by date so period
    /// slicing keeps the most recent days and lines read left-to-right in time.
    private func loadChart(using api: CategoryDetailAPI) async {
        let range = CategoryChart.chartDateRange(today: now())
        do {
            let response = try await api.fetchTable(dateFrom: range.from, dateTo: range.to)
            tableDays = response.days.sorted { $0.date < $1.date }
        } catch {
            // Chart is secondary content: a table failure must not fail the
            // whole screen. Drop to an empty chart and log (no PII).
            tableDays = []
            Self.logger.error("Chart table load failed: \(String(describing: error))")
        }
    }

    // MARK: - Quick-add

    /// Records today's value for the category's first field via generic POST.
    /// A blank value or a category without fields is a no-op. On success the new
    /// entry is inserted at the top of the list and the input is cleared. Returns
    /// true on success.
    func quickAdd() async -> Bool {
        saveErrorMessage = nil
        let trimmed = quickAddValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let field = quickAddField else { return false }
        guard let api = requireAPI() as? CategoryDetailAPI else { return false }
        let payload = EntryCreateDTO(
            categoryId: category.id,
            entryDate: todayString,
            notes: nil,
            values: [EntryValueDTO(fieldId: field.id, value: trimmed)]
        )
        do {
            let created = try await api.createEntry(payload)
            entries.insert(created, at: 0)
            quickAddValue = ""
            return true
        } catch let error as APIClientError {
            saveErrorMessage = error.userMessage
            return false
        } catch {
            saveErrorMessage = "Unexpected error"
            return false
        }
    }
}
