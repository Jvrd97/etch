// [review:need-review] PHASE-01/266
// summary: texts and arithmetic of the Roles screens, ported from the mobile web's role-format / role-share / role-rules — minutes as «1 ч 30 мин», Russian plural forms, labels of act kinds, the target share always called a hypothesis, the unassigned line and the lag note, the markup source of an automatic block, period bounds, the dry-run and re-markup lines
import Foundation

enum RolesFormat {
    static let loadFailedMessage = "Не удалось загрузить роли"
    static let notConfiguredMessage = "Укажите адрес сервера и ключ API в Settings"
    static let emptyDirectoryText = "Справочник ролей пуст: примените миграцию — четыре роли приезжают с ней."
    static let noActsText = "Актов роли сегодня нет"
    static let noMinutesText = "Минут за день пока не записано"
    static let manualMark = "вручную"
    static let automaticMark = "автоматически"
    static let confirmedMark = "подтверждено"
    static let confirmLabel = "подтвердить"
    static let targetHypothesis = "гипотеза, не норма"
    static let unassignedCode = "unassigned"
    static let summaryEmptyText = "Записей за период нет."
    static let summaryTargetNote = "целевая доля — гипотеза квартала, а не норма"
    static let unassignedTitle = "Не отнесено"
    static let emptyRulesText =
        "Правил разметки пока нет: заведите первое — оно начнёт действовать на следующей же разметке."
    static let nothingToScan = "За этот период размеченных строк нет — прогонять пока не по чему."
    static let defaultMinutes = 90
    static let defaultPriority = 100

    static func message(for error: Error) -> String {
        guard let error = error as? APIClientError else { return loadFailedMessage }
        switch error {
        case .invalidBaseURL: return "Неверный адрес сервера"
        case .unauthorized: return "Неверный ключ API (401)"
        case .timeout: return "Сервер не ответил вовремя"
        case .transport: return "Нет связи с сервером"
        case .unexpectedStatus(let status): return "Сервер ответил ошибкой \(status)"
        case .invalidResponse: return "Сервер вернул непонятный ответ"
        }
    }

    // MARK: Plain numbers

    static func minutes(_ value: Int) -> String {
        let whole = max(0, value)
        let hours = whole / 60
        let rest = whole % 60
        if hours == 0 { return "\(rest) мин" }
        if rest == 0 { return "\(hours) ч" }
        return "\(hours) ч \(rest) мин"
    }

    /// The summary shows hours and minutes both, even when one is zero.
    static func summaryMinutes(_ value: Int) -> String {
        "\(value / 60) ч \(value % 60) мин"
    }

    /// `count` with the right one of three Russian forms: 1 акт, 2 акта, 5 актов, 11 актов.
    static func countable(_ count: Int, one: String, few: String, many: String) -> String {
        let lastTwo = abs(count) % 100
        let last = count % 10
        if lastTwo >= 11 && lastTwo <= 14 { return "\(count) \(many)" }
        if last == 1 { return "\(count) \(one)" }
        if (2...4).contains(last) { return "\(count) \(few)" }
        return "\(count) \(many)"
    }

    static func actsCount(_ count: Int) -> String {
        countable(count, one: "акт", few: "акта", many: "актов")
    }

    // MARK: Day

    struct Choice: Equatable, Hashable {
        let id: String
        let label: String
    }

    static let actKinds: [Choice] = [
        Choice(id: "adr_written", label: "написан ADR"),
        Choice(id: "data_model_decision", label: "решение по модели данных"),
        Choice(id: "security_review", label: "ревью безопасности"),
        Choice(id: "roadmap_update", label: "правка роадмапа"),
        Choice(id: "budget_decision", label: "решение по бюджету"),
        Choice(id: "hiring_step", label: "шаг по найму"),
        Choice(id: "report_to_management", label: "отчёт руководству"),
        Choice(id: "partner_talk", label: "разговор с партнёром"),
        Choice(id: "code_review", label: "code review"),
        Choice(id: "ci_change", label: "правка CI"),
        Choice(id: "wrote_from_scratch", label: "написано с нуля"),
    ]

    static func actKindLabel(_ kind: String) -> String {
        actKinds.first { $0.id == kind }?.label ?? kind
    }

