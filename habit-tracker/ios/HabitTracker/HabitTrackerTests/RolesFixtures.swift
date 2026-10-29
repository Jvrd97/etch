// [review:need-review] PHASE-01/266
// summary: server-shaped JSON of the role endpoints (a day with one automatic and one manual block, a summary that lags, a rule, a dry run, a re-markup answer) decoded with the app's own decoder, and a scripted RolesAPI for the view-model tests
import Foundation
@testable import HabitTracker

enum RolesFixtures {
    static let dayJSON = """
    {"work_day":"2026-08-27","total_minutes":150,
     "roles":[
       {"role_id":1,"role_code":"cto","title":"Тимлид","minutes":90,"share_pct":60,"target_share_pct":40,"act_count":2},
       {"role_id":2,"role_code":"dev","title":"Разработчик","minutes":30,"share_pct":20,"target_share_pct":null,"act_count":0},
       {"role_id":9,"role_code":"unassigned","title":"Не отнесено","minutes":30,"share_pct":20,"target_share_pct":null,"act_count":0}],
     "blocks":[
       {"id":11,"work_day":"2026-08-27","role_id":1,"role_code":"cto","source":"manual","started_at":null,"ended_at":null,
        "minutes":90,"confidence":"manual","external_ref":null,"rule_id":null,"note":"найм","is_manual":true,"is_automatic":false,
        "rule_summary":null,"app_name":null},
       {"id":12,"work_day":"2026-08-27","role_id":2,"role_code":"dev","source":"app_usage","started_at":null,"ended_at":null,
        "minutes":30,"confidence":"auto","external_ref":null,"rule_id":5,"note":null,"is_manual":false,"is_automatic":true,
        "rule_summary":"bundle_id = com.apple.dt.Xcode","app_name":"Xcode"}],
     "acts":[
       {"id":21,"work_day":"2026-08-27","role_id":1,"role_code":"cto","act_kind":"adr_written","title":"ADR-0020","source":"manual",
        "external_ref":null,"confidence":"manual","occurred_at":null,"note":null,"is_manual":true,"plan_item_id":null,"plan_item_text":null},
       {"id":22,"work_day":"2026-08-27","role_id":1,"role_code":"cto","act_kind":"hiring_step","title":"созвон","source":"plan",
        "external_ref":null,"confidence":"auto","occurred_at":null,"note":null,"is_manual":false,"plan_item_id":"p1","plan_item_text":"Созвон с кандидатом"}]}
    """

    static let rolesJSON = """
    [{"id":1,"code":"cto","title":"Тимлид","description":null,"target_share_pct":40,"is_work":true,"ord":1,"is_active":true},
     {"id":2,"code":"dev","title":"Разработчик","description":null,"target_share_pct":null,"is_work":true,"ord":2,"is_active":true}]
    """

    static let summaryJSON = """
    {"date_from":"2026-08-21","date_to":"2026-08-27","total_minutes":600,
     "roles":[
       {"role_id":1,"role_code":"cto","title":"Тимлид","minutes":300,"share_pct":50,"target_share_pct":40,"delta_pct":10,
        "act_counts":{"hiring_step":1,"adr_written":2},"act_total":3},
       {"role_id":9,"role_code":"unassigned","title":"Не отнесено","minutes":120,"share_pct":20,"target_share_pct":null,"delta_pct":null,
        "act_counts":{},"act_total":0}],
     "unassigned_minutes":120,"unassigned_share_pct":20,"window_from":"2026-07-29","window_minutes":2000,
     "window_unassigned_share_pct":35,"lag_threshold_pct":30,"rules_lag":true,"markdown":"# Отчёт"}
    """

    static let blockJSON = """
    {"id":12,"work_day":"2026-08-27","role_id":2,"role_code":"dev","source":"app_usage","started_at":null,"ended_at":null,
     "minutes":30,"confidence":"auto","external_ref":null,"rule_id":5,"note":null,"is_manual":false,"is_automatic":true,
     "rule_summary":null,"app_name":null}
    """

    static let ruleJSON = """
    {"id":5,"role_id":2,"role_code":"dev","source":"app_usage","matcher_kind":"bundle_id","pattern":"com.apple.dt.Xcode","priority":10,"is_active":false}
    """

    static let rulesJSON = """
    [{"id":5,"role_id":2,"role_code":"dev","source":"app_usage","matcher_kind":"bundle_id","pattern":"com.apple.dt.Xcode","priority":10,"is_active":true},
     {"id":6,"role_id":1,"role_code":"cto","source":"git","matcher_kind":"commit_prefix","pattern":"docs(","priority":20,"is_active":false}]
    """

