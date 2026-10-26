// [review:need-review] PHASE-01/211
// summary: Codable DTOs of the Day screen — GET /day answer (plan tree, marks, category-linked facts, task counts, notebook, summary), mark/fact/notebook/closing request bodies; decoded with APIJSONCoding (snake_case), dates stay "yyyy-MM-dd" strings, plan windows stay ISO timestamps
import Foundation

/// `GET /api/v1/day[/{date}]`. Only the parts the iOS screen draws are decoded;
/// the server's other blocks (day map, anchors, training, work) are ignored.
struct DayDetailDTO: Codable, Equatable {
    let day: DayHeadDTO
    let rule: DayRuleDTO
    let plan: DayPlanDTO?
    let hasPlan: Bool
    let marks: [DayMarkDTO]
    let planFacts: [PlanItemFactsDTO]
    let taskCounts: TaskCountsDTO
    let notebook: String?
    let summary: DaySummaryDTO
}

struct DayHeadDTO: Codable, Equatable {
    let date: String
    /// `work` or `off`.
    let kind: String
    let isNocode: Bool
    let openedAt: String?
}

/// The slice of the day's rule the screen needs: the bar the task counter is shown against.
/// `timezone` is decoded for completeness; plan windows are read in the device's zone.
struct DayRuleDTO: Codable, Equatable {
    let timezone: String
    let maxWorkTasks: Int
}

struct DayPlanDTO: Codable, Equatable {
    let id: UUID
    let lede: String?
    let needsReview: Bool
    let sections: [DayPlanSectionDTO]
}

struct DayPlanSectionDTO: Codable, Equatable, Identifiable {
    let id: UUID
    let title: String?
    let kind: String
    let items: [DayPlanItemDTO]
}

/// One line of the plan. `children` nests a task's minimum (and any sub-step).
struct DayPlanItemDTO: Codable, Equatable, Identifiable {
    let id: UUID
    let kind: String
    let textPlain: String
    let startsAt: String?
    let endsAt: String?
    let code: String?
    let categoryId: Int?
    let targetValue: Double?
    let children: [DayPlanItemDTO]
}

/// Mark of one item. `state` is `done`, `failed`, `skipped`, or nil for "no mark".
struct DayMarkDTO: Codable, Equatable {
    let itemId: UUID
    let state: String?
    let note: String?
}

struct TaskCountsDTO: Codable, Equatable {
    let planned: Int
    let done: Int
    let failed: Int
    let skipped: Int
    let pending: Int
}

// MARK: - Category-linked facts (#200)

/// A plan line linked to a category: the link, the entries it wrote, how they add up.
struct PlanItemFactsDTO: Codable, Equatable {
    let itemId: UUID
    let link: PlanLinkDTO
    let entries: [PlanFactEntryDTO]
    let total: Double?
    let done: Bool
    /// `none`, `partial`, `met` or `recorded`.
    let progress: String
}

struct PlanLinkDTO: Codable, Equatable {
    let categoryId: Int
    let categoryName: String
    let categoryActive: Bool
    let fieldId: Int?
    let fieldName: String?
    /// `number`, `duration` or `boolean` for a linkable field.
    let fieldType: String?
    let unit: String?
    let targetValue: Double?
    /// `ok` when a fact can be written; any other value says why not.
    let state: String
    let fields: [PlanLinkFieldDTO]
}

struct PlanLinkFieldDTO: Codable, Equatable {
    let id: Int
    let name: String
    let fieldType: String
    let unit: String?
}

struct PlanFactEntryDTO: Codable, Equatable, Identifiable {
    let entryId: Int
    let entryDate: String
    let values: [PlanFactValueDTO]

    var id: Int { entryId }
}

struct PlanFactValueDTO: Codable, Equatable {
    let fieldId: Int
    let value: String?
}

/// Answer of a fact write: the entry touched, the line's whole state, the mark.
struct PlanFactWriteDTO: Codable, Equatable {
    let entryId: Int
    let facts: PlanItemFactsDTO?
    let mark: DayMarkDTO
}

// MARK: - Summary

struct DaySummaryDTO: Codable, Equatable {
    let dayDate: String
    let closed: Bool
    /// `open`, `reviewed` or `closed`.
    let stage: String
    let reviewSkipped: Bool
    /// `won`, `lost` or nil while the day is not closed.
    let verdict: String?
    /// `tasks`, `anchors`, `overtime`, `role_act`, `not_closed` or "".
    let verdictReason: String
    let anchorsDone: Int
    let anchorsTotal: Int
    let tasksDone: Int
    let tasksTotal: Int
    let workMinutes: Int?
    let streakAfter: Int?
    let bodyMd: String
    let missingAnchors: [String]
    let clauses: [DayClauseDTO]
}

struct DayClauseDTO: Codable, Equatable {
    let code: String
    let passed: Bool
    let detail: String
}

// MARK: - Request bodies

/// `PUT /day/{on}/marks/{item_id}`. A nil `state` removes the mark; the note is
/// resent with every change so a state flip does not clear it.
struct DayMarkRequestDTO: Encodable, Equatable {
    let state: String?
    let note: String?
}

/// A fact value: a number (also whole seconds for a duration) or a box.
enum PlanFactValue: Equatable, Encodable {
    case number(Double)
    case flag(Bool)

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .number(let number): try container.encode(number)
        case .flag(let flag): try container.encode(flag)
        }
    }
}

struct PlanFactValueRequestDTO: Encodable, Equatable {
    let fieldId: Int
    let value: PlanFactValue
    let unit: String?
}

/// `POST|PUT /day/{on}/plan/items/{id}/facts[/{entry}]`. `mark` is `done` or `unmark`.
struct PlanFactRequestDTO: Encodable, Equatable {
    let values: [PlanFactValueRequestDTO]
    let mark: String?
}

struct NotebookRequestDTO: Encodable, Equatable {
    let content: String
}

/// Body of both closing touches (`/close/review`, `/close/final`). A nil field means
/// "keep what is recorded" on the server, never "erase".
struct DayClosingRequestDTO: Encodable, Equatable {
    let workMinutes: Int?
    let bodyMd: String?
}
