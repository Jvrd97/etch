// [review:need-review] PHASE-03/305
// summary: wire type of the «Состояние сегодня» read — only `scores.health` of GET /dashboard/summary (value 0..100 or null under three days of data, label good|fair|poor, days it was counted on); the rest of the summary is ignored by the decoder
import Foundation

/// The server's index of the person's health. The phone never computes it: `value` is `nil` when the server had too little data.
struct HealthScoreDTO: Codable, Equatable {
    let value: Int?
    /// `good`, `fair` or `poor`; a word the app does not know yet stays a word and shows no label.
    let label: String?
    let basisDays: Int
}

struct HealthStateResponseDTO: Codable, Equatable {
    struct Scores: Codable, Equatable {
        let health: HealthScoreDTO?
    }

    let scores: Scores
}