    static let dryRunJSON = """
    {"date_from":"2026-07-29","date_to":"2026-08-27","scanned_rows":40,"matched_time_blocks":7,"matched_acts":1,
     "taken_from":{"5":3},"taken_from_nobody":4,
     "examples":[{"kind":"time_block","work_day":"2026-08-20","label":"Xcode","current_role_id":2,"taken_from_rule_id":5}]}
    """

    static let reclassifiedJSON = """
    {"date_from":"2026-07-29","date_to":"2026-08-27","scanned_rows":40,"changed_time_blocks":6,"changed_acts":0,"protected":2,
     "before":[{"role_id":1,"minutes":100,"share_pct":40},{"role_id":2,"minutes":50,"share_pct":20}],
     "after":[{"role_id":1,"minutes":150,"share_pct":55},{"role_id":2,"minutes":50,"share_pct":20}]}
    """

    static func decode<T: Decodable>(_ json: String) throws -> T {
        try APIJSONCoding.makeDecoder().decode(T.self, from: Data(json.utf8))
    }

    static func day() throws -> RoleDayDTO { try decode(dayJSON) }
    static func roles() throws -> [RoleDTO] { try decode(rolesJSON) }
    static func summary() throws -> RoleSummaryDTO { try decode(summaryJSON) }
    static func rules() throws -> [RoleRuleDTO] { try decode(rulesJSON) }
    static func dryRun() throws -> RoleRuleDryRunDTO { try decode(dryRunJSON) }
    static func reclassified() throws -> RoleReclassifiedDTO { try decode(reclassifiedJSON) }
}

final class MockRolesAPI: RolesAPI {
    var day: () async throws -> RoleDayDTO = { try RolesFixtures.day() }
    var roles: () async throws -> [RoleDTO] = { try RolesFixtures.roles() }
    var summary: (String, String) async throws -> RoleSummaryDTO = { _, _ in try RolesFixtures.summary() }
    var rules: () async throws -> [RoleRuleDTO] = { try RolesFixtures.rules() }
    var write: () async throws -> Void = {}
    private(set) var summaryRequests: [(String, String)] = []
    private(set) var timeBlockDrafts: [RoleTimeBlockDraftDTO] = []
    private(set) var actDrafts: [RoleActDraftDTO] = []
    private(set) var ruleDrafts: [RoleRuleDraftDTO] = []
    private(set) var dryRunDrafts: [RoleRuleDraftDTO] = []
    private(set) var deleted: [Int] = []
    private(set) var confirmed: [Int] = []
    private(set) var toggled: [(Int, Bool)] = []
    private(set) var reclassifyRequests: [(String, String)] = []

    func fetchRoles() async throws -> [RoleDTO] { try await roles() }
    func fetchRoleDay() async throws -> RoleDayDTO { try await day() }
    func fetchRoleSummary(dateFrom: String, dateTo: String) async throws -> RoleSummaryDTO {
        summaryRequests.append((dateFrom, dateTo))
        return try await summary(dateFrom, dateTo)
    }
    func fetchRoleRules() async throws -> [RoleRuleDTO] { try await rules() }
    func addRoleRule(_ draft: RoleRuleDraftDTO) async throws -> RoleRuleDTO {
        ruleDrafts.append(draft)
        try await write()
        return try RolesFixtures.rules()[0]
    }
    func setRoleRuleActive(id: Int, isActive: Bool) async throws -> RoleRuleDTO {
        toggled.append((id, isActive))
        try await write()
        return try RolesFixtures.rules()[0]
    }
    func dryRunRoleRule(_ draft: RoleRuleDraftDTO) async throws -> RoleRuleDryRunDTO {
        dryRunDrafts.append(draft)
        try await write()
        return try RolesFixtures.dryRun()
    }
    func reclassifyRoles(dateFrom: String, dateTo: String) async throws -> RoleReclassifiedDTO {
        reclassifyRequests.append((dateFrom, dateTo))
        try await write()
        return try RolesFixtures.reclassified()
    }
    func addRoleTimeBlock(_ draft: RoleTimeBlockDraftDTO) async throws -> RoleTimeBlockDTO {
        timeBlockDrafts.append(draft)
        try await write()
        return try RolesFixtures.day().blocks[0]
    }
    func deleteRoleTimeBlock(id: Int) async throws {
        deleted.append(id)
        try await write()
    }
    func confirmRoleTimeBlock(id: Int) async throws -> RoleTimeBlockDTO {
        confirmed.append(id)
        try await write()
        return try RolesFixtures.day().blocks[1]
    }
    func addRoleAct(_ draft: RoleActDraftDTO) async throws -> RoleActDTO {
        actDrafts.append(draft)
        try await write()
        return try RolesFixtures.day().acts[0]
    }
}
