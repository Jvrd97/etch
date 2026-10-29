// [review:need-review] PHASE-03/240, PHASE-03/258
// summary: the server's day rule (zone + day-start hour, cut by wall clock, not by hours of absolute time), form limits on name and dose; words and values of the Supplements screen — dose and planned time as text, the form draft with its checks (name, positive dose with a comma or a point, unit, optional time), the day of a press by the server's rule (the day turns at 04:00), and the words for what the server refuses
import Foundation

/// What the person fills in to add a supplement. The planned time is optional.
struct SupplementDraft: Equatable {
    static let defaultUnit = "мг"
    static let defaultHour = 8

    var name = ""
    var doseText = ""
    var unit = SupplementDraft.defaultUnit
    var hasTime = false
    var hour = SupplementDraft.defaultHour
    var minute = 0
}

/// The day rule the server holds: its zone and the hour its day starts at. Until the server says,
/// the default (phone zone, 04:00) stands in.
struct ServerDayRule: Codable, Equatable {
    static let defaultDayStartHour = 4
    static let phone = ServerDayRule(timeZoneID: TimeZone.current.identifier, dayStartHour: defaultDayStartHour)

    var timeZoneID: String
    var dayStartHour: Int

    var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: timeZoneID) ?? .current
        return calendar
    }
}

enum SupplementsFormat {
    static let maxNameLength = 100
    static let maxUnitLength = 20
    static let maxDose = 1_000_000.0
    static let unitTooLongMessage = "Единица длиннее \(maxUnitLength) символов."
    static let nameTooLongMessage = "Название длиннее \(maxNameLength) символов."
    static let minuteStep = 5
    static let notConfiguredMessage = "Укажите адрес сервера в Settings"
    static let addNeedsNetworkMessage = "Добавить добавку можно только с сетью: на сервере она получает номер."
    static let nameMissingMessage = "Введите название."
    static let doseInvalidMessage = "Доза — число больше нуля, не больше миллиона."
    static let unitMissingMessage = "Введите единицу: мг, мкг, капсула."
    static let markFailedMessage = "Отметку записать не удалось."
    static let addFailedMessage = "Добавку записать не удалось."

    private static let ru = Locale(identifier: "ru_RU")

    // MARK: Text

    /// "500 мг", "0,5 г".
    static func doseText(_ supplement: SupplementDTO) -> String {
        let number = supplement.dose.formatted(
            .number.locale(ru).grouping(.never).precision(.fractionLength(0...3))
        )
        return "\(number) \(supplement.unit)"
    }

    /// "08:30" out of the server's "08:30:00"; nil when there is no time or it cannot be read.
    static func timeText(_ wire: String?) -> String? {
        guard let wire, let (hour, minute) = parts(of: wire) else { return nil }
        return twoDigits(hour) + ":" + twoDigits(minute)
    }

    /// The line under the name: dose, and the planned time when there is one.
    static func detail(_ supplement: SupplementDTO) -> String {
        [doseText(supplement), timeText(supplement.intakeTime)].compactMap { $0 }.joined(separator: " · ")
    }

    /// "Принял: Магний" — what the list of waiting writes says.
    static func queueLabel(_ supplement: SupplementDTO) -> String {
        "Принял: \(supplement.name)"
    }

    // MARK: Draft

    /// The dose as typed: a comma or a point, spaces around. Nil unless it is a number above zero.
    static func parseDose(_ text: String) -> Double? {
        let normalized = text.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: ",", with: ".")
        guard let dose = Double(normalized), dose.isFinite, dose > 0, dose <= maxDose else { return nil }
        return dose
    }

    /// The create body, or the first thing that is wrong with the draft.
    static func payload(from draft: SupplementDraft) -> Result<SupplementCreateDTO, ValidationError> {
        let name = draft.name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return .failure(.init(message: nameMissingMessage)) }
        guard name.count <= maxNameLength else { return .failure(.init(message: nameTooLongMessage)) }
        guard let dose = parseDose(draft.doseText) else { return .failure(.init(message: doseInvalidMessage)) }
        let unit = draft.unit.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !unit.isEmpty else { return .failure(.init(message: unitMissingMessage)) }
        guard unit.count <= maxUnitLength else { return .failure(.init(message: unitTooLongMessage)) }
        let time = draft.hasTime ? twoDigits(draft.hour) + ":" + twoDigits(draft.minute) + ":00" : nil
        return .success(SupplementCreateDTO(name: name, dose: dose, unit: unit, intakeTime: time))
    }

    struct ValidationError: Error, Equatable {
        let message: String
    }

    // MARK: Day

    /// `yyyy-MM-dd` of the day a moment belongs to by the server's rule: the wall clock of the server's zone,
    /// and before the day-start hour it is still the day before (a calendar day, so a clock change does not shift it).
    static func logicalDay(of moment: Date, rule: ServerDayRule) -> String {
        let calendar = rule.calendar
        var day = calendar.startOfDay(for: moment)
        if calendar.component(.hour, from: moment) < rule.dayStartHour {
            day = calendar.date(byAdding: .day, value: -1, to: day) ?? day
        }
        let parts = calendar.dateComponents([.year, .month, .day], from: day)
        return String(format: "%04d-%02d-%02d", parts.year ?? 0, parts.month ?? 0, parts.day ?? 0)
    }

    /// The next moment the server's day turns, for the timer that re-reads the screen.
    static func nextDayTurn(after moment: Date, rule: ServerDayRule) -> Date? {
        rule.calendar.nextDate(
            after: moment, matching: DateComponents(hour: rule.dayStartHour, minute: 0, second: 0),
            matchingPolicy: .nextTime
        )
    }

    // MARK: Errors

    static func message(forMark error: APIClientError) -> String {
        switch error {
        case .unexpectedStatus(409): return "Сервер не принял отметку (409): добавка в архиве."
        case .unexpectedStatus(404): return "Сервер не нашёл эту добавку (404): её удалили."
        default: return error.userMessage
        }
    }

    // MARK: Private

    private static func parts(of wire: String) -> (Int, Int)? {
        let pieces = wire.split(separator: ":")
        guard pieces.count >= 2, let hour = Int(pieces[0]), let minute = Int(pieces[1]),
              (0..<24).contains(hour), (0..<60).contains(minute)
        else { return nil }
        return (hour, minute)
    }

    private static func twoDigits(_ value: Int) -> String {
        String(format: "%02d", value)
    }
}
