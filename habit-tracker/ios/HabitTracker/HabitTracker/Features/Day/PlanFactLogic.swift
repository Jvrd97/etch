// [review:need-review] PHASE-01/211
// summary: pure rules of a category-linked plan line (port of the web lib/plan-facts.ts) — parse a typed value (comma decimals, "ч:мм" durations), the mark a write should carry (done once the target is reached, unmark when a correction/delete takes the line back below it), Russian progress/value/link-state texts
import Foundation

enum PlanFactLogic {
    static let markDone = "done"
    static let markUnmark = "unmark"
    /// Unit a duration travels in; the card shows h:mm and sends whole seconds.
    static let durationUnit = "s"

    private static let secondsPerMinute = 60
    private static let secondsPerHour = 3600
    private static let minutesPerHour = 60
    private static let trueTexts: Set<String> = ["true", "1", "yes"]

    // MARK: Typed input

    /// A typed value as the API wants it: a number, or whole seconds for a duration.
    /// Nil when empty or unreadable. A comma is a decimal point ("3,5").
    static func parseInput(fieldType: String, _ text: String) -> Double? {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return nil }
        if fieldType == "duration" {
            return parseDuration(trimmed)
        }
        guard let number = Double(trimmed.replacingOccurrences(of: ",", with: ".")),
              number.isFinite else { return nil }
        return number
    }

    /// "1:20" is hours:minutes (minutes 0-59), a bare "45" is minutes.
    private static func parseDuration(_ text: String) -> Double? {
        let isDigits: (String) -> Bool = { !$0.isEmpty && $0.allSatisfy { $0.isASCII && $0.isNumber } }
        if text.contains(":") {
            let parts = text.split(separator: ":", omittingEmptySubsequences: false).map(String.init)
            guard parts.count == 2, isDigits(parts[0]), isDigits(parts[1]),
                  let hours = Int(parts[0]), let minutes = Int(parts[1]),
                  minutes < minutesPerHour else { return nil }
            return Double(hours * secondsPerHour + minutes * secondsPerMinute)
        }
        guard isDigits(text), let minutes = Int(text) else { return nil }
        return Double(minutes * secondsPerMinute)
    }

    /// Seconds as the editable "H:MM" string.
    static func inputText(seconds: Double) -> String {
        let total = max(0, Int(seconds.rounded()))
        let minutes = (total % secondsPerHour) / secondsPerMinute
        return "\(total / secondsPerHour):" + (minutes < 10 ? "0\(minutes)" : "\(minutes)")
    }

    static func isTrue(_ raw: String?) -> Bool {
        guard let raw else { return false }
        return trueTexts.contains(raw.trimmingCharacters(in: .whitespaces).lowercased())
    }

    // MARK: Marks

    /// The stored value of the linked field of every entry but `entryID`.
    private static func linkedRaws(_ facts: PlanItemFactsDTO, excluding entryID: Int? = nil) -> [String?] {
        facts.entries
            .filter { $0.entryId != entryID }
            .map { entry in entry.values.first { $0.fieldId == facts.link.fieldId }?.value }
    }

    private static func reaches(_ facts: PlanItemFactsDTO, total: Double) -> Bool {
        guard let target = facts.link.targetValue else { return true }
        return total >= target
    }

    /// The stored values do the line: a "было", or a total that reaches the target.
    private static func rawsDo(_ facts: PlanItemFactsDTO, _ raws: [String?]) -> Bool {
        if facts.link.fieldType == "boolean" {
            return raws.contains { isTrue($0) }
        }
        let total = raws.reduce(0.0) { $0 + (Double($1 ?? "") ?? 0) }
        return !raws.isEmpty && reaches(facts, total: total)
    }

    /// `unmark` when the facts did the line before the write and `after` no longer does.
    /// Facts that fell short never backed "сделано": a mark on such a line is the
    /// person's own call, and a correction or a delete leaves it be.
    private static func markOfLoss(_ facts: PlanItemFactsDTO, after: [String?]) -> String? {
        rawsDo(facts, linkedRaws(facts)) && !rawsDo(facts, after) ? markUnmark : nil
    }

    /// `done` once the new fact completes the line, else none: 100 of 300 is recorded
    /// as 100 and the line is not declared done for the person.
    static func markAfterRecord(_ facts: PlanItemFactsDTO, value: PlanFactValue) -> String? {
        switch value {
        case .flag(let flag):
            return flag ? markDone : nil
        case .number(let number):
            return reaches(facts, total: (facts.total ?? 0) + number) ? markDone : nil
        }
    }

    /// The mark after correcting `entryID` to `value`: its old value counted out.
    static func markAfterCorrect(_ facts: PlanItemFactsDTO, entryID: Int, value: PlanFactValue) -> String? {
        let rest = linkedRaws(facts, excluding: entryID)
        switch value {
        case .flag(let flag):
            return flag ? markDone : markOfLoss(facts, after: rest)
        case .number(let number):
            let after = rest + [String(number)]
            return rawsDo(facts, after) ? markDone : markOfLoss(facts, after: after)
        }
    }

    /// `unmark` once the line was done and is no longer without `entryID`.
    static func markAfterRemove(_ facts: PlanItemFactsDTO, entryID: Int) -> String? {
        markOfLoss(facts, after: linkedRaws(facts, excluding: entryID))
    }

    // MARK: Texts

    /// "300", "3.5": no trailing ".0".
    static func numberText(_ number: Double) -> String {
        number == number.rounded() && abs(number) < 1e15 ? String(Int(number)) : String(number)
    }

    /// Whole seconds as "1 ч 20 мин", "45 мин", "2 ч".
    static func durationText(seconds: Double) -> String {
        let total = max(0, Int(seconds.rounded()))
        let hours = total / secondsPerHour
        let minutes = (total % secondsPerHour) / secondsPerMinute
        if hours == 0 { return "\(minutes) мин" }
        if minutes == 0 { return "\(hours) ч" }
        return "\(hours) ч \(minutes) мин"
    }

    /// A stored value worded for the card.
    static func valueText(fieldType: String?, raw: String?, unit: String?) -> String {
        guard let raw, !raw.isEmpty else { return "—" }
        if fieldType == "boolean" { return isTrue(raw) ? "было" : "не было" }
        if fieldType == "duration" {
            return Double(raw).map { durationText(seconds: $0) } ?? raw
        }
        guard let unit, !unit.isEmpty else { return raw }
        return "\(raw) \(unit)"
    }

    private static func bareAmount(_ facts: PlanItemFactsDTO, _ amount: Double) -> String {
        facts.link.fieldType == "duration" ? durationText(seconds: amount) : numberText(amount)
    }

    private static func amountText(_ facts: PlanItemFactsDTO, _ amount: Double) -> String {
        let bare = bareAmount(facts, amount)
        guard let unit = facts.link.unit, !unit.isEmpty, facts.link.fieldType != "duration" else { return bare }
        return "\(bare) \(unit)"
    }

    /// Where the line stands, in one sentence: the target and the fact kept apart.
    static func progressText(_ facts: PlanItemFactsDTO) -> String {
        let target = facts.link.targetValue
        if facts.progress == "none" {
            return target.map { "Цель \(amountText(facts, $0)), пока не записано" } ?? "Пока не записано"
        }
        if facts.link.fieldType == "boolean" {
            return facts.done ? "Было" : "Записано: не было"
        }
        let total = facts.total ?? 0
        guard let target else { return "Записано \(amountText(facts, total))" }
        return "Сделано \(bareAmount(facts, total)) из \(amountText(facts, target))"
    }

    /// Why a link cannot take a fact; nil when it can.
    static func linkStateText(_ state: String) -> String? {
        switch state {
        case "ok": return nil
        case "category_missing": return "Категории больше нет — запись из плана невозможна"
        case "category_archived": return "Категория в архиве — запись из плана невозможна"
        case "checklist_category": return "Чек-лист ведёт одну запись на день — отмечайте его на Today"
        case "field_missing": return "Поле удалено из категории — выберите другое поле"
        case "field_not_in_category": return "Поле не из этой категории — выберите поле заново"
        case "field_unsupported": return "В это поле из плана не записать — выберите числовое поле"
        case "target_needs_number": return "Цель стоит на галочке — уберите цель или смените поле"
        default: return "Связь с категорией сломана (\(state))"
        }
    }
}
