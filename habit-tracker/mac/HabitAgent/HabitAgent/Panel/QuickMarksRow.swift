// [review:need-review] PHASE-03/170
// summary: the quick marks row of the floating window — up to four buttons from GET /quick-marks?surface=agent (glyph, label, total with its unit) and a fifth that opens the page of marks in the browser; a tap is written to a file queue under an Idempotency-Key and the button repaints from the answer to the POST, with no second GET; an unsent tap is shown as accepted and marked «не отправлено»; the list is polled every 15 s while the window is visible and keeps its last picture, marked stale, when the server is silent
import AppKit
import Combine
import Foundation
import SwiftUI

// MARK: - Wire types

/// One button as `GET /quick-marks?surface=agent` sends it. Fields the window does not draw are not read.
struct QuickMark: Equatable, Decodable {
    let id: Int
    let label: String
    let icon: String?
    let color: String?
    /// `increment`, `check`, `set_value` or `relapse`; a kind the window does not know is drawn as a counter.
    let kind: String
    let step: Double?
    let unitLabel: String?
    /// The day the totals below belong to, `yyyy-MM-dd`; the server's word, never computed here.
    let entryDate: String
    var todayTotal: Double?
    var done: Bool

    static let checkKind = "check"

    enum CodingKeys: String, CodingKey {
        case id, label, icon, color, kind, step, done
        case unitLabel = "unit_label"
        case entryDate = "entry_date"
        case todayTotal = "today_total"
    }
}

/// A press waiting for the server. It is on disk from the moment of the press, and `key`
/// is its `Idempotency-Key` for every resend, so a lost answer cannot make two events.
struct QuickMarkTap: Codable, Equatable {
    let key: UUID
    let markID: Int
    /// The moment of the press: a tap that arrives later still lands on its own moment.
    let occurredAt: Date
    let utcOffsetMinutes: Int
}

/// The new state of the day that comes back with a tap.
struct QuickMarkEventResult: Equatable, Decodable {
    let quickMarkID: Int
    let entryDate: String
    let todayTotal: Double?
    let done: Bool

    enum CodingKeys: String, CodingKey {
        case quickMarkID = "quick_mark_id"
        case entryDate = "entry_date"
        case todayTotal = "today_total"
        case done
    }
}

// MARK: - What a button shows

struct QuickMarkButton: Identifiable, Equatable {
    let id: Int
    let label: String
    let icon: String?
    let color: String?
    /// «750 мл», «✓» or «–».
    let countText: String
    let isDone: Bool
    /// Counted on the button, not yet confirmed by the server.
    let isPending: Bool
    /// «+250 мл» — what one tap adds.
    let stepText: String?

    /// Whole numbers without a fraction; one digit otherwise, which is all a 44-point button holds.
    static func format(_ value: Double) -> String {
        value == value.rounded() ? String(Int(value)) : String(format: "%.1f", value)
    }
}

enum QuickMarkGlyph: Equatable {
    case symbol(String)
    case emoji(String)
    case letter(String)

    /// `icon` is a name the person typed: an SF Symbol if there is one by that name, an emoji if it is one,
    /// otherwise the first letter of the label — a button must never be blank.
    static func resolve(icon: String?, label: String) -> QuickMarkGlyph {
        if let icon, !icon.isEmpty {
            if NSImage(systemSymbolName: icon, accessibilityDescription: nil) != nil { return .symbol(icon) }
            if icon.unicodeScalars.contains(where: { $0.properties.isEmojiPresentation }) { return .emoji(icon) }
        }
        return .letter(label.first.map { String($0).uppercased() } ?? "?")
    }

    /// `#rrggbb` as three 0...1 components; anything else is nil.
    static func rgb(of hex: String?) -> (red: Double, green: Double, blue: Double)? {
        guard let hex, hex.count == 7, hex.hasPrefix("#"), let value = UInt32(hex.dropFirst(), radix: 16) else { return nil }
        return (Double(value >> 16 & 0xFF) / 255, Double(value >> 8 & 0xFF) / 255, Double(value & 0xFF) / 255)
    }
}

// MARK: - Model

@MainActor
final class QuickMarksModel: ObservableObject {
    typealias Post = QuickMarkOutbox.Sender

