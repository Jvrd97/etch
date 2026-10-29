// [review:need-review] PHASE-01/266
// summary: wire types of the roles endpoints — the directory, one day (share per role, time blocks, acts), the period summary with the Friday report text, the markup rules with their dry run and the re-markup answer, and the bodies of the manual writes
import Foundation

struct RoleDTO: Codable, Equatable, Identifiable {
    let id: Int
    let code: String
    let title: String
    let description: String?
    let targetSharePct: Int?
    let isWork: Bool
    let ord: Int
    let isActive: Bool
}

struct RoleDaySliceDTO: Codable, Equatable {
    let roleId: Int
    let roleCode: String
    let title: String
    let minutes: Int
    let sharePct: Int
    let targetSharePct: Int?
    let actCount: Int
}

struct RoleTimeBlockDTO: Codable, Equatable, Identifiable {
    let id: Int
    let workDay: String
    let roleId: Int
    let roleCode: String
    let source: String
    let minutes: Int
    let confidence: String
    let ruleId: Int?
    let note: String?
    let isManual: Bool
    let isAutomatic: Bool
    let ruleSummary: String?
    let appName: String?
}

struct RoleActDTO: Codable, Equatable, Identifiable {
    let id: Int
    let workDay: String
    let roleId: Int
    let roleCode: String
    let actKind: String
    let title: String
    let isManual: Bool
    let planItemText: String?
}

struct RoleDayDTO: Codable, Equatable {
    let workDay: String
    let totalMinutes: Int
    let roles: [RoleDaySliceDTO]
    let blocks: [RoleTimeBlockDTO]
    let acts: [RoleActDTO]
}

struct RoleSummarySliceDTO: Codable, Equatable {
    let roleId: Int
    let roleCode: String
    let title: String
    let minutes: Int
    let sharePct: Int
    let targetSharePct: Int?
    let deltaPct: Int?
    let actCounts: [String: Int]
    let actTotal: Int
}

struct RoleSummaryDTO: Codable, Equatable {
    let dateFrom: String
    let dateTo: String
    let totalMinutes: Int
    let roles: [RoleSummarySliceDTO]
    let unassignedMinutes: Int
    let unassignedSharePct: Int
    let windowUnassignedSharePct: Int
    let lagThresholdPct: Int
    let rulesLag: Bool
    let markdown: String
}

struct RoleRuleDTO: Codable, Equatable, Identifiable {
    let id: Int
    let roleId: Int
    let roleCode: String
    let source: String
    let matcherKind: String
    let pattern: String
    let priority: Int
    let isActive: Bool
}

struct RoleRuleDraftDTO: Encodable, Equatable {
    let roleCode: String
    let source: String
    let matcherKind: String
    let pattern: String
    let priority: Int
}

struct RoleRulePatchDTO: Encodable, Equatable {
    let isActive: Bool
}

struct RoleRuleDryRunExampleDTO: Codable, Equatable {
    let kind: String
    let workDay: String
    let label: String
}

struct RoleRuleDryRunDTO: Codable, Equatable {
    let dateFrom: String
    let dateTo: String
    let scannedRows: Int
    let matchedTimeBlocks: Int
    let matchedActs: Int
    /// Rule id (as a string key) → rows the new rule would take from it.
    let takenFrom: [String: Int]
    let takenFromNobody: Int
    let examples: [RoleRuleDryRunExampleDTO]
}

struct RoleShareDTO: Codable, Equatable {
    let roleId: Int
    let sharePct: Int
}

struct RoleReclassifiedDTO: Codable, Equatable {
    let dateFrom: String
    let dateTo: String
    let scannedRows: Int
    let changedTimeBlocks: Int
    let changedActs: Int
    let `protected`: Int
    let before: [RoleShareDTO]
    let after: [RoleShareDTO]
}

struct RoleDateRangeDTO: Encodable, Equatable {
    let dateFrom: String
    let dateTo: String
}

struct RoleTimeBlockDraftDTO: Encodable, Equatable {
    let roleCode: String
    let minutes: Int
    let workDay: String
    let note: String?
}

struct RoleActDraftDTO: Encodable, Equatable {
    let roleCode: String
    let actKind: String
    let title: String
    let workDay: String
}

struct RoleConfirmDTO: Encodable, Equatable {
    let confidence = "confirmed"
}
