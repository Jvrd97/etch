// [review:need-review] PHASE-01/212
// summary: Chat screen replacing the #208 placeholder — message feed with the live bubble of the running turn, composer, history sheet and new-conversation button in the toolbar; the running turn is cancelled when the screen goes away
import SwiftUI

struct ChatView: View {
    @StateObject private var viewModel: ChatViewModel
    @State private var isHistoryOpen = false

    private static let bottomID = "chat-bottom"
    private static let emptyHint = "Напишите сообщение — ответ придёт по кускам."

    init() {
        _viewModel = StateObject(wrappedValue: .live())
    }

    init(viewModel: ChatViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        VStack(spacing: 0) {
            content
            if let notice = viewModel.notice {
                // Outside the composer: without a conversation there is no composer, and
                // a failed "new conversation" must still be seen.
                Text(notice)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.danger)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, DS.Spacing.lg)
                    .padding(.vertical, DS.Spacing.sm)
                    .background(DS.Palette.background)
            }
            if viewModel.isReady {
                composer
            }
        }
        .navigationTitle(AppTab.chat.title)
        .navigationBarTitleDisplayMode(.inline)
        .dsScreenBackground()
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button {
                    isHistoryOpen = true
                } label: {
                    Image(systemName: "clock.arrow.circlepath")
                        .accessibilityLabel("История разговоров")
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    Task { await viewModel.startNewConversation() }
                } label: {
                    Image(systemName: "square.and.pencil")
                        .accessibilityLabel("Новый разговор")
                }
                .disabled(viewModel.isTurnRunning)
            }
        }
        .task { await viewModel.refresh() }
        // Leaving the screen closes the connection. The server keeps what it had as
        // `interrupted`, and the next appearance re-reads it.
        .onDisappear { viewModel.cancelTurn() }
        .sheet(isPresented: $isHistoryOpen) {
            ChatHistoryView(viewModel: viewModel) { isHistoryOpen = false }
        }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.screen {
        case .loading:
            NeonLoader(label: "Loading")
        case .failed(let message):
            DSErrorState(message: message) {
                Task { await viewModel.retry() }
            }
        case .empty:
            DSEmptyState(
                title: "Разговор не выбран",
                systemImage: "bubble.left.and.bubble.right",
                message: "Откройте разговор из истории или начните новый.",
                action: (label: "Новый разговор", run: {
                    Task { await viewModel.startNewConversation() }
                })
            )
        case .ready:
            feed
        }
    }

    private var feed: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: DS.Spacing.md) {
                    if viewModel.messages.isEmpty && viewModel.turn == nil {
                        Text(Self.emptyHint)
                            .font(DS.Typography.body)
                            .foregroundStyle(DS.Palette.textSecondary)
                            .padding(.top, DS.Spacing.xxl)
                    }
                    ForEach(viewModel.messages) { message in
                        ChatMessageRow(message: message, viewModel: viewModel)
                    }
                    if let turn = viewModel.turn {
                        ChatTurnView(turn: turn)
                    }
                    if viewModel.isStuck {
                        stuckBanner
                    }
                    Color.clear.frame(height: 1).id(Self.bottomID)
                }
                .padding(DS.Spacing.lg)
            }
            .defaultScrollAnchor(.bottom)
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: viewModel.messages.count) { scrollToBottom(proxy) }
            .onChange(of: viewModel.turn?.text) { scrollToBottom(proxy) }
            .onChange(of: viewModel.turn?.question) { scrollToBottom(proxy) }
        }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        proxy.scrollTo(Self.bottomID, anchor: .bottom)
    }

    private var stuckBanner: some View {
        VStack(spacing: DS.Spacing.sm) {
            Text("Ход не закрыт: ответ не придёт. Сбросьте разговор, чтобы писать дальше.")
                .font(DS.Typography.caption)
                .foregroundStyle(DS.Palette.warning)
                .multilineTextAlignment(.center)
            Button("Сбросить разговор") {
                Task { await viewModel.reset() }
            }
            .buttonStyle(LimeButtonStyle(prominent: false))
            .fixedSize()
        }
    }

    private var composer: some View {
        VStack(spacing: DS.Spacing.sm) {
            HStack(alignment: .bottom, spacing: DS.Spacing.sm) {
                TextField("Сообщение", text: $viewModel.draft, axis: .vertical)
                    .lineLimit(1...5)
                    .textFieldStyle(.plain)
                    .padding(.horizontal, DS.Spacing.md)
                    .padding(.vertical, DS.Spacing.sm + 2)
                    .background(DS.Palette.surface)
                    .clipShape(RoundedRectangle(cornerRadius: DS.Radius.control, style: .continuous))
                    .disabled(viewModel.isBusy)
                Button {
                    viewModel.send()
                } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 34))
                        .foregroundStyle(viewModel.canSend ? DS.Palette.lime : DS.Palette.textDisabled)
                        .accessibilityLabel("Отправить")
                }
                .disabled(!viewModel.canSend)
            }
        }
        .padding(.horizontal, DS.Spacing.lg)
        .padding(.vertical, DS.Spacing.sm)
        .background(DS.Palette.background)
    }
}