    /// Buttons drawn before the fifth place, which is always the way to the browser.
    static let maxButtons = 4
    /// Seconds between polls while the window is visible (`docs/quick-marks-agent-contract.md`).
    static let pollInterval: TimeInterval = 15
    /// Silence longer than this marks the row as not fresh: four polls missed.
    static let staleAfter: TimeInterval = 60
    /// Retries go 15 s → 30 s → 60 s and stay there, so a network that came back is noticed within a minute.
    static let maxRetryDelay: TimeInterval = 60
    /// How long the note about a refused tap stays.
    private static let rejectedNoteSeconds: TimeInterval = 15
    private static let morePath = "/quick-marks"

    let poller: ConditionalPoller<[QuickMark]>
    let outbox: QuickMarkOutbox
    /// The list has been silent longer than `staleAfter`.
    @Published private(set) var isStale = false
    /// A tap was refused for good a moment ago.
    @Published private(set) var rejectedNote = false

    /// The server's answer to a tap, shown until a poll started after that answer succeeds.
    /// A poll asked before the answer proves nothing about the tap and may land late with the old total.
    private struct Answer {
        let result: QuickMarkEventResult
        let afterPoll: Int
    }

    @Published private var answers: [Int: Answer] = [:]
    private let serverAddress: () -> String?
    private let openURL: (URL) -> Void
    private let now: () -> Date
    private let utcOffsetMinutes: () -> Int
    private var pollTask: Task<Void, Never>?
    private var observers: [AnyCancellable] = []

    init(
        outboxFile: URL,
        serverAddress: @escaping () -> String?,
        openURL: @escaping (URL) -> Void,
        now: @escaping () -> Date = Date.init,
        utcOffsetMinutes: @escaping () -> Int = { TimeZone.current.secondsFromGMT() / 60 },
        sleep: @escaping ConditionalPoller<[QuickMark]>.Sleep = { try await Task.sleep(nanoseconds: UInt64($0 * 1_000_000_000)) },
        fetch: @escaping ConditionalPoller<[QuickMark]>.Fetch,
        post: @escaping Post
    ) {
        self.serverAddress = serverAddress
        self.openURL = openURL
        self.now = now
        self.utcOffsetMinutes = utcOffsetMinutes
        poller = ConditionalPoller(
            interval: Self.pollInterval, staleAfter: Self.staleAfter, maxRetryDelay: Self.maxRetryDelay,
            now: now, sleep: sleep, fetch: fetch
        )
        // The answer is kept before the outbox forgets the tap, so the count never steps back in between.
        outbox = QuickMarkOutbox(fileURL: outboxFile, now: now, send: post)
        outbox.onConfirmed = { [weak self] result in self?.keep(result) }
        observers = [
            poller.objectWillChange.sink { [weak self] in self?.objectWillChange.send() },
            outbox.objectWillChange.sink { [weak self] in self?.objectWillChange.send() },
            poller.$lastSuccessfulPoll.sink { [weak self] poll in
                self?.answers = self?.answers.filter { $0.value.afterPoll >= poll } ?? [:]
            },
        ]
    }

    /// The marks as the window draws them: the first four, the server's order.
    var buttons: [QuickMarkButton] {
        (poller.value ?? []).prefix(Self.maxButtons).map(button)
    }

    /// The fifth place is there with any number of marks, so the page of marks is always one click away.
    var showsMore: Bool { true }

    var pendingCount: Int { outbox.pending.count }

