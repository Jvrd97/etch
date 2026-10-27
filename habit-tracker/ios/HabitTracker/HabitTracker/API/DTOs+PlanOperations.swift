// [review:need-review] PHASE-03/230, PHASE-03/250
// summary: the plan operations the day-summary draft and the chat plan share — a number to record, a checklist box to tick, the day's text with its append/create/replace mode; the server uses one schema for both, so the app decodes and echoes one type; flags the server leaves out are false, `existingEntryId` exists only in a draft; the `op` tag is written on the way out and never required on the way in (a stored chat journal has none)
import Foundation

/// One number a plan proposes to record. Resolved by `categoryId` and `fieldId` only; the server
/// revalidates both on apply. The apply request echoes the operation back unchanged, so every
/// field the server sends is kept here.
struct LogMetricOpDTO: Codable, Equatable {
    var op = "log_metric"
    let categoryId: Int
    let fieldId: Int
    let value: Double
    /// The wording the number was read from, shown next to its switch.
    let sourceText: String
    /// The model placed the number without confidence: it arrives switched off.
    let uncertain: Bool
    /// The number itself looks wrong (300 push-ups): it arrives switched off.
    let implausible: Bool
    /// Nobody said this number, the model derived it from a description (a meal).
    let estimated: Bool

    init(
        categoryId: Int, fieldId: Int, value: Double, sourceText: String,
        uncertain: Bool = false, implausible: Bool = false, estimated: Bool = false
    ) {
        self.categoryId = categoryId
        self.fieldId = fieldId
        self.value = value
        self.sourceText = sourceText
        self.uncertain = uncertain
        self.implausible = implausible
        self.estimated = estimated
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        categoryId = try container.decode(Int.self, forKey: .categoryId)
        fieldId = try container.decode(Int.self, forKey: .fieldId)
        value = try container.decode(Double.self, forKey: .value)
        sourceText = try container.decode(String.self, forKey: .sourceText)
        uncertain = try container.decodeIfPresent(Bool.self, forKey: .uncertain) ?? false
        implausible = try container.decodeIfPresent(Bool.self, forKey: .implausible) ?? false
        estimated = try container.decodeIfPresent(Bool.self, forKey: .estimated) ?? false
    }

    /// Rows the model was unsure about, or whose value looks wrong, arrive unticked.
    var isTickedByDefault: Bool { !uncertain && !implausible }
}

/// One checklist box a plan proposes to tick. There is no value on purpose: a plan can raise a box
/// and cannot lower one, because silence in a retelling is not "didn't do it".
struct CheckOpDTO: Codable, Equatable {
    var op = "check"
    let categoryId: Int
    let fieldId: Int
    let sourceText: String
    let uncertain: Bool

    init(categoryId: Int, fieldId: Int, sourceText: String, uncertain: Bool = false) {
        self.categoryId = categoryId
        self.fieldId = fieldId
        self.sourceText = sourceText
        self.uncertain = uncertain
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        categoryId = try container.decode(Int.self, forKey: .categoryId)
        fieldId = try container.decode(Int.self, forKey: .fieldId)
        sourceText = try container.decode(String.self, forKey: .sourceText)
        uncertain = try container.decodeIfPresent(Bool.self, forKey: .uncertain) ?? false
    }

    var isTickedByDefault: Bool { !uncertain }
}

/// The day written out as text, with what the server decided to do with it.
/// `existingEntryId` is context for the draft's preview and is never trusted by the apply; a
/// chat plan has none.
struct JournalOpDTO: Codable, Equatable {
    /// How the text meets what the day already holds. The server only proposes append or create;
    /// replace is chosen by the person, and only the day-summary screen offers it: the chat's
    /// server schema cannot say it.
    enum Mode: String, Codable, Equatable {
        case append
        case create
        case replace
    }

    var op = "write_journal"
    let title: String?
    let content: String
    let mood: String?
    let tags: String?
    var mode: Mode
    let existingEntryId: Int?

    init(
        title: String?, content: String, mood: String?, tags: String?, mode: Mode,
        existingEntryId: Int? = nil
    ) {
        self.title = title
        self.content = content
        self.mood = mood
        self.tags = tags
        self.mode = mode
        self.existingEntryId = existingEntryId
    }

    /// `op` is a tag the app writes when it echoes the operation back; a journal read from the chat's
    /// history may come without it, and a missing tag must not fail the whole message. A missing `mode`
    /// reads as the server's default, `append`: it adds to the day and overwrites nothing.
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        title = try container.decodeIfPresent(String.self, forKey: .title)
        content = try container.decode(String.self, forKey: .content)
        mood = try container.decodeIfPresent(String.self, forKey: .mood)
        tags = try container.decodeIfPresent(String.self, forKey: .tags)
        mode = try container.decodeIfPresent(Mode.self, forKey: .mode) ?? .append
        existingEntryId = try container.decodeIfPresent(Int.self, forKey: .existingEntryId)
    }
}
