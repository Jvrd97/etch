// [review:need-review] PHASE-01/210
// summary: wording and local folding of quick-mark state — the caption a button shows, the state a tap's own answer or an offline press folds into the list, the signed amount of one set of the day and its clock time
import Foundation

enum QuickMarkWording {
    static let plannedBadge = "в плане"
    static let ticked = "Отмечено"
    static let unticked = "Снято"

    /// The number under a button's label, '' when it has none. A zero is a claim about the day
    /// ("я выпил ноль"), and a button nobody pressed has not made it.
    static func formatTotal(_ total: Double?) -> String {
        guard let total else { return "" }
        let rounded = (total * 1_000).rounded() / 1_000
        if rounded == rounded.rounded() {
            return String(Int(rounded))
        }
        return String(rounded)
    }

    static func heading(forKind kind: String) -> String {
        kind == QuickMarkDTO.kindCheck ? "Отметки за сегодня" : "Подходы за сегодня"
    }

    /// «12:30» of an ISO 8601 moment, in the device's time zone; '' when it does not parse.
    static func clockTime(_ iso: String, timeZone: TimeZone = .current) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let plain = ISO8601DateFormatter()
        guard let date = formatter.date(from: iso) ?? plain.date(from: iso) else { return "" }
        let output = DateFormatter()
        output.locale = Locale(identifier: "en_US_POSIX")
        output.timeZone = timeZone
        output.dateFormat = "HH:mm"
        return output.string(from: date)
    }
}

extension QuickMarkDTO {
    /// The total and its unit as the card prints them, '' for a tick or an untouched number.
    var caption: String {
        let total = QuickMarkWording.formatTotal(todayTotal)
        guard !total.isEmpty else { return "" }
        guard let unitLabel, !unitLabel.isEmpty else { return total }
        return "\(total) \(unitLabel)"
    }

    /// What the button says it will do for a reader who is not looking at glyphs.
    var accessibilityName: String {
        let named = planned ? "\(label) — \(QuickMarkWording.plannedBadge)" : label
        return done ? "\(named) — отмечено" : named
    }

    /// The state a tap's own answer leaves the button in.
    func applying(_ event: QuickMarkEventDTO) -> QuickMarkDTO {
        var copy = self
        copy.todayTotal = event.todayTotal
        copy.done = event.done
        return copy
    }

    func applying(_ undone: QuickMarkUndoDTO) -> QuickMarkDTO {
        var copy = self
        copy.todayTotal = undone.todayTotal
        copy.done = undone.done
        return copy
    }

    /// The state a press the server has not seen yet leaves the button in, so the press is visible
    /// at once. The server's answer replaces it as soon as the press is delivered.
    func afterOfflineTap() -> QuickMarkDTO {
        var copy = self
        let amount = step ?? 1
        switch kind {
        case Self.kindCheck:
            copy.done = true
        case Self.kindSetValue:
            copy.todayTotal = amount
            copy.done = amount != 0
        default:
            let total = (todayTotal ?? 0) + amount
            copy.todayTotal = total
            copy.done = total != 0
        }
        return copy
    }
}

extension QuickMarkDayEventDTO {
    /// What one set was worth, as the row prints it. A number is signed ("+25", "-400") because the
    /// row is a move of the day's total; a tick says which way it moved the box.
    var amountText: String {
        if let boolValue {
            return boolValue ? QuickMarkWording.ticked : QuickMarkWording.unticked
        }
        guard let delta else { return "" }
        let figure = QuickMarkWording.formatTotal(delta)
        let signed = delta > 0 ? "+\(figure)" : figure
        guard let unitLabel, !unitLabel.isEmpty else { return signed }
        return "\(signed) \(unitLabel)"
    }

    var isTakenBack: Bool { undoneAt != nil }
}