    static func targetShareLine(_ slice: RoleDaySliceDTO) -> String? {
        guard let target = slice.targetSharePct else { return nil }
        return "цель \(target)% — \(targetHypothesis)"
    }

    static func actsSummary(_ day: RoleDayDTO) -> String {
        let withActs = day.roles.filter { $0.actCount > 0 }
        if withActs.isEmpty { return noActsText }
        return withActs.map { "\($0.title) — \(actsCount($0.actCount))" }.joined(separator: ", ")
    }

    static func actLine(_ act: RoleActDTO) -> String {
        "\(actKindLabel(act.actKind)): \(act.title)"
    }

    static func fromPlanLine(_ act: RoleActDTO) -> String? {
        act.planItemText.map { "из плана: \($0)" }
    }

    /// The rule and the application behind an automatic block; nil for a record typed by a person.
    static func markupSource(_ block: RoleTimeBlockDTO) -> String? {
        guard block.isAutomatic else { return nil }
        let parts = [block.appName, block.ruleSummary].compactMap { part -> String? in
            guard let part, !part.isEmpty else { return nil }
            return part
        }
        if parts.isEmpty { return automaticMark }
        return "\(automaticMark): \(parts.joined(separator: " · "))"
    }

    static func unassignedLine(_ day: RoleDayDTO) -> String? {
        guard let slice = day.roles.first(where: { $0.roleCode == unassignedCode }), slice.minutes > 0 else {
            return nil
        }
        return "не отнесено: \(slice.sharePct)%"
    }

    static func blockLine(_ block: RoleTimeBlockDTO) -> String {
        var line = "\(minutes(block.minutes)) · \(block.roleCode)"
        if let note = block.note, !note.isEmpty { line += " · \(note)" }
        if block.isManual { line += " · \(manualMark)" }
        if block.confidence == "confirmed" { line += " · \(confirmedMark)" }
        return line
    }

    static func canConfirm(_ block: RoleTimeBlockDTO) -> Bool {
        block.isAutomatic && block.confidence != "confirmed"
    }

    // MARK: Summary

    enum Period: String, CaseIterable, Identifiable, Codable {
        case week, month, quarter

        var id: String { rawValue }

        var label: String {
            switch self {
            case .week: return "Неделя"
            case .month: return "Месяц"
            case .quarter: return "Квартал"
            }
        }

        var days: Int {
            switch self {
            case .week: return 7
            case .month: return 30
            case .quarter: return 90
            }
        }
    }

    /// `days` calendar days ending on `lastDay` (`yyyy-MM-dd`), inclusive. The bounds are server days:
    /// the day runs from 04:00, so the phone's calendar is not asked.
    static func range(endingOn lastDay: String, days: Int) -> (from: String, to: String)? {
        guard let end = dayFormatter.date(from: lastDay),
              let start = utcCalendar.date(byAdding: .day, value: -(days - 1), to: end)
        else { return nil }
        return (dayFormatter.string(from: start), lastDay)
    }

    static func range(endingOn lastDay: String, period: Period) -> (from: String, to: String)? {
        range(endingOn: lastDay, days: period.days)
    }

