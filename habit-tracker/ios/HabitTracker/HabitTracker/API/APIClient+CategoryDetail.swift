// [review:need-review] PHASE-03/310
// summary: CategoryChartAPI — the category screen's chart asks GET /table for its own category only (`category_id`); a server without the filter ignores it and answers every category, and the chart picks its own either way
import Foundation

/// API surface of the category screen: its chart reads the table of one category.
protocol CategoryChartAPI: CategoryDetailAPI {
    func fetchTable(dateFrom: String, dateTo: String, categoryId: Int) async throws -> TableResponseDTO
}

extension APIClient: CategoryChartAPI {
    func fetchTable(dateFrom: String, dateTo: String, categoryId: Int) async throws -> TableResponseDTO {
        try await getJSON(
            path: "/table",
            query: [
                URLQueryItem(name: "date_from", value: dateFrom),
                URLQueryItem(name: "date_to", value: dateTo),
                URLQueryItem(name: "category_id", value: String(categoryId)),
            ]
        )
    }
}
