// [review:need-review] PHASE-01/210
// summary: state of the relapse history screen of one avoid category — one read of the server's history, then the analysis and the chart for the chosen period are computed locally from the server's today
import Foundation

@MainActor
final class RelapseHistoryViewModel: ObservableObject {
    enum LoadState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    /// How many of the latest relapse days the list spells out.
    static let recentDaysShown = 10

    @Published private(set) var state: LoadState = .idle
    @Published private(set) var history: RelapseHistoryDTO?
    @Published var period: RelapsePeriod = .days30

    private let categoryId: Int
    private let apiProvider: () -> RelapseHistoryAPI?

    init(categoryId: Int, apiProvider: @escaping () -> RelapseHistoryAPI?) {
        self.categoryId = categoryId
        self.apiProvider = apiProvider
    }

    static func live(categoryId: Int) -> RelapseHistoryViewModel {
        RelapseHistoryViewModel(categoryId: categoryId, apiProvider: { APIClient.live() })
    }

    func load() async {
        guard let api = apiProvider() else {
            state = .failure(TodayViewModel.notConfiguredMessage)
            return
        }
        if history == nil { state = .loading }
        do {
            history = try await api.fetchRelapseHistory(categoryId: categoryId)
            state = .loaded
        } catch let error as APIClientError {
            state = .failure(error.userMessage)
        } catch {
            state = .failure("Unexpected error")
        }
    }

    /// Week and month windows end on the server's today: the day may end at 04:00, not at midnight.
    var summary: RelapseSummary? {
        history.map {
            RelapseAnalysis.summarize(
                relapseDates: $0.relapseDates, trackedSince: $0.trackedSince, today: $0.today
            )
        }
    }

    var timeline: RelapseTimeline? {
        history.map {
            RelapseAnalysis.timeline(
                relapseDates: $0.relapseDates, trackedSince: $0.trackedSince, today: $0.today,
                period: period
            )
        }
    }

    /// The latest relapse days, newest first.
    var recentDays: [String] {
        Array((history?.relapseDates ?? []).suffix(Self.recentDaysShown).reversed())
    }
}
