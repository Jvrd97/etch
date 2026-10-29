// [review:need-review] PHASE-01/266
// summary: RolesAPI — the role endpoints the mobile web calls (/roles, /roles/day, /roles/summary, /role-rules[...], /roles/reclassify, /role-time-blocks, /role-acts); APIClient implements it on the shared request helpers
import Foundation

/// API surface of the Roles screens; `APIClient` is the production implementation.
protocol RolesAPI {
    func fetchRoles() async throws -> [RoleDTO]
    /// The server's running day: it turns at 04:00, not at midnight.
    func fetchRoleDay() async throws -> RoleDayDTO
    func fetchRoleSummary(dateFrom: String, dateTo: String) async throws -> RoleSummaryDTO
    func fetchRoleRules() async throws -> [RoleRuleDTO]
    func addRoleRule(_ draft: RoleRuleDraftDTO) async throws -> RoleRuleDTO
    func setRoleRuleActive(id: Int, isActive: Bool) async throws -> RoleRuleDTO
    /// Runs the rule over the history without saving it.
    func dryRunRoleRule(_ draft: RoleRuleDraftDTO) async throws -> RoleRuleDryRunDTO
    func reclassifyRoles(dateFrom: String, dateTo: String) async throws -> RoleReclassifiedDTO
    func addRoleTimeBlock(_ draft: RoleTimeBlockDraftDTO) async throws -> RoleTimeBlockDTO
    func deleteRoleTimeBlock(id: Int) async throws
    func confirmRoleTimeBlock(id: Int) async throws -> RoleTimeBlockDTO
    func addRoleAct(_ draft: RoleActDraftDTO) async throws -> RoleActDTO
}

extension APIClient: RolesAPI {
    func fetchRoles() async throws -> [RoleDTO] {
        try await getJSON(path: "/roles", query: [])
    }

    func fetchRoleDay() async throws -> RoleDayDTO {
        try await getJSON(path: "/roles/day", query: [])
    }

    func fetchRoleSummary(dateFrom: String, dateTo: String) async throws -> RoleSummaryDTO {
        try await getJSON(
            path: "/roles/summary",
            query: [
                URLQueryItem(name: "date_from", value: dateFrom),
                URLQueryItem(name: "date_to", value: dateTo),
            ]
        )
    }

    func fetchRoleRules() async throws -> [RoleRuleDTO] {
        try await getJSON(path: "/role-rules", query: [])
    }

    func addRoleRule(_ draft: RoleRuleDraftDTO) async throws -> RoleRuleDTO {
        try await sendJSON(path: "/role-rules", method: "POST", body: draft)
    }

    func setRoleRuleActive(id: Int, isActive: Bool) async throws -> RoleRuleDTO {
        try await sendJSON(path: "/role-rules/\(id)", method: "PATCH", body: RoleRulePatchDTO(isActive: isActive))
    }

    func dryRunRoleRule(_ draft: RoleRuleDraftDTO) async throws -> RoleRuleDryRunDTO {
        try await sendJSON(path: "/role-rules/dry-run", method: "POST", body: draft)
    }

    func reclassifyRoles(dateFrom: String, dateTo: String) async throws -> RoleReclassifiedDTO {
        try await sendJSON(
            path: "/roles/reclassify", method: "POST",
            body: RoleDateRangeDTO(dateFrom: dateFrom, dateTo: dateTo)
        )
    }

    func addRoleTimeBlock(_ draft: RoleTimeBlockDraftDTO) async throws -> RoleTimeBlockDTO {
        try await sendJSON(path: "/role-time-blocks", method: "POST", body: draft)
    }

    func deleteRoleTimeBlock(id: Int) async throws {
        let url = try makeAPIURL(path: "/role-time-blocks/\(id)", query: [])
        _ = try await send(makeRequest(url: url, method: "DELETE"))
    }

    func confirmRoleTimeBlock(id: Int) async throws -> RoleTimeBlockDTO {
        try await sendJSON(path: "/role-time-blocks/\(id)", method: "PATCH", body: RoleConfirmDTO())
    }

    func addRoleAct(_ draft: RoleActDraftDTO) async throws -> RoleActDTO {
        try await sendJSON(path: "/role-acts", method: "POST", body: draft)
    }
}
