// [review:need-review] PHASE-01/32-ios-lime-tech-design-pass, PHASE-01/11-ios-read-cache, PHASE-01/208
// summary: Table screen — Lime Tech dark restyle: contributions-style grid, lime-tinted filled cells, neon loader; offline banner atop when the window came from the read cache
// [review:need-review] PHASE-03/310
// summary: PHASE-03/310 — opens on the cached window, reads again only what is not recent, a failed re-read is a line above the grid
import SwiftUI

struct TableView: View {
    @StateObject private var viewModel: TableViewModel
    @State private var selectedCell: TableCellSelection?

    init(viewModel: TableViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    private enum Metrics {
        static let dateColumnWidth: CGFloat = 96
        static let valueColumnWidth: CGFloat = 88
        static let loaderFooterHeight: CGFloat = 64
    }

    var body: some View {
        VStack(spacing: 0) {
            if let offlineAsOf = viewModel.offlineAsOf {
                OfflineBanner(updatedAt: offlineAsOf)
            }
            if let problem = viewModel.refreshError {
                Text(problem)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.danger)
                    .padding(.horizontal, DS.Spacing.md)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            content
        }
        .navigationTitle("Table")
        .dsScreenBackground()
        .onAppear { viewModel.showCached() }
        .task { await viewModel.appear() }
        .sheet(item: $selectedCell) { selection in
            TableCellDetailSheet(selection: selection, viewModel: viewModel)
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
        case .loaded:
            grid
        }
    }

    private var grid: some View {
        ScrollView(.vertical) {
            ScrollView(.horizontal, showsIndicators: true) {
                Grid(alignment: .leading, horizontalSpacing: 0, verticalSpacing: 0) {
                    headerRow
                    Divider()
                    ForEach(viewModel.grid.rows) { row in
                        dataRow(row)
                        Divider()
                    }
                }
                .padding(.horizontal)
            }
            loadOlderFooter
        }
        .refreshable {
            await viewModel.load()
        }
    }

    private var headerRow: some View {
        GridRow {
            Text("Day")
                .font(DS.Typography.caption)
                .foregroundStyle(DS.Palette.textSecondary)
                .frame(width: Metrics.dateColumnWidth, alignment: .leading)
            ForEach(viewModel.grid.columns) { column in
                Text(column.title)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
                    .lineLimit(1)
                    .frame(width: Metrics.valueColumnWidth, alignment: .center)
            }
        }
        .padding(.vertical, DS.Spacing.sm)
    }

    private func dataRow(_ row: TableGridRow) -> some View {
        GridRow {
            Text(row.date)
                .font(DS.Typography.caption.monospaced())
                .foregroundStyle(DS.Palette.textSecondary)
                .frame(width: Metrics.dateColumnWidth, alignment: .leading)
            ForEach(Array(viewModel.grid.columns.enumerated()), id: \.element.id) { index, column in
                cellButton(row: row, column: column, cell: row.cells[index])
            }
        }
        .padding(.vertical, DS.Spacing.sm)
    }

    @ViewBuilder
    private func cellButton(
        row: TableGridRow, column: TableGridColumn, cell: TableGridCell
    ) -> some View {
        if cell.isEmpty {
            Text("—")
                .foregroundStyle(DS.Palette.textDisabled)
                .frame(width: Metrics.valueColumnWidth, alignment: .center)
        } else {
            Button {
                selectedCell = TableCellSelection(
                    date: row.date,
                    categoryId: column.categoryId,
                    fieldId: column.fieldId,
                    title: column.title
                )
            } label: {
                Text(cell.value ?? "—")
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.lime)
                    .lineLimit(1)
                    .frame(width: Metrics.valueColumnWidth - DS.Spacing.sm, alignment: .center)
                    .padding(.vertical, DS.Spacing.xs)
                    .background(
                        RoundedRectangle(cornerRadius: DS.Radius.chip, style: .continuous)
                            .fill(DS.Palette.lime.opacity(0.14))
                    )
                    .frame(width: Metrics.valueColumnWidth, alignment: .center)
            }
            .buttonStyle(.plain)
        }
    }

    @ViewBuilder
    private var loadOlderFooter: some View {
        if viewModel.isLoadingOlder {
            NeonLoader()
                .frame(height: Metrics.loaderFooterHeight)
                .padding()
        } else {
            VStack(spacing: DS.Spacing.sm) {
                if let message = viewModel.loadOlderErrorMessage {
                    Text(message)
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.danger)
                }
                Button("Load older days") {
                    Task { await viewModel.loadOlder() }
                }
                .buttonStyle(LimeButtonStyle(prominent: false))
                .fixedSize()
            }
            .padding()
        }
    }
}

/// Identifies the tapped cell so the sheet can fetch the day's source entries.
struct TableCellSelection: Identifiable, Equatable {
    let date: String
    let categoryId: Int
    let fieldId: Int
    let title: String

    var id: String { "\(categoryId)-\(date)" }
}

/// Sheet listing the raw entries a cell's aggregated value was composed from.
struct TableCellDetailSheet: View {
    let selection: TableCellSelection
    let viewModel: TableViewModel

    @Environment(\.dismiss) private var dismiss

    private enum LoadState: Equatable {
        case loading
        case loaded([EntryDTO])
        case failure(String)
    }

    @State private var state: LoadState = .loading

    var body: some View {
        NavigationStack {
            content
                .navigationTitle(selection.title)
                .navigationBarTitleDisplayMode(.inline)
                .dsScreenBackground()
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Done") { dismiss() }
                    }
                }
        }
        .task { await load() }
    }

    @ViewBuilder
    private var content: some View {
        switch state {
        case .loading:
            NeonLoader(label: "Loading")
        case .failure(let message):
            Text(message)
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.danger)
                .padding()
        case .loaded(let entries) where entries.isEmpty:
            Text("No records for \(selection.date)")
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.textSecondary)
                .padding()
        case .loaded(let entries):
            List {
                Section(selection.date) {
                    ForEach(entries) { entry in
                        entryRow(entry)
                    }
                    .listRowBackground(DS.Palette.card)
                }
            }
        }
    }

    private func entryRow(_ entry: EntryDTO) -> some View {
        VStack(alignment: .leading, spacing: DS.Spacing.xs) {
            ForEach(entry.values, id: \.fieldId) { value in
                HStack {
                    Text("Field \(value.fieldId)")
                        .foregroundStyle(DS.Palette.textSecondary)
                    Spacer()
                    Text(value.value ?? "—")
                        .foregroundStyle(DS.Palette.textPrimary)
                }
                .font(DS.Typography.body)
            }
        }
        .padding(.vertical, DS.Spacing.xs)
    }

    private func load() async {
        state = .loading
        do {
            let entries = try await viewModel.fetchCellEntries(
                categoryId: selection.categoryId, date: selection.date
            )
            state = .loaded(entries)
        } catch let error as APIClientError {
            state = .failure(error.userMessage)
        } catch {
            state = .failure("Unexpected error")
        }
    }
}
