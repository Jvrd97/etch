// [review:need-review] PHASE-01/212
// summary: chat DTOs — conversation list item and detail, stored message, proposed plan with its operations (metric, check, journal, day plan) and the apply selection, plus the SSE events of one turn
import Foundation

// MARK: - Conversations and messages

/// Row of `GET /chat/conversations`.
struct ChatConversationDTO: Codable, Identifiable, Equatable {
    let id: Int
    let title: String?
    let startedOn: String
    let kind: String
    let lastMessageAt: String?
    let createdAt: String
    let usage: ChatUsageDTO

    /// Number of stored messages, shown next to the row in history.
    var messageCount: Int { usage.messageCount }
}

struct ChatUsageDTO: Codable, Equatable {
    let messageCount: Int
}

/// `GET /chat/conversations/{id}`: the conversation with its messages in `seq` order.
struct ChatConversationDetailDTO: Codable, Equatable {
    let id: Int
    let messages: [ChatMessageDTO]
}

struct ChatMessageDTO: Codable, Identifiable, Equatable {
    /// Server-side `role` values.
    static let userRole = "user"
    static let assistantRole = "assistant"
    static let systemNoteRole = "system_note"
    /// Server-side `status` values.
    static let streamingStatus = "streaming"
    static let completeStatus = "complete"
    static let interruptedStatus = "interrupted"
    static let failedStatus = "failed"

    let id: Int
    let seq: Int
    let role: String
    let content: String
    let status: String
    let errorCode: String?
    let createdAt: String
    /// The plan this message proposed, if any.
    let planId: Int?
    /// What the model pulled while answering: name and size, never the data.
    let retrievals: [ChatRetrievalDTO]?

    var isStreaming: Bool { status == Self.streamingStatus }
}

struct ChatRetrievalDTO: Codable, Equatable {
    let queryName: String
    let rowCount: Int
}

struct ChatMessageCreateDTO: Encodable {
    let content: String
}

struct ChatResetDTO: Decodable, Equatable {
    let reset: Int
}

// MARK: - Plans

/// A plan the chat proposed. The operations are decoded and sent back verbatim:
/// the server narrows the selection to what it stored, and a changed field is a 400.
struct ChatPlanDTO: Decodable, Identifiable, Equatable {
    /// Server-side `status` values.
    static let proposedStatus = "proposed"
    static let appliedStatus = "applied"
    static let dismissedStatus = "dismissed"
    static let staleStatus = "stale"

    let id: Int
    let messageId: Int
    let entryDate: String
    let status: String
    let plan: ChatPlanBodyDTO
    let operationCount: Int
}

struct ChatPlanBodyDTO: Decodable, Equatable {
    let entryDate: String
    let metrics: [ChatPlanMetricDTO]
    let checklist: [ChatPlanCheckDTO]
    let journal: ChatPlanJournalDTO?
    let dayPlan: ChatPlanDayPlanDTO?
}

struct ChatPlanMetricDTO: Codable, Equatable {
    let categoryId: Int
    let fieldId: Int
    let value: Double
    let sourceText: String
    let uncertain: Bool
    let implausible: Bool
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

struct ChatPlanCheckDTO: Codable, Equatable {
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
}

struct ChatPlanJournalDTO: Codable, Equatable {
    let title: String?
    let content: String
    let mood: String?
    let tags: String?
    /// `append` or `create`; the chat can never say `replace`.
    let mode: String
}

/// The day plan is shown, never edited, and written whole: the apply sends a flag.
struct ChatPlanDayPlanDTO: Decodable, Equatable {
    /// `draft_day_plan` fills an empty day, `rewrite_day_plan` replaces a full one.
    static let rewriteOperation = "rewrite_day_plan"

    struct Section: Decodable, Equatable {
        struct Item: Decodable, Equatable {
            let text: String
        }

        let title: String
        let items: [Item]
    }

    let op: String
    let title: String?
    let sections: [Section]

    var isRewrite: Bool { op == Self.rewriteOperation }
    var itemCount: Int { sections.reduce(0) { $0 + $1.items.count } }
}

/// Body of `POST /chat/plans/{id}/apply`: the subset of the stored plan left ticked.
struct ChatPlanSelectionDTO: Encodable, Equatable {
    let metrics: [ChatPlanMetricDTO]
    let checklist: [ChatPlanCheckDTO]
    let journal: ChatPlanJournalDTO?
    let dayPlan: Bool
}

struct ChatPlanApplyResultDTO: Decodable, Equatable {
    let plan: ChatPlanDTO
    let appliedOperations: Int
}

// MARK: - Stream events

/// One event of a chat turn, as the server names it. Unknown frames map to `nil`.
enum ChatStreamEvent: Equatable {
    case delta(String)
    case usage
    case thinking
    case writing
    case acting(tool: String?)
    case stepEnd
    case retrieval(queryName: String, rowCount: Int, refusal: String?)
    case stop(reason: String?)
    case done(messageID: Int, seq: Int, status: String)
    case error(code: String)

    init?(frame: SSEFrame) {
        guard
            let name = frame.event,
            let payload = Self.payload(of: frame)
        else { return nil }
        switch name {
        case "delta":
            guard let text = payload["text"] as? String, !text.isEmpty else { return nil }
            self = .delta(text)
        case "usage":
            self = .usage
        case "thinking":
            self = .thinking
        case "writing":
            self = .writing
        case "acting":
            self = .acting(tool: payload["tool"] as? String)
        case "step_end":
            self = .stepEnd
        case "retrieval":
            guard let queryName = payload["query_name"] as? String else { return nil }
            self = .retrieval(
                queryName: queryName,
                rowCount: payload["row_count"] as? Int ?? 0,
                refusal: payload["refusal"] as? String
            )
        case "stop":
            self = .stop(reason: payload["reason"] as? String)
        case "done":
            guard
                let messageID = payload["message_id"] as? Int,
                let seq = payload["seq"] as? Int,
                let status = payload["status"] as? String
            else { return nil }
            self = .done(messageID: messageID, seq: seq, status: status)
        case "error":
            guard let code = payload["code"] as? String, !code.isEmpty else { return nil }
            self = .error(code: code)
        default:
            return nil
        }
    }

    /// The JSON object of a frame. A half-written or non-object payload is not an
    /// error worth showing: the turn continues, and answer text never reaches a log.
    private static func payload(of frame: SSEFrame) -> [String: Any]? {
        guard
            let data = frame.data.data(using: .utf8),
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        return object
    }
}
