// [review:need-review] PHASE-01/210, PHASE-03/225, PHASE-03/242
// summary: PHASE-03/242 — both targets of a card say "ждёт отправки: N" to VoiceOver while its presses wait in the queue
// summary: the quick-mark buttons of Today — a card per button (name and counter open the day's sets, the trailing plus or tick adds one), planned badge, lime when done, the undo chip of the last tap, the offline banner (queued presses are counted by the shared outbox strip of the screen)
import SwiftUI

/// The buttons as the server ordered them. A card splits into two targets: the name and counter open
/// the list of the day's sets, the plus (or tick) adds one — a tap that both added and opened would
/// add a set every time the reader only wanted to look.
struct QuickMarksSection: View {
    @ObservedObject var viewModel: QuickMarksViewModel
    let onOpen: (QuickMarkDTO) -> Void

    private let columns = [GridItem(.adaptive(minimum: 160), spacing: DS.Spacing.md)]

    var body: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.md) {
            if let offlineAsOf = viewModel.offlineAsOf {
                OfflineBanner(updatedAt: offlineAsOf)
            }
            if let message = viewModel.errorMessage {
                Text(message)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.danger)
                    .accessibilityIdentifier("quickMarks.error")
            }
            LazyVGrid(columns: columns, spacing: DS.Spacing.md) {
                ForEach(viewModel.marks) { mark in
                    QuickMarkCard(
                        mark: mark,
                        waitingCaption: viewModel.waitingCaption(of: mark.id),
                        onOpen: { onOpen(mark) },
                        onTap: { Task { await viewModel.tap(mark) } }
                    )
                }
            }
            if let caption = viewModel.undoCaption {
                Button(caption) {
                    Task { await viewModel.undoLast() }
                }
                .font(DS.Typography.caption)
                .foregroundStyle(DS.Palette.textSecondary)
                .padding(.vertical, DS.Spacing.sm)
                .padding(.horizontal, DS.Spacing.md)
                .overlay(
                    Capsule().strokeBorder(
                        DS.Palette.textSecondary.opacity(0.5),
                        style: StrokeStyle(lineWidth: 1, dash: [4, 3])
                    )
                )
                .accessibilityIdentifier("quickMarks.undo")
            }
        }
    }
}

private struct QuickMarkCard: View {
    let mark: QuickMarkDTO
    /// "ждёт отправки: N" while presses of this button wait in the queue: the drawn total already
    /// counts them, and VoiceOver has to say they are not on the server yet.
    let waitingCaption: String?
    let onOpen: () -> Void
    let onTap: () -> Void

    private var foreground: Color {
        mark.done ? DS.Palette.background : DS.Palette.textPrimary
    }

    var body: some View {
        HStack(spacing: 0) {
            Button(action: onOpen) {
                VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                    HStack(spacing: DS.Spacing.xs) {
                        if mark.planned {
                            Text(QuickMarkWording.plannedBadge)
                                .font(DS.Typography.caption)
                                .padding(.horizontal, DS.Spacing.xs)
                                .background(
                                    (mark.done ? DS.Palette.background : DS.Palette.lime).opacity(0.18),
                                    in: RoundedRectangle(cornerRadius: DS.Radius.chip / 2)
                                )
                        }
                        Text(mark.label)
                            .font(DS.Typography.card)
                            .lineLimit(1)
                    }
                    if !mark.caption.isEmpty {
                        Text(mark.caption)
                            .font(DS.Typography.caption)
                            .opacity(0.8)
                            .monospacedDigit()
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, DS.Spacing.md)
                .padding(.leading, DS.Spacing.lg)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(
                "\(QuickMarkWording.heading(forKind: mark.kind)) — \(mark.label)"
            )
            .accessibilityValue(waitingCaption ?? "")

            Button(action: onTap) {
                Image(systemName: mark.kind == QuickMarkDTO.kindCheck ? "checkmark" : "plus")
                    .font(DS.Typography.section)
                    .frame(width: 52)
                    .frame(maxHeight: .infinity)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(mark.accessibilityName)
            .accessibilityValue(waitingCaption ?? "")
            .accessibilityIdentifier("quickMark.tap.\(mark.id)")
        }
        .foregroundStyle(foreground)
        .frame(minHeight: 56)
        .background(mark.done ? DS.Palette.lime : DS.Palette.card)
        .clipShape(RoundedRectangle(cornerRadius: DS.Radius.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: DS.Radius.card, style: .continuous)
                .stroke(mark.done ? DS.Palette.lime : DS.Palette.cardStroke, lineWidth: 1)
        )
    }
}
