// [review:need-review] PHASE-01/208, PHASE-01/210, PHASE-03/225
// summary: the Quick marks screen behind More — the same buttons and day-sets list as Today, on their own, under the shared offline-queue strip; replaces the #208 placeholder and builds its view model with .live() so RootView needs no edit
import SwiftUI

struct QuickMarksView: View {
    @StateObject private var viewModel: QuickMarksViewModel
    @State private var openedMark: QuickMarkDTO?

    init() {
        _viewModel = StateObject(wrappedValue: .live())
    }

    init(viewModel: QuickMarksViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        VStack(spacing: 0) {
            OutboxQueueBar(queue: OutboxLive.shared)
            content
        }
        .navigationTitle(MoreDestination.quickMarks.title)
        .dsScreenBackground()
        .task { await viewModel.load() }
        .sheet(item: $openedMark) { mark in
            QuickMarkSetsSheet(mark: mark, viewModel: viewModel)
        }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel.state {
        case .idle, .loading:
            NeonLoader(label: "Loading")
        case .failure(let message):
            DSErrorState(message: message) {
                Task { await viewModel.load() }
            }
        case .loaded where viewModel.marks.isEmpty:
            DSEmptyState(
                title: "Кнопок пока нет",
                systemImage: "bolt",
                message: "Кнопки заводятся на сервере; здесь появятся отметки в одно касание."
            )
        case .loaded:
            ScrollView {
                QuickMarksSection(viewModel: viewModel) { openedMark = $0 }
                    .padding(DS.Spacing.lg)
            }
            .refreshable { await viewModel.load() }
        }
    }
}

/// The sets of the day behind one card, on their own — the screen has no records list beside it.
struct QuickMarkSetsSheet: View {
    let mark: QuickMarkDTO
    @ObservedObject var viewModel: QuickMarksViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                QuickMarkDaySetsSection(mark: mark, quickMarks: viewModel)
            }
            .scrollContentBackground(.hidden)
            .dsScreenBackground()
            .navigationTitle(mark.label)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Готово") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }
}
