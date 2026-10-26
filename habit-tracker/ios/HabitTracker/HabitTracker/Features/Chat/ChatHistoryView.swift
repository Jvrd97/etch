// [review:need-review] PHASE-01/212
// summary: history sheet of the chat — the conversation list, opening one, swipe-to-delete behind a confirmation, and the reason shown when the server (409) or the running answer forbids deleting
import SwiftUI

struct ChatHistoryView: View {
    @ObservedObject var viewModel: ChatViewModel
    let onClose: () -> Void

    @State private var pendingDeletion: ChatConversationDTO?

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if let notice = viewModel.historyNoticeLine {
                    Text(notice)
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.danger)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(DS.Spacing.lg)
                }
                content
            }
            .navigationTitle("История")
            .navigationBarTitleDisplayMode(.inline)
            .dsScreenBackground()
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Готово", action: onClose)
                }
            }
        }
        .task { await viewModel.loadHistory() }
        .confirmationDialog(
            "Удалить разговор?",
            isPresented: Binding(
                get: { pendingDeletion != nil },
                set: { if !$0 { pendingDeletion = nil } }
            ),
            titleVisibility: .visible,
            presenting: pendingDeletion
        ) { conversation in
            Button("Удалить", role: .destructive) {
                Task { await viewModel.deleteConversation(id: conversation.id) }
            }
            Button("Отмена", role: .cancel) {}
        } message: { _ in
            Text("Разговор и его сообщения будут удалены насовсем.")
        }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.historyState {
        case .idle, .loading:
            NeonLoader(label: "Loading")
        case .failure(let message):
            DSErrorState(message: message) {
                Task { await viewModel.loadHistory() }
            }
        case .loaded:
            if viewModel.conversations.isEmpty {
                DSEmptyState(
                    title: "Разговоров нет",
                    systemImage: "bubble.left",
                    message: "Начните новый разговор кнопкой на экране чата."
                )
            } else {
                list
            }
        }
    }

    private var list: some View {
        List(viewModel.conversations) { conversation in
            Button {
                Task {
                    onClose()
                    await viewModel.open(conversationID: conversation.id)
                }
            } label: {
                row(conversation)
            }
            .listRowBackground(DS.Palette.card)
            .swipeActions(edge: .trailing) {
                Button(role: .destructive) {
                    requestDeletion(of: conversation)
                } label: {
                    Label("Удалить", systemImage: "trash")
                }
            }
        }
        .refreshable { await viewModel.loadHistory() }
    }

    private func row(_ conversation: ChatConversationDTO) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: DS.Spacing.xs) {
                Text(conversation.title ?? "Разговор \(conversation.id)")
                    .font(DS.Typography.card)
                    .foregroundStyle(DS.Palette.textPrimary)
                    .lineLimit(2)
                Text("\(conversation.startedOn) · сообщений: \(conversation.messageCount)")
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
            }
            Spacer()
            if conversation.id == viewModel.openConversationID {
                Image(systemName: "checkmark")
                    .foregroundStyle(DS.Palette.lime)
                    .accessibilityLabel("Открыт")
            }
        }
    }

    /// A conversation with a running answer is not offered for deletion: the view model
    /// shows the reason instead of a confirmation.
    private func requestDeletion(of conversation: ChatConversationDTO) {
        if viewModel.deleteBlockedReason(for: conversation.id) != nil {
            Task { await viewModel.deleteConversation(id: conversation.id) }
        } else {
            pendingDeletion = conversation
        }
    }
}
