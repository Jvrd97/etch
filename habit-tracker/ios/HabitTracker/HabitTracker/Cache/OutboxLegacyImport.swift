// [review:need-review] PHASE-03/225
// summary: one-time carry-over of the two queues that came before the shared outbox — quick-mark presses from quick-mark-taps.json and entry creates from the SwiftData default store — into OutboxQueue under their own Idempotency-Keys, so an update installed while writes wait loses none of them
import Foundation
import SwiftData
import os

/// One queued entry create as the first outbox (#12) stored it in the default SwiftData store.
/// Kept only so `OutboxLegacyImport` can read what an older build left behind.
@Model
final class PendingEntryRecord {
    @Attribute(.unique) var id: UUID
    var payload: Data
    var createdAt: Date
    var attempts: Int
    var statusRaw: String

    init(id: UUID, payload: Data, createdAt: Date, attempts: Int, statusRaw: String) {
        self.id = id
        self.payload = payload
        self.createdAt = createdAt
        self.attempts = attempts
        self.statusRaw = statusRaw
    }
}

@MainActor
enum OutboxLegacyImport {
    private static let logger = Logger(subsystem: "com.habittracker.app", category: "OutboxLegacyImport")
    static let doneDefaultsKey = "outbox.legacyImport.done"
    static let tapFileName = "quick-mark-taps.json"
    static let tapLabel = "Быстрая отметка"
    static let entryLabel = "Запись"

    /// A press as the old tap queue (#210) stored it.
    private struct LegacyTap: Decodable {
        let id: UUID
        let quickMarkId: Int
        let categoryId: Int
        let createdAt: Date
        let utcOffsetMinutes: Int
    }

    /// Runs both imports once per install. The entry import opens the default store with the same
    /// schema the old outbox did, so it changes nothing the old build did not do on every launch.
    static func runOnce(directory: URL, into queue: OutboxQueue, defaults: UserDefaults = .standard) {
        guard !defaults.bool(forKey: doneDefaultsKey) else { return }
        importTaps(from: directory.appendingPathComponent(tapFileName), into: queue)
        do {
            let container = try ModelContainer(
                for: PendingEntryRecord.self, configurations: ModelConfiguration(isStoredInMemoryOnly: false)
            )
            importEntries(from: ModelContext(container), into: queue)
        } catch {
            logger.error("Old entry queue unreadable: \(String(describing: error))")
        }
        defaults.set(true, forKey: doneDefaultsKey)
    }

    /// The old presses, replayed to the server's today: the old queue did not know their day.
    static func importTaps(from url: URL, into queue: OutboxQueue) {
        guard let data = try? Data(contentsOf: url) else { return }
        do {
            for tap in try CacheCoding.decoder().decode([LegacyTap].self, from: data) {
                queue.restore(
                    .tapQuickMark(
                        QueuedTap(
                            quickMarkId: tap.quickMarkId, categoryId: tap.categoryId,
                            utcOffsetMinutes: tap.utcOffsetMinutes, serverDay: nil
                        )
                    ),
                    key: tap.id.uuidString, label: tapLabel, createdAt: tap.createdAt
                )
            }
            try FileManager.default.removeItem(at: url)
        } catch {
            logger.error("Old tap queue import failed: \(String(describing: error))")
        }
    }

    static func importEntries(from context: ModelContext, into queue: OutboxQueue) {
        do {
            let records = try context.fetch(
                FetchDescriptor<PendingEntryRecord>(sortBy: [SortDescriptor(\.createdAt, order: .forward)])
            )
            for record in records {
                let payload = try CacheCoding.decoder().decode(EntryCreateDTO.self, from: record.payload)
                queue.restore(
                    .createEntry(payload), key: record.id.uuidString, label: entryLabel, createdAt: record.createdAt
                )
                context.delete(record)
            }
            try context.save()
        } catch {
            logger.error("Old entry queue import failed: \(String(describing: error))")
        }
    }
}
