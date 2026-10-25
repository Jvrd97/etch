// [review:need-review] PHASE-01/37-ios-insights, PHASE-01/208
// summary: Insights screen — period selector + "разбор периода" with neon loader, 503 hint, Markdown report render, history list with detail sheet
import SwiftUI

struct InsightsView: View {
    @StateObject private var viewModel: InsightsViewModel

    init(viewModel: InsightsViewModel) {
        _viewModel = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        content
            .navigationTitle("Insights")
            .dsScreenBackground()
        .task { await viewModel.load() }
        .sheet(item: $viewModel.openedReport) { report in
            InsightReportView(report: report)
        }
    }

    @ViewBuilder
    private var content: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DS.Spacing.xl) {
                analysisCard
                sectionHeader("История разборов")
                history
            }
            .padding(DS.Spacing.lg)
        }
        .refreshable { await viewModel.load() }
    }

    // MARK: - Analysis

    private var analysisCard: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.lg) {
                Text("Период анализа")
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.textSecondary)
                Picker("Период", selection: $viewModel.selectedPeriod) {
                    ForEach(InsightPeriod.allCases) { period in
                        Text(period.label).tag(period)
                    }
                }
                .pickerStyle(.segmented)
                .disabled(isRunning)

                analysisAction
            }
        }
    }

    @ViewBuilder
    private var analysisAction: some View {
        switch viewModel.analysisState {
        case .running:
            NeonLoader(label: "Анализирую период…")
                .frame(height: 120)
        case .notConfigured:
            notConfiguredHint
        case .failure(let message):
            VStack(spacing: DS.Spacing.md) {
                Text(message)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.danger)
                    .multilineTextAlignment(.center)
                runButton(title: "Повторить")
            }
        case .idle:
            runButton(title: "Разобрать период")
        }
    }

    private func runButton(title: String) -> some View {
        Button {
            Task { await viewModel.runAnalysis() }
        } label: {
            Label(title, systemImage: "sparkles")
        }
        .buttonStyle(LimeButtonStyle())
    }

    /// Honest hint for a backend that answered 503 (AI insights disabled — no LLM key).
    private var notConfiguredHint: some View {
        VStack(spacing: DS.Spacing.md) {
            Image(systemName: "wand.and.stars")
                .font(.system(size: 40, weight: .regular))
                .foregroundStyle(DS.Palette.textSecondary)
            Text("AI-разбор не подключён")
                .font(DS.Typography.card)
                .foregroundStyle(DS.Palette.textPrimary)
            Text("Сервер не сконфигурирован для AI-инсайтов. Добавьте ключ на бэкенде и повторите.")
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.textSecondary)
                .multilineTextAlignment(.center)
            runButton(title: "Повторить")
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, DS.Spacing.md)
    }

    private var isRunning: Bool {
        viewModel.analysisState == .running
    }

    // MARK: - History

    @ViewBuilder
    private var history: some View {
        switch viewModel.historyState {
        case .idle, .loading:
            NeonLoader(label: "Loading")
                .frame(height: 160)
        case .failure(let message):
            DSErrorState(message: message) {
                Task { await viewModel.load() }
            }
            .frame(height: 220)
        case .loaded:
            historyList
        }
    }

    @ViewBuilder
    private var historyList: some View {
        if viewModel.reports.isEmpty {
            Card {
                Text("Разборов пока нет — запустите первый анализ выше.")
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textSecondary)
            }
        } else {
            VStack(spacing: DS.Spacing.md) {
                ForEach(viewModel.reports) { report in
                    Button {
                        Task { await viewModel.openReport(id: report.id) }
                    } label: {
                        InsightHistoryRow(report: report)
                    }
                    .buttonStyle(.plain)
                }
            }
            if let message = viewModel.openErrorMessage {
                Text(message)
                    .font(DS.Typography.caption)
                    .foregroundStyle(DS.Palette.danger)
            }
        }
    }

    private func sectionHeader(_ title: String) -> some View {
        Text(title)
            .font(DS.Typography.section)
            .foregroundStyle(DS.Palette.textPrimary)
    }
}

/// A single report history row: period + timestamp on top, a preview underneath.
struct InsightHistoryRow: View {
    let report: InsightListItemDTO

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: DS.Spacing.sm) {
                HStack {
                    Text("\(report.periodDays) дней")
                        .font(DS.Typography.card)
                        .foregroundStyle(DS.Palette.lime)
                    Spacer()
                    Text(report.createdAt)
                        .font(DS.Typography.caption)
                        .foregroundStyle(DS.Palette.textSecondary)
                }
                Text(report.preview)
                    .font(DS.Typography.body)
                    .foregroundStyle(DS.Palette.textPrimary)
                    .lineLimit(3)
            }
        }
    }
}

/// Full report reader: renders the Markdown content of one AI report.
struct InsightReportView: View {
    let report: InsightReportDTO

    var body: some View {
        NavigationStack {
            ScrollView {
                MarkdownText(markdown: report.content)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(DS.Spacing.lg)
            }
            .dsScreenBackground()
            .navigationTitle("Разбор за \(report.periodDays) дней")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}

/// Minimal block-level Markdown renderer: headings, bullet/numbered lists, and
/// paragraphs, each line's inline emphasis parsed via `AttributedString`. Enough to
/// present the backend's structured report (trends / gaps / correlations / advice)
/// without pulling in a Markdown dependency.
struct MarkdownText: View {
    let markdown: String

    var body: some View {
        VStack(alignment: .leading, spacing: DS.Spacing.sm) {
            ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                lineView(line)
            }
        }
    }

    private var lines: [String] {
        markdown.components(separatedBy: "\n")
    }

    @ViewBuilder
    private func lineView(_ raw: String) -> some View {
        let trimmed = raw.trimmingCharacters(in: .whitespaces)
        if trimmed.isEmpty {
            Spacer().frame(height: DS.Spacing.xs)
        } else if let heading = heading(trimmed) {
            Text(inline(heading.text))
                .font(heading.font)
                .foregroundStyle(DS.Palette.textPrimary)
                .padding(.top, DS.Spacing.sm)
        } else if let bullet = bullet(trimmed) {
            HStack(alignment: .top, spacing: DS.Spacing.sm) {
                Text("•").foregroundStyle(DS.Palette.lime)
                Text(inline(bullet))
                    .foregroundStyle(DS.Palette.textPrimary)
            }
            .font(DS.Typography.body)
        } else {
            Text(inline(trimmed))
                .font(DS.Typography.body)
                .foregroundStyle(DS.Palette.textPrimary)
        }
    }

    private func heading(_ line: String) -> (text: String, font: Font)? {
        if line.hasPrefix("### ") {
            return (String(line.dropFirst(4)), DS.Typography.card)
        }
        if line.hasPrefix("## ") {
            return (String(line.dropFirst(3)), DS.Typography.section)
        }
        if line.hasPrefix("# ") {
            return (String(line.dropFirst(2)), DS.Typography.h1)
        }
        return nil
    }

    private func bullet(_ line: String) -> String? {
        for marker in ["- ", "* "] where line.hasPrefix(marker) {
            return String(line.dropFirst(marker.count))
        }
        return nil
    }

    /// Parses inline emphasis (bold/italic/code/links); falls back to plain text.
    private func inline(_ text: String) -> AttributedString {
        (try? AttributedString(markdown: text)) ?? AttributedString(text)
    }
}
