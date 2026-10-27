// [review:need-review] PHASE-03/240
// summary: tests of the Supplements words and values — dose and time as text, the dose typed with a comma, the create body with its optional time, the day boundary at 04:00 in a time zone, the new queued write (target, day, a stored form that reads back, forced retry without the day, a replay with no supplement API waiting), the row under More, and a scan of the feature's sources: no logger, print or dump, so a name cannot reach a log
import XCTest
@testable import HabitTracker

@MainActor
final class SupplementsFormatTests: XCTestCase {
    func testDoseAndTimeAsText() {
        XCTAssertEqual(SupplementsFormat.doseText(.stub(id: 1, dose: 400, unit: "мг")), "400 мг")
        XCTAssertEqual(SupplementsFormat.doseText(.stub(id: 1, dose: 0.5, unit: "г")), "0,5 г")
        XCTAssertEqual(SupplementsFormat.doseText(.stub(id: 1, dose: 1_000_000, unit: "МЕ")), "1000000 МЕ")
        XCTAssertEqual(SupplementsFormat.timeText("21:30:00"), "21:30")
        XCTAssertEqual(SupplementsFormat.timeText("08:05"), "08:05")
        XCTAssertNil(SupplementsFormat.timeText(nil))
        XCTAssertNil(SupplementsFormat.timeText("25:00:00"))
        XCTAssertEqual(SupplementsFormat.detail(.stub(id: 1, time: "21:30:00")), "400 мг · 21:30")
        XCTAssertEqual(SupplementsFormat.detail(.stub(id: 1)), "400 мг")
    }

    func testTheDoseAcceptsACommaAndRefusesZeroAndWords() {
        XCTAssertEqual(SupplementsFormat.parseDose("0,5"), 0.5)
        XCTAssertEqual(SupplementsFormat.parseDose(" 2.5 "), 2.5)
        XCTAssertNil(SupplementsFormat.parseDose("0"))
        XCTAssertNil(SupplementsFormat.parseDose("-1"))
        XCTAssertNil(SupplementsFormat.parseDose("много"))
        XCTAssertNil(SupplementsFormat.parseDose(""))
        XCTAssertNil(SupplementsFormat.parseDose("inf"))
    }

    func testThePayloadTrimsAndCarriesTheTimeOnlyWhenAsked() throws {
        var draft = SupplementDraft(name: "  Магний ", doseText: "400", unit: " мг ")
        XCTAssertEqual(
            try SupplementsFormat.payload(from: draft).get(),
            SupplementCreateDTO(name: "Магний", dose: 400, unit: "мг", intakeTime: nil)
        )
        draft.hasTime = true
        draft.hour = 7
        draft.minute = 5
        XCTAssertEqual(try SupplementsFormat.payload(from: draft).get().intakeTime, "07:05:00")
    }

    func testTheDayTurnsAtFourInTheMorningInThePhonesZone() {
        let utc = TimeZone(identifier: "UTC")!
        let moscow = TimeZone(identifier: "Europe/Moscow")!
        let threeFiftyNine = Date(timeIntervalSince1970: 1_793_069_999) // 2026-10-27 02:59:59 UTC
        let fourSharp = Date(timeIntervalSince1970: 1_793_073_600) // 2026-10-27 04:00:00 UTC
        XCTAssertEqual(SupplementsFormat.logicalDay(of: threeFiftyNine, timeZone: utc), "2026-10-26")
        XCTAssertEqual(SupplementsFormat.logicalDay(of: fourSharp, timeZone: utc), "2026-10-27")
        XCTAssertEqual(SupplementsFormat.logicalDay(of: threeFiftyNine, timeZone: moscow), "2026-10-27")
    }

    // MARK: The queued write

    func testTheQueuedWriteKeepsTheIdAndNotTheName() throws {
        let intake = QueuedSupplementIntake(
            supplementId: 5, intakeDate: "2026-10-26", pressedAt: Date(timeIntervalSince1970: 1_793_062_800)
        )
        let action = OutboxAction.markSupplementTaken(intake)

        XCTAssertEqual(action.target, "supplement-intake:5")
        XCTAssertEqual(action.day, "2026-10-26")
        XCTAssertFalse(action.replacesOlderOfSameTarget)
        let stored = try CacheCoding.encoder().encode(action)
        XCTAssertEqual(try CacheCoding.decoder().decode(OutboxAction.self, from: stored), action)
        XCTAssertEqual(String(decoding: stored, as: UTF8.self).contains("name"), false)
    }

