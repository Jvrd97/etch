// [review:need-review] PHASE-03/294
// summary: the order of the Today cards by use — entries in the last 30 days (from the day table), the latest filled day on a tie, the server's order after that; the order is fixed by a load, so a tap never moves a card under the finger
import Foundation

/// How much one category was filled in the window: the entries and the latest day with one.
struct CategoryUsage: Codable, Equatable {
    let entryCount: Int
    let lastEntryDate: String?
}

enum TodayOrdering {
    /// The window of the count, today included.
    static let windowDays = 30

    /// Entries per category over the table's days. A day's entries of a category are the largest count among
    /// its field cells: every cell of a day counts the same entries, the ones that have a value for its field.
    static func usage(from table: TableResponseDTO) -> [Int: CategoryUsage] {
        var counts: [Int: Int] = [:]
        var lastDays: [Int: String] = [:]
        for day in table.days {
            var perCategory: [Int: Int] = [:]
            for cell in day.cells {
                perCategory[cell.categoryId] = max(perCategory[cell.categoryId] ?? 0, cell.entryCount)
            }
            for (categoryID, count) in perCategory where count > 0 {
                counts[categoryID, default: 0] += count
                if day.date > (lastDays[categoryID] ?? "") { lastDays[categoryID] = day.date }
            }
        }
        return counts.reduce(into: [:]) { result, item in
            result[item.key] = CategoryUsage(entryCount: item.value, lastEntryDate: lastDays[item.key])
        }
    }

    /// Most used first, then the more recently filled. Equal categories keep the order they came in, and
    /// without a usage read the order is untouched.
    static func sorted(_ categories: [CategoryDTO], usage: [Int: CategoryUsage]?) -> [CategoryDTO] {
        guard let usage else { return categories }
        return categories.enumerated().sorted { lhs, rhs in
            let left = usage[lhs.element.id]
            let right = usage[rhs.element.id]
            if (left?.entryCount ?? 0) != (right?.entryCount ?? 0) {
                return (left?.entryCount ?? 0) > (right?.entryCount ?? 0)
            }
            if (left?.lastEntryDate ?? "") != (right?.lastEntryDate ?? "") {
                return (left?.lastEntryDate ?? "") > (right?.lastEntryDate ?? "")
            }
            return lhs.offset < rhs.offset
        }.map(\.element)
    }
}