    private static let utcCalendar: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0) ?? .gmt
        return calendar
    }()

    private static let dayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.calendar = utcCalendar
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()

    static func workingRoles(_ summary: RoleSummaryDTO) -> [RoleSummarySliceDTO] {
        summary.roles.filter { $0.roleCode != unassignedCode }
    }

    static func deltaText(_ slice: RoleSummarySliceDTO) -> String? {
        guard let delta = slice.deltaPct else { return nil }
        return "\(delta > 0 ? "+" : "")\(delta) п.п."
    }

    static func targetText(_ slice: RoleSummarySliceDTO) -> String {
        slice.targetSharePct.map { "\($0)%" } ?? "—"
    }

    static func summaryRowLine(_ slice: RoleSummarySliceDTO) -> String {
        var line = "\(summaryMinutes(slice.minutes)) · \(slice.sharePct)% · цель \(targetText(slice))"
        if let delta = deltaText(slice) { line += " · \(delta)" }
        return line
    }

    /// Acts of a role by kind, `kind × n`, kinds in alphabetical order.
    static func actsText(_ slice: RoleSummarySliceDTO) -> String {
        slice.actCounts.sorted { $0.key < $1.key }.map { "\($0.key) × \($0.value)" }.joined(separator: ", ")
    }

    static func unassignedNote(_ summary: RoleSummaryDTO) -> String {
        if !summary.rulesLag {
            return "не отнесено \(summary.unassignedSharePct)% минут периода; "
                + "за скользящие 30 дней — \(summary.windowUnassignedSharePct)% "
                + "при пороге \(summary.lagThresholdPct)%"
        }
        return "правила разметки отстали: за скользящие 30 дней не отнесено "
            + "\(summary.windowUnassignedSharePct)% минут при пороге \(summary.lagThresholdPct)%. "
            + "По ADR-0020 автоматику пора выключать в пользу ручного ввода — чинить правила полдня в неделю дороже"
    }

    // MARK: Rules

    static let sources: [Choice] = [
        Choice(id: "app_usage", label: "Окна приложений"),
        Choice(id: "git", label: "Коммиты"),
        Choice(id: "clickup", label: "ClickUp"),
        Choice(id: "plan", label: "План дня"),
        Choice(id: "manual", label: "Ручной ввод"),
    ]

    static let matchers: [Choice] = [
        Choice(id: "commit_prefix", label: "Начало сообщения коммита"),
        Choice(id: "window_title_regex", label: "Заголовок окна (регулярка)"),
        Choice(id: "bundle_id", label: "Bundle id приложения"),
        Choice(id: "repo_path_glob", label: "Путь репозитория (glob)"),
        Choice(id: "clickup_list", label: "Список ClickUp"),
        Choice(id: "clickup_tag", label: "Тег ClickUp"),
        Choice(id: "plan_section", label: "Секция плана"),
    ]

    static func sourceLabel(_ id: String) -> String {
        sources.first { $0.id == id }?.label ?? id
    }

    static func matcherLabel(_ id: String) -> String {
        matchers.first { $0.id == id }?.label ?? id
    }

    static func ruleLine(_ rule: RoleRuleDTO) -> String {
        "\(rule.priority) · \(rule.pattern)"
    }

    static func ruleTarget(_ rule: RoleRuleDTO) -> String {
        "\(rule.source) → \(rule.roleCode)\(rule.isActive ? "" : " · выключено")"
    }

    static func dryRunSummary(_ run: RoleRuleDryRunDTO) -> String {
        if run.scannedRows == 0 { return nothingToScan }
        return "Зацепило интервалов: \(run.matchedTimeBlocks), актов: \(run.matchedActs) "
            + "из \(run.scannedRows) строк за \(run.dateFrom) — \(run.dateTo)."
    }

    static func takenFromLines(_ run: RoleRuleDryRunDTO, rules: [RoleRuleDTO]) -> [String] {
        var lines = run.takenFrom.sorted { $0.key < $1.key }.map { id, count -> String in
            let rule = rules.first { String($0.id) == id }
            let name = rule.map { "«\($0.pattern)»" } ?? "правило \(id)"
            return "Отбирает у \(name): \(count)"
        }
        if run.takenFromNobody > 0 { lines.append("Ничьих совпадений: \(run.takenFromNobody)") }
        return lines
    }

    static func protectedLine(_ result: RoleReclassifiedDTO) -> String {
        "Пересчитано строк: \(result.scannedRows), изменено интервалов: \(result.changedTimeBlocks), "
            + "актов: \(result.changedActs). Подтверждённых вами записей не тронуто: \(result.protected)."
    }

    /// Shares that moved: «Роль: 40% → 55%».
    static func reclassifyLines(_ result: RoleReclassifiedDTO, roles: [RoleDTO]) -> [String] {
        let before = Dictionary(result.before.map { ($0.roleId, $0.sharePct) }, uniquingKeysWith: { first, _ in first })
        let after = Dictionary(result.after.map { ($0.roleId, $0.sharePct) }, uniquingKeysWith: { first, _ in first })
        let ids = Set(before.keys).union(after.keys).sorted()
        return ids.compactMap { id in
            let was = before[id] ?? 0
            let now = after[id] ?? 0
            guard was != now else { return nil }
            let title = roles.first { $0.id == id }?.title ?? "роль \(id)"
            return "\(title): \(was)% → \(now)%"
        }
    }
}