    func testAForcedRetryDropsTheDay() {
        let intake = QueuedSupplementIntake(supplementId: 5, intakeDate: "2026-10-26", pressedAt: .distantPast)

        let retried = OutboxAction.markSupplementTaken(intake).forcedRetry()

        XCTAssertEqual(retried, .markSupplementTaken(QueuedSupplementIntake(supplementId: 5, intakeDate: nil, pressedAt: .distantPast)))
    }

    func testTwoPressesOfOneSupplementAreNotMerged() {
        let queue = OutboxQueue(store: InMemoryOutboxStore())
        let press = OutboxAction.markSupplementTaken(
            QueuedSupplementIntake(supplementId: 5, intakeDate: "2026-10-26", pressedAt: .distantPast)
        )

        queue.enqueue(press, label: "Принял: Магний")
        queue.enqueue(press, label: "Принял: Магний")

        XCTAssertEqual(queue.pendingCount, 2, "the server answers the second one with the first mark")
        XCTAssertTrue(queue.hasPending(sameTargetAs: press))
    }

    func testAReplayWithoutASupplementAPIWaitsInsteadOfBeingLost() async {
        let queue = OutboxQueue(store: InMemoryOutboxStore())
        queue.enqueue(
            .markSupplementTaken(QueuedSupplementIntake(supplementId: 5, intakeDate: nil, pressedAt: .distantPast)),
            label: "Принял: Магний"
        )

        await queue.flush(using: OutboxReplay(entries: NoCall(), quickMarks: NoCall(), day: NoCall()))

        XCTAssertEqual(queue.pendingCount, 1)
        XCTAssertEqual(queue.failedCount, 0)
    }

    // MARK: The screen's place

    func testTheRowSitsUnderMoreOnce() {
        XCTAssertEqual(MoreDestination.allCases.filter { $0 == .supplements }.count, 1)
        XCTAssertEqual(MoreDestination.supplements.title, "Добавки")
    }

    // MARK: Logs

    /// A supplement's name is health data. The feature writes to no log at all, so none can leak into one.
    func testNoSupplementSourceWritesToALog() throws {
        let app = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("HabitTracker")
        let sources = [
            "Features/Supplements/SupplementsFormat.swift", "Features/Supplements/SupplementsViewModel.swift",
            "Features/Supplements/SupplementsView.swift", "API/APIClient+Supplements.swift", "API/DTOs+Supplements.swift",
        ]
        let forbidden = ["Logger(", "os_log", "print(", "NSLog", "dump(", "debugPrint"]
        for path in sources {
            let url = app.appendingPathComponent(path)
            guard let text = try? String(contentsOf: url, encoding: .utf8) else {
                throw XCTSkip("sources are not readable from the test host")
            }
            for word in forbidden {
                XCTAssertFalse(text.contains(word), "\(path) uses \(word)")
            }
        }
    }
}

private struct NoCall: OutboxEntriesAPI, QuickMarksAPI, OutboxDayAPI {
    func createEntry(_ entry: EntryCreateDTO, idempotencyKey: String?) async throws -> EntryDTO { fatalError() }
    func upsertChecklistEntry(_ payload: ChecklistUpsertDTO) async throws -> EntryDTO { fatalError() }
    func fetchQuickMarks() async throws -> [QuickMarkDTO] { fatalError() }
    func tapQuickMark(id: Int, request: QuickMarkEventRequestDTO, idempotencyKey: String) async throws -> QuickMarkEventDTO { fatalError() }
    func undoQuickMarkEvent(id: Int) async throws -> QuickMarkUndoDTO { fatalError() }
    func fetchQuickMarkDayEvents(categoryId: Int) async throws -> [QuickMarkDayEventDTO] { fatalError() }
    func fetchDayUnopened(date: String) async throws -> DayDetailDTO { fatalError() }
    func setMark(date: String, itemID: UUID, _ payload: DayMarkRequestDTO) async throws -> DayMarkDTO { fatalError() }
    func recordFact(date: String, itemID: UUID, _ payload: PlanFactRequestDTO, idempotencyKey: String) async throws -> PlanFactWriteDTO { fatalError() }
    func saveNotebook(date: String, content: String) async throws { fatalError() }
}
