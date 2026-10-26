// [review:need-review] PHASE-01/212
// summary: chat bubbles — a stored message (user, assistant with status note, retrievals and plan card, system note) and the live bubble of the running turn with what the model is busy with
import SwiftUI

private func renderedText(_ source: String) -> AttributedString {
    let options = AttributedString.MarkdownParsingOptions(
        interpretedSyntax: .inlineOnlyPreservingWhitespace
    )
    return (try? AttributedString(markdown: source, options: options)) ?? AttributedString(source)
}

private struct Bubble: View {
    enum Side {
        case person
        case model
    }

    let side: Side
    let text: String

    var body: some View {
        HStack {
            if side == .person { Spacer(minLength: DS.Spacing.xxl) }
            Text(renderedText(text))
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.textPrimary)
                .textSelection(.enabled)
                .padding(DS.Spacing.md)
                .background(side == .person ? DS.Palette.lime.opacity(0.18) : DS.Palette.card)
                .clipShape(RoundedRectangle(cornerRadius: DS.Radius.card, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: DS.Radius.card, style: .continuous)
                        .stroke(side == .person ? DS.Palette.lime.opacity(0.4) : DS.Palette.cardStroke, lineWidth: 1)
                )
            if side == .model { Spacer(minLength: DS.Spacing.xxl) }
        }
    }
}

/// One stored message.
struct ChatMessageRow: View {
    let message: ChatMessageDTO
    @ObservedObject var viewModel: ChatViewModel

    var body: some View {
        switch message.role {
        case ChatMessageDTO.userRole:
            Bubble(side: .person, text: message.content)
        case ChatMessageDTO.systemNoteRole:
            Text(message.content)
                .font(DS.Typography.caption)
                .foregroundStyle(DS.Palette.textSecondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: .infinity)
        default:
            assistant
        }
    }

    private var assistant: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.sm) {
            if !message.content.isEmpty {
                Bubble(side: .model, text: message.content)
            }
            if let note = statusNote {
                Text(note)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.warning)
            }
            if let retrievals = message.retrievals, !retrievals.isEmpty {
                Text("Читал данные: " + retrievals.map { "\($0.queryName) (\($0.rowCount))" }.joined(separator: ", "))
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
            }
            if let planID = message.planId, let plan = viewModel.plans[planID] {
                ChatPlanCardView(plan: plan, viewModel: viewModel)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// Why this answer is not whole: the failure code of a failed turn, or the status.
    private var statusNote: String? {
        if message.status == ChatMessageDTO.failedStatus {
            return message.errorCode.flatMap { ChatViewModel.turnErrorText[$0] } ?? ChatViewModel.turnFailedFallback
        }
        return ChatViewModel.messageStatusNote[message.status]
    }
}

/// The turn in flight: the question just sent and the answer as it arrives.
struct ChatTurnView: View {
    let turn: ChatViewModel.Turn

    var body: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.sm) {
            Bubble(side: .person, text: turn.question)
            if !turn.text.isEmpty {
                Bubble(side: .model, text: turn.text)
            }
            if let failure = turn.failure {
                Text(failure)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.danger)
            } else if !turn.isStoredCopyMissing {
                HStack(spacing: DS.Spacing.sm) {
                    ProgressView()
                        .tint(DS.Palette.lime)
                    Text(progressLabel)
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var progressLabel: String {
        switch turn.activity {
        case .waiting:
            return turn.retrievalCount > 0 ? "Смотрит данные (\(turn.retrievalCount))…" : "Ждёт ответа…"
        case .thinking:
            return "Думает…"
        case .writing:
            return "Пишет ответ…"
        case .acting(let tool):
            return tool.map { "Работает: \($0)…" } ?? "Работает…"
        }
    }
}
