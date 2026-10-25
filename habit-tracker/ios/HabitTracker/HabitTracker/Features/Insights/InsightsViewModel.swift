// [review:need-review] PHASE-01/37-ios-insights, PHASE-01/208
// summary: Insights state — load report history, run a period analysis (503→not-configured hint, 502→retryable failure), open a past report
import Foundation
import os

/// The trailing period offered by the analysis selector, in days.
enum InsightPeriod: Int, CaseIterable, Identifiable {
    case week = 7
    case month = 30
    case quarter = 90

    var id: Int { rawValue }

    /// Length of the analysis window in days (mirrors the backend `period_days`).
    var days: Int { rawValue }

    /// User-facing label for the segmented selector.
    var label: String {
        switch self {
        case .week: return "7 дней"
        case .month: return "30 дней"
        case .quarter: return "90 дней"
        }
    }
}

@MainActor
final class InsightsViewModel: ObservableObject {
    /// Discriminated load state for the report history list.
    enum HistoryState: Equatable {
        case idle
        case loading
        case loaded
        case failure(String)
    }

    /// State of the "разбор периода" action. `notConfigured` is the honest hint for a
    /// backend that answered 503 (no LLM key); `failure` is a retryable error (e.g. 502).
    enum AnalysisState: Equatable {
        case idle
        case running
        case notConfigured
        case failure(String)
    }

    @Published private(set) var historyState: HistoryState = .idle
    @Published private(set) var reports: [InsightListItemDTO] = []

    /// Selected analysis window; drives the POST payload.
    @Published var selectedPeriod: InsightPeriod = .month

    @Published private(set) var analysisState: AnalysisState = .idle

    /// The report currently open for reading (full Markdown), or nil when none is shown.
    @Published var openedReport: InsightReportDTO?
    /// Error surfaced while opening a past report from history.
    @Published var openErrorMessage: String?

    static let notConfiguredMessage = "Set the server address in Settings"
    /// Backend `PREVIEW_MAX_CHARS`: how far a fresh report's content is truncated when
    /// derived into a history row locally (so it appears without a reload round trip).
    static let previewMaxChars = 200
    /// HTTP status the backend returns when AI insights are disabled (no LLM backend).
    static let notConfiguredStatus = 503

    private let apiProvider: () -> InsightsAPI?

    private static let logger = Logger(
        subsystem: "com.habittracker.app", category: "InsightsViewModel"
    )

    /// Primary init: the provider is re-evaluated on every call, so Settings changes
    /// (server address / API key) take effect without an app restart.
    init(apiProvider: @escaping () -> InsightsAPI?) {
        self.apiProvider = apiProvider
    }

    /// Convenience init with a fixed API (used by unit tests).
    convenience init(api: InsightsAPI) {
        self.init(apiProvider: { api })
    }

    /// A generous timeout: the POST blocks on a synchronous LLM call server-side.
    static let analysisTimeout: TimeInterval = 120

    /// Builds the production view model from stored Settings (UserDefaults + Keychain),
    /// wiring a long-timeout client so the LLM round trip is not cut short.
    static func live() -> InsightsViewModel {
        InsightsViewModel(apiProvider: {
            APIClient.live(timeout: analysisTimeout)
        })
    }

    // MARK: - History

    /// Loads the report history (`GET /insights`), newest first as sent by the backend.
    func load() async {
        historyState = .loading
        guard let api = apiProvider() else {
            historyState = .failure(Self.notConfiguredMessage)
            return
        }
        do {
            reports = try await api.fetchInsights()
            historyState = .loaded
        } catch let error as APIClientError {
            historyState = .failure(error.userMessage)
        } catch {
            historyState = .failure("Unexpected error")
        }
    }

    // MARK: - Analysis

    /// Runs a fresh analysis over `selectedPeriod` via `POST /insights`. On success the
    /// report is opened for reading and prepended to the history (no reload needed).
    /// A 503 means the backend has no LLM configured — surfaced as an honest hint, not
    /// a transient error; any other failure is retryable. Returns true on success.
    func runAnalysis() async -> Bool {
        analysisState = .running
        guard let api = apiProvider() else {
            analysisState = .failure(Self.notConfiguredMessage)
            return false
        }
        do {
            let report = try await api.createInsight(
                InsightRequestDTO(periodDays: selectedPeriod.days)
            )
            openedReport = report
            reports.insert(Self.listItem(from: report), at: 0)
            analysisState = .idle
            return true
        } catch APIClientError.unexpectedStatus(Self.notConfiguredStatus) {
            analysisState = .notConfigured
            return false
        } catch let error as APIClientError {
            analysisState = .failure(error.userMessage)
            return false
        } catch {
            analysisState = .failure("Unexpected error")
            return false
        }
    }

    // MARK: - Viewing

    /// Opens a past report in full via `GET /insights/{id}`. On failure the previously
    /// open report is untouched and an error message is surfaced.
    func openReport(id: Int) async {
        openErrorMessage = nil
        guard let api = apiProvider() else {
            openErrorMessage = Self.notConfiguredMessage
            return
        }
        do {
            openedReport = try await api.fetchInsight(id: id)
        } catch let error as APIClientError {
            openErrorMessage = error.userMessage
        } catch {
            openErrorMessage = "Unexpected error"
        }
    }

    // MARK: - Private

    /// Derives a history row from a freshly created report, truncating the content to a
    /// preview the same way the backend does, so the new report shows without a reload.
    private static func listItem(from report: InsightReportDTO) -> InsightListItemDTO {
        InsightListItemDTO(
            id: report.id,
            periodDays: report.periodDays,
            model: report.model,
            createdAt: report.createdAt,
            preview: String(report.content.prefix(previewMaxChars))
        )
    }
}
