// [review:need-review] PHASE-03/229
// summary: Week screen (More → Неделя) — the numbers of a week against the previous one, best and worst day, health, and the AI text on a button; states: loading, error with retry (and a way back to the running week), empty week, unfinished week marked, last cached answer marked "обновлено …" offline; pull to refresh in place; no navigation stack of its own
import SwiftUI

struct WeekView: View {
    @StateObject private var viewModel: WeekViewModel

    /// No-argument init keeps `RootView` to one line: the model builds its client with `.live()`.
    init() {
        _viewModel = StateObject(wrappedValue: .live())
    }

    init(viewModel: WeekViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        content
            .navigationTitle(MoreDestination.week.title)
            .dsScreenBackground()
            .task { await viewModel.load() }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .idle, .loading:
            NeonLoader(label: "Загрузка")
        case .failure(let message):
            VStack(spacing: 0) {
                DSErrorState(message: message) { Task { await viewModel.load() } }
                if viewModel.requestedIso != nil {
                    Button("К текущей неделе") { Task { await viewModel.showCurrent() } }
                        .buttonStyle(LimeButtonStyle(prominent: false))
                        .fixedSize()
                        .padding(.bottom, DS.Spacing.xl)
                }
            }
        case .loaded:
            if let review = viewModel.review {
                loaded(review)
            }
        }
    }

    private func loaded(_ review: WeekReviewDTO) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DS.Spacing.xl) {
                WeekHeaderView(viewModel: viewModel, window: review.window)
                if WeekFormat.isEmpty(review) {
                    Text(WeekFormat.emptyWeekText)
                        .font(DS.Typography.body)
                        .foregroundStyle(DS.Palette.textSecondary)
                } else {
                    WeekTotalsView(review: review)
                    WeekDaysView(review: review)
                    WeekRolesView(review: review)
                    WeekCategoriesView(review: review)
                    WeekStreaksView(review: review)
                    WeekHealthView(review: review)
                }
                WeekNarrativeView(viewModel: viewModel, review: review)
            }
            .padding(DS.Spacing.lg)
        }
        .refreshable { await viewModel.refresh() }
    }
}