    /// What the line under the row says, nil when there is nothing to say.
    var note: String? {
        let parts = [
            isStale ? "данные не свежие" : nil,
            pendingCount > 0 ? "не отправлено: \(pendingCount)" : nil,
            rejectedNote ? "сервер отклонил отметку" : nil,
        ].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// Writes the tap to the queue and tries to send it at once. The button counts it before the server answers.
    /// Nil when the window has no such mark.
    @discardableResult
    func tap(_ markID: Int) -> Task<Void, Never>? {
        guard poller.value?.contains(where: { $0.id == markID }) == true else { return nil }
        outbox.enqueue(QuickMarkTap(key: UUID(), markID: markID, occurredAt: now(), utcOffsetMinutes: utcOffsetMinutes()))
        return Task { await outbox.flush() }
    }

    /// The page of marks in the browser, on the origin the agent talks to.
    func openMore() {
        guard let address = serverAddress(), let url = PanelAPIClient.endpoint(for: address, path: Self.morePath) else { return }
        openURL(url)
    }

    /// Polls while the window is visible. A hidden window asks nobody: the row behind it is for no one.
    func startPolling() {
        guard pollTask == nil else { return }
        let poller = poller
        pollTask = Task { await poller.run() }
    }

    func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    /// Called about once a second by whoever owns the window.
    func tick() {
        isStale = poller.isStale(at: now())
        rejectedNote = outbox.lastRejectedAt.map { now().timeIntervalSince($0) < Self.rejectedNoteSeconds } ?? false
        if outbox.isDue { Task { await outbox.flush() } }
    }

    private func keep(_ result: QuickMarkEventResult) {
        answers[result.quickMarkID] = Answer(result: result, afterPoll: poller.pollsStarted)
    }

    private func button(_ mark: QuickMark) -> QuickMarkButton {
        var total = mark.todayTotal
        var done = mark.done
        // The answer is about the same day as the list; after midnight the list wins.
        if let answer = answers[mark.id]?.result, answer.entryDate == mark.entryDate {
            total = answer.todayTotal
            done = answer.done
        }
        let waiting = outbox.pending.filter { $0.markID == mark.id }.count
        let isCheck = mark.kind == QuickMark.checkKind
        if waiting > 0 {
            if isCheck {
                done = true
            } else {
                total = (total ?? 0) + Double(waiting) * (mark.step ?? 1)
            }
        }
        let unit = mark.unitLabel.map { " \($0)" } ?? ""
        let count = isCheck ? (done ? "✓" : "–") : QuickMarkButton.format(total ?? 0) + unit
        let step = isCheck ? nil : mark.step.map { "+\(QuickMarkButton.format($0))\(unit)" }
        return QuickMarkButton(
            id: mark.id, label: mark.label, icon: mark.icon, color: mark.color,
            countText: count, isDone: done, isPending: waiting > 0, stepText: step
        )
    }
}

// MARK: - View

struct QuickMarksRow: View {
    @ObservedObject var model: QuickMarksModel

    static let cellWidth: CGFloat = 44
    static let cellHeight: CGFloat = 44
    private static let spacing: CGFloat = 4

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: Self.spacing) {
                ForEach(model.buttons) { button in
                    QuickMarkCell(button: button) { model.tap(button.id) }
                }
                Spacer(minLength: 0)
                MoreCell(action: model.openMore)
            }
            Text(model.note ?? " ")
                .font(.caption2)
                .foregroundStyle(.orange)
                .lineLimit(1)
        }
    }
}

private struct QuickMarkCell: View {
    let button: QuickMarkButton
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 1) {
                QuickMarkGlyphView(icon: button.icon, label: button.label, color: button.color)
                    .frame(height: 16)
                Text(button.label)
                    .font(.system(size: 9))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Text(button.countText)
                    .font(.system(size: 11, weight: .semibold))
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
            }
            .frame(width: QuickMarksRow.cellWidth, height: QuickMarksRow.cellHeight)
            .background(button.isDone ? Color.accentColor.opacity(0.15) : Color.primary.opacity(0.06), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(alignment: .topTrailing) {
                if button.isPending {
                    Circle().fill(Color.orange).frame(width: 6, height: 6).padding(3)
                }
            }
        }
        .buttonStyle(.plain)
        .help([button.label, button.stepText, button.isPending ? "не отправлено" : nil].compactMap { $0 }.joined(separator: ", "))
        .accessibilityLabel("\(button.label), \(button.countText)\(button.isPending ? ", не отправлено" : "")")
    }
}

private struct MoreCell: View {
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 2) {
                Image(systemName: "safari").frame(height: 16)
                Text("ещё").font(.system(size: 9)).foregroundStyle(.secondary)
            }
            .frame(width: QuickMarksRow.cellWidth, height: QuickMarksRow.cellHeight)
            .background(Color.primary.opacity(0.06), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(.plain)
        .help("Все отметки в браузере")
        .accessibilityLabel("Ещё отметки в браузере")
    }
}

private struct QuickMarkGlyphView: View {
    let icon: String?
    let label: String
    let color: String?

    var body: some View {
        let tint = QuickMarkGlyph.rgb(of: color).map { Color(red: $0.red, green: $0.green, blue: $0.blue) } ?? Color.primary
        switch QuickMarkGlyph.resolve(icon: icon, label: label) {
        case let .symbol(name):
            Image(systemName: name).foregroundStyle(tint)
        case let .emoji(text):
            Text(text)
        case let .letter(letter):
            Text(letter).font(.system(size: 13, weight: .bold, design: .rounded)).foregroundStyle(tint)
        }
    }
}
