// [review:need-review] PHASE-03/240
// summary: wire types of the supplements endpoints — a list item with taken_today (the create answer has none: false), the create body with the planned time as HH:mm:ss, the intake request that carries the day only as a clock check, and the intake answer
import Foundation

/// A supplement as the server lists it. `intakeTime` is `HH:mm:ss` (a time of day, not a date).
struct SupplementDTO: Codable, Equatable, Identifiable {
    let id: Int
    let name: String
    let dose: Double
    let unit: String
    let intakeTime: String?
    let isActive: Bool
    /// A mark «принял» exists for the server's current logical day.
    var takenToday: Bool
}

extension SupplementDTO {
    /// The create answer has no `taken_today`: a supplement just added was not taken yet.
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.init(
            id: try container.decode(Int.self, forKey: .id),
            name: try container.decode(String.self, forKey: .name),
            dose: try container.decode(Double.self, forKey: .dose),
            unit: try container.decode(String.self, forKey: .unit),
            intakeTime: try container.decodeIfPresent(String.self, forKey: .intakeTime),
            isActive: try container.decode(Bool.self, forKey: .isActive),
            takenToday: try container.decodeIfPresent(Bool.self, forKey: .takenToday) ?? false
        )
    }
}

struct SupplementCreateDTO: Encodable, Equatable {
    let name: String
    let dose: Double
    let unit: String
    let intakeTime: String?
}

/// `intakeDate` is the day by the phone's clock. It is not the address of the write: a day that differs
/// from the server's is refused (409). A direct press leaves it out and the server decides.
struct SupplementIntakeRequestDTO: Encodable, Equatable {
    let intakeDate: String?
}

struct SupplementIntakeDTO: Codable, Equatable {
    let id: Int
    let supplementId: Int
    let intakeDate: String
}
