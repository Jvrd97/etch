// [review:need-review] PHASE-03/159
// summary: holds the timer's manual intervals in a file under Application Support until the server confirms each one; resends under the same Idempotency-Key on the shared Backoff, drops what the server refuses for good
import Foundation
import os

@MainActor
final class ManualIntervalOutbox {
    typealias Sender = (ManualInterval) async throws -> Void

    private static let log = Logger(subsystem: "com.talvior.habitagent", category: "manual-outbox")

    private(set) var pending: [ManualInterval]
    /// Intervals the server refused for good since launch.
    private(set) var droppedCount = 0

    private let fileURL: URL
    private let send: Sender
    private let now: () -> Date
    private var backoff = Backoff()
    private var notBefore = Date.distantPast
    private var flushing = false

    init(fileURL: URL, now: @escaping () -> Date = Date.init, send: @escaping Sender) {
        self.fileURL = fileURL
        self.now = now
        self.send = send
        pending = Self.load(fileURL)
    }

    /// `~/Library/Application Support/com.talvior.habitagent/manual-intervals.json`
    static func defaultFileURL() -> URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("com.talvior.habitagent", isDirectory: true)
            .appendingPathComponent("manual-intervals.json")
    }

    /// True when there is something to send and the backoff has run out.
    var isDue: Bool {
        !pending.isEmpty && !flushing && now() >= notBefore
    }

    /// Writes the interval to disk at once. Sending is the owner's call (`flush`),
    /// made on its one-second tick, so a stopped timer reaches the file even if
    /// the process dies before the network answers.
    func enqueue(_ interval: ManualInterval) {
        pending.append(interval)
        persist()
    }

    /// Sends the oldest first, one at a time. `force` ignores the backoff.
    func flush(force: Bool = false) async {
        guard !flushing, !pending.isEmpty, force || now() >= notBefore else { return }
        flushing = true
        defer { flushing = false }
        while let head = pending.first {
            do {
                try await send(head)
                backoff.reset()
                notBefore = .distantPast
            } catch PanelAPIError.rejected(let status) {
                droppedCount += 1
                Self.log.error("manual interval refused with \(status), dropped")
            } catch {
                notBefore = now().addingTimeInterval(backoff.recordFailure())
                return
            }
            pending.removeAll { $0.key == head.key }
            persist()
        }
    }

    private func persist() {
        do {
            try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Self.encoder.encode(pending).write(to: fileURL, options: .atomic)
        } catch {
            Self.log.error("could not write the manual outbox: \(error.localizedDescription)")
        }
    }

    private static func load(_ url: URL) -> [ManualInterval] {
        guard let data = try? Data(contentsOf: url) else { return [] }
        if let intervals = try? decoder.decode([ManualInterval].self, from: data) { return intervals }
        // Not overwritten by the next write: a person can still read what was in it.
        try? FileManager.default.moveItem(at: url, to: url.appendingPathExtension("unreadable"))
        log.error("manual outbox was unreadable and was set aside")
        return []
    }

    private static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }()

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }()
}
