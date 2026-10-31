// [review:need-review] PHASE-03/170
// summary: tests of the quick marks row — four buttons plus «ещё» out of any number of marks, the repaint from the answer to a tap without a second GET, a tap made offline shown as accepted and sent once under one Idempotency-Key, the poll cadence of the contract, and the two requests on the wire
import XCTest
@testable import HabitAgent

// MARK: - The row

@MainActor
final class QuickMarksModelTests: XCTestCase {
    private struct Down: Error {}

    /// A server the test moves by hand: it keeps the day's totals, counts the calls it gets
    /// and, like the real one, answers a repeated Idempotency-Key with the first event.
    @MainActor private final class Server {
        var marks: [QuickMark]
        var online = true
        private(set) var fetches = 0
        private(set) var posts: [QuickMarkTap] = []
        private var recorded: [UUID: QuickMarkEventResult] = [:]
        /// What the answer to a tap carries, when a test wants it to differ from the plain sum.
        var answerTotal: ((QuickMark) -> Double)?

        init(marks: [QuickMark]) { self.marks = marks }

        func fetch(_ etag: String?) async throws -> PollResponse<[QuickMark]> {
            fetches += 1
            guard online else { throw Down() }
            return .modified(marks, etag: "\"v\(fetches)\"")
        }

        func post(_ tap: QuickMarkTap) async throws -> QuickMarkEventResult {
            guard online else { throw Down() }
            posts.append(tap)
            if let first = recorded[tap.key] { return first }
            guard let index = marks.firstIndex(where: { $0.id == tap.markID }) else { throw PanelAPIError.rejected(status: 404) }
            let total = answerTotal?(marks[index]) ?? ((marks[index].todayTotal ?? 0) + (marks[index].step ?? 1))
            marks[index].todayTotal = marks[index].kind == "check" ? nil : total
            marks[index].done = true
            let result = QuickMarkEventResult(
                quickMarkID: tap.markID, entryDate: marks[index].entryDate,
                todayTotal: marks[index].todayTotal, done: true
            )
            recorded[tap.key] = result
            return result
        }
    }

    private var directory: URL!
    private var file: URL { directory.appendingPathComponent("quick-mark-taps.json") }
    private var clock = Date(timeIntervalSince1970: 1_800_000_000)
    private var opened: [URL] = []

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("quick-marks-\(UUID().uuidString)", isDirectory: true)
        opened = []
        clock = Date(timeIntervalSince1970: 1_800_000_000)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: directory)
    }

    private func mark(_ id: Int, _ label: String, kind: String = "increment", step: Double? = 250, unit: String? = "мл", total: Double? = 0) -> QuickMark {
        QuickMark(
            id: id, label: label, icon: nil, color: nil, kind: kind, step: step, unitLabel: unit,
            entryDate: "2026-10-31", todayTotal: total, done: false
        )
    }

    private func model(_ server: Server, sleep: @escaping ConditionalPoller<[QuickMark]>.Sleep = { _ in try await Task.sleep(nanoseconds: 3_600_000_000_000) }) -> QuickMarksModel {
        QuickMarksModel(
            outboxFile: file,
            serverAddress: { "https://habit.example" },
            openURL: { [unowned self] in opened.append($0) },
            now: { [unowned self] in clock },
            sleep: sleep,
            fetch: { try await server.fetch($0) },
            post: { try await server.post($0) }
        )
    }

    /// The first poll, as the loop would make it.
    private func loaded(_ server: Server) async -> QuickMarksModel {
        let model = model(server)
        await model.poller.pollOnce()
        return model
    }

    // MARK: Four buttons

    func testSixMarksGiveFourButtonsAndMore() async {
        let server = Server(marks: (1...6).map { mark($0, "М\($0)") })
        let model = await loaded(server)

        XCTAssertEqual(model.buttons.map(\.label), ["М1", "М2", "М3", "М4"], "the server's order, cut at four")
        XCTAssertTrue(model.showsMore)
    }

    func testFewMarksAreAllDrawnAndMoreIsStillThere() async {
        let server = Server(marks: [mark(1, "Вода")])
        let model = await loaded(server)

        XCTAssertEqual(model.buttons.map(\.label), ["Вода"])
        XCTAssertTrue(model.showsMore, "the fifth place is always the way to the page of marks")
    }

    func testMoreOpensThePageOfMarksInTheBrowser() async {
        let model = await loaded(Server(marks: []))
        model.openMore()
        XCTAssertEqual(opened.map(\.absoluteString), ["https://habit.example/quick-marks"])
    }

    func testAButtonShowsTheTotalWithItsUnit() async {
        let server = Server(marks: [mark(1, "Вода", total: 750), mark(2, "Таблетка", kind: "check", step: nil, unit: nil, total: nil)])
        let model = await loaded(server)

        XCTAssertEqual(model.buttons[0].countText, "750 мл")
        XCTAssertEqual(model.buttons[1].countText, "–", "a tick not yet made")
    }

    func testAMarkAddedInTheWebAppearsOnTheNextPollWithoutARebuild() async {
        let server = Server(marks: [mark(1, "Вода")])
        let model = await loaded(server)
        server.marks.append(mark(2, "Кофе", step: 1, unit: "чаш"))

        await model.poller.pollOnce()

        XCTAssertEqual(model.buttons.map(\.label), ["Вода", "Кофе"])
    }

    // MARK: Tap

    func testATapRepaintsFromTheAnswerAndMakesNoSecondGet() async throws {
        let server = Server(marks: [mark(1, "Вода", total: 500)])
        server.answerTotal = { _ in 900 }
        let model = await loaded(server)
        let fetchesBefore = server.fetches

        try await XCTUnwrap(model.tap(1)).value

        XCTAssertEqual(server.posts.count, 1)
        XCTAssertEqual(server.posts[0].markID, 1)
        XCTAssertEqual(model.buttons[0].countText, "900 мл", "painted from the answer, not from 500 + 250")
        XCTAssertFalse(model.buttons[0].isPending)
        XCTAssertEqual(server.fetches, fetchesBefore, "the answer to the tap is enough")
    }

    func testTheNextPollTakesOverFromTheAnswer() async throws {
        let server = Server(marks: [mark(1, "Вода", total: 500)])
        let model = await loaded(server)
        server.answerTotal = { _ in 750 }
        server.marks[0].todayTotal = 500

        try await XCTUnwrap(model.tap(1)).value
        // The next regular poll asks again and the server now says 750, as the answer did.
        await model.poller.pollOnce()

        XCTAssertEqual(model.buttons[0].countText, "750 мл")
    }

    func testATapOnATickWritesWithoutAValueAndMarksItDone() async throws {
        let server = Server(marks: [mark(1, "Таблетка", kind: "check", step: nil, unit: nil, total: nil)])
        let model = await loaded(server)

        try await XCTUnwrap(model.tap(1)).value

        XCTAssertTrue(model.buttons[0].isDone)
        XCTAssertEqual(model.buttons[0].countText, "✓")
    }

    func testATapOnAnUnknownMarkDoesNothing() async {
        let server = Server(marks: [mark(1, "Вода")])
        let model = await loaded(server)
        XCTAssertNil(model.tap(99))
        XCTAssertTrue(server.posts.isEmpty)
    }

    // MARK: Offline

    func testATapWithoutNetworkIsShownAcceptedAndPending() async throws {
        let server = Server(marks: [mark(1, "Вода", total: 500)])
        let model = await loaded(server)
        server.online = false

        try await XCTUnwrap(model.tap(1)).value

        XCTAssertEqual(model.buttons[0].countText, "750 мл", "the tap is counted at once")
        XCTAssertTrue(model.buttons[0].isPending, "and said to be unsent")
        XCTAssertEqual(model.pendingCount, 1)
        XCTAssertTrue(server.posts.isEmpty)
    }

    func testATapMadeOfflineReachesTheServerExactlyOnceAfterTheNetworkReturns() async throws {
        let server = Server(marks: [mark(1, "Вода", total: 500)])
        let model = await loaded(server)
        server.online = false
        try await XCTUnwrap(model.tap(1)).value
        let key = try XCTUnwrap(model.outbox.pending.first?.key)

        // The backoff runs out and the network is back.
        server.online = true
        clock = clock.addingTimeInterval(600)
        XCTAssertTrue(model.outbox.isDue)
        await model.outbox.flush()
        // A lost answer makes the next flush send the same tap again; the key makes it one event.
        await model.outbox.flush()

        XCTAssertEqual(server.posts.map(\.key), [key])
        XCTAssertEqual(model.pendingCount, 0)
        XCTAssertFalse(model.buttons[0].isPending)
        XCTAssertEqual(model.buttons[0].countText, "750 мл")
    }

    func testTheMomentOfThePressTravelsWithAQueuedTap() async throws {
        let server = Server(marks: [mark(1, "Вода")])
        let model = await loaded(server)
        server.online = false
        let pressed = clock
        try await XCTUnwrap(model.tap(1)).value

        clock = clock.addingTimeInterval(3600)
        server.online = true
        await model.outbox.flush(force: true)

        XCTAssertEqual(server.posts.first?.occurredAt, pressed, "a tap that arrives an hour late still says when it was made")
    }

    func testQueuedTapsSurviveARestart() async throws {
        let server = Server(marks: [mark(1, "Вода")])
        let model = await loaded(server)
        server.online = false
        try await XCTUnwrap(model.tap(1)).value

        let reborn = await loaded(Server(marks: [mark(1, "Вода")]))
        XCTAssertEqual(reborn.pendingCount, 1)
    }

    func testAnOnlineTapAfterAFailedOneKeepsTheOrder() async throws {
        let server = Server(marks: [mark(1, "Вода", total: 0)])
        let model = await loaded(server)
        server.online = false
        try await XCTUnwrap(model.tap(1)).value
        server.online = true
        try await XCTUnwrap(model.tap(1)).value
        XCTAssertEqual(model.pendingCount, 2, "the backoff of the first failure has not run out: both wait")

        clock = clock.addingTimeInterval(600)
        await model.outbox.flush()

        XCTAssertEqual(server.posts.count, 2)
        XCTAssertEqual(model.pendingCount, 0)
        XCTAssertEqual(model.buttons[0].countText, "500 мл")
    }

    func testATapTheServerRefusesForGoodIsDroppedAndSaid() async throws {
        let server = Server(marks: [mark(1, "Вода")])
        let model = await loaded(server)
        server.marks = []   // the mark was deleted in the web; the window has not polled yet

        try await XCTUnwrap(model.tap(1)).value
        model.tick()

        XCTAssertEqual(model.pendingCount, 0, "a 404 will not pass by waiting")
        XCTAssertTrue(model.rejectedNote)
    }

    // MARK: Freshness and cadence

    func testTheCadenceIsTheOneInTheContract() async {
        let model = await loaded(Server(marks: []))
        XCTAssertEqual(model.poller.interval, 15)
        XCTAssertEqual(model.poller.staleAfter, 60)
        // 15 s → 30 s → 60 s, then 60 s until the server answers.
        let server = Server(marks: [])
        server.online = false
        let failing = self.model(server)
        var delays: [TimeInterval] = []
        for _ in 0..<5 {
            await failing.poller.pollOnce()
            delays.append(failing.poller.nextDelay)
        }
        XCTAssertEqual(delays, [15, 30, 60, 60, 60])
    }

    func testAnUnreachableServerKeepsTheLastListAndSaysItIsNotFresh() async {
        let server = Server(marks: [mark(1, "Вода", total: 500)])
        let model = await loaded(server)
        model.tick()
        XCTAssertFalse(model.isStale)

        server.online = false
        clock = clock.addingTimeInterval(61)
        await model.poller.pollOnce()
        model.tick()

        XCTAssertTrue(model.isStale)
        XCTAssertEqual(model.buttons.map(\.label), ["Вода"], "the buttons stay")
        XCTAssertEqual(model.buttons[0].countText, "500 мл")
    }

    func testAHiddenWindowDoesNotPoll() async throws {
        let server = Server(marks: [mark(1, "Вода")])
        let model = model(server)

        model.startPolling()
        for _ in 0..<200 where server.fetches == 0 { await Task.yield() }
        XCTAssertEqual(server.fetches, 1, "shown: one poll at once")

        model.stopPolling()
        let seen = server.fetches
        await Task.yield()
        XCTAssertEqual(server.fetches, seen)

        model.startPolling()
        for _ in 0..<200 where server.fetches == seen { await Task.yield() }
        XCTAssertEqual(server.fetches, seen + 1, "shown again: asks at once")
        model.stopPolling()
    }
}

// MARK: - Glyph and numbers

final class QuickMarkButtonTests: XCTestCase {
    func testWholeNumbersHaveNoFraction() {
        XCTAssertEqual(QuickMarkButton.format(750), "750")
        XCTAssertEqual(QuickMarkButton.format(1.5), "1.5")
    }

    func testAnUnknownIconFallsBackToTheFirstLetterOfTheLabel() {
        XCTAssertEqual(QuickMarkGlyph.resolve(icon: "no-such-glyph-name", label: "вода"), .letter("В"))
        XCTAssertEqual(QuickMarkGlyph.resolve(icon: nil, label: "вода"), .letter("В"))
        XCTAssertEqual(QuickMarkGlyph.resolve(icon: "💧", label: "вода"), .emoji("💧"))
        XCTAssertEqual(QuickMarkGlyph.resolve(icon: "drop.fill", label: "вода"), .symbol("drop.fill"))
    }

    func testAColorMustBeSixHexDigits() {
        XCTAssertNotNil(QuickMarkGlyph.rgb(of: "#1a2b3c"))
        XCTAssertNil(QuickMarkGlyph.rgb(of: "red"))
        XCTAssertNil(QuickMarkGlyph.rgb(of: "#12345"))
    }
}

// MARK: - On the wire

private final class QuickMarksStub: URLProtocol {
    nonisolated(unsafe) static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        do {
            let (response, data) = try XCTUnwrap(Self.handler)(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}

    static func session() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [QuickMarksStub.self]
        return URLSession(configuration: configuration)
    }
}

private func stubReply(_ request: URLRequest, status: Int, headers: [String: String] = [:], body: String = "") -> (HTTPURLResponse, Data) {
    (HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: headers)!, Data(body.utf8))
}

private func bodyData(of request: URLRequest) -> Data {
    guard let stream = request.httpBodyStream else { return request.httpBody ?? Data() }
    stream.open()
    defer { stream.close() }
    var data = Data()
    var buffer = [UInt8](repeating: 0, count: 4096)
    while stream.hasBytesAvailable {
        let count = stream.read(&buffer, maxLength: buffer.count)
        if count <= 0 { break }
        data.append(buffer, count: count)
    }
    return data
}

private let marksJSON = """
[
  {"id": 7, "label": "Вода", "category_id": 3, "field_id": 4, "kind": "increment", "step": 250.0,
   "unit_label": "мл", "icon": "drop.fill", "color": "#3b82f6", "hotkey": "w", "order": 0,
   "show_in_agent": true, "is_active": true, "entry_date": "2026-10-31", "today_total": 750.0,
   "done": true, "planned": false, "plan_item_id": null},
  {"id": 8, "label": "Таблетка", "category_id": 3, "field_id": 5, "kind": "check", "step": null,
   "unit_label": null, "icon": null, "color": null, "hotkey": null, "order": 1,
   "show_in_agent": true, "is_active": true, "entry_date": "2026-10-31", "today_total": null,
   "done": false, "planned": true, "plan_item_id": "0b8f1c52-6d77-4c0e-9d0a-2f6a1f3a9b10"}
]
"""

final class QuickMarksAPITests: XCTestCase {
    private func client() -> AgentAPIClient {
        AgentAPIClient(serverAddress: "https://habit.example", apiKey: "secret", session: QuickMarksStub.session())
    }

    func testTheListIsAskedForTheAgentSurfaceWithTheKeyAndTheLastETagAndWithoutADate() async throws {
        var seen: URLRequest?
        QuickMarksStub.handler = { request in
            seen = request
            return stubReply(request, status: 200, headers: ["ETag": "\"abc\""], body: marksJSON)
        }

        let answer = try await client().fetchQuickMarks(etag: "\"old\"")

        XCTAssertEqual(seen?.httpMethod, "GET")
        XCTAssertEqual(seen?.url?.absoluteString, "https://habit.example/api/v1/quick-marks?surface=agent")
        XCTAssertEqual(seen?.value(forHTTPHeaderField: "X-API-Key"), "secret")
        XCTAssertEqual(seen?.value(forHTTPHeaderField: "If-None-Match"), "\"old\"")
        guard case let .modified(marks, etag) = answer else { return XCTFail("expected a body") }
        XCTAssertEqual(etag, "\"abc\"")
        XCTAssertEqual(marks.map(\.id), [7, 8])
        XCTAssertEqual(marks[0].step, 250)
        XCTAssertEqual(marks[0].unitLabel, "мл")
        XCTAssertEqual(marks[0].todayTotal, 750)
        XCTAssertTrue(marks[0].done)
        XCTAssertNil(marks[1].todayTotal)
        XCTAssertEqual(marks[1].entryDate, "2026-10-31")
    }

    func testAnUnchangedListIs304() async throws {
        QuickMarksStub.handler = { stubReply($0, status: 304) }
        let answer = try await client().fetchQuickMarks(etag: "\"x\"")
        XCTAssertEqual(answer, .notModified)
    }

    func testARefusedListIsAnErrorTheCallerRetriesLater() async {
        QuickMarksStub.handler = { stubReply($0, status: 503) }
        do {
            _ = try await client().fetchQuickMarks(etag: nil)
            XCTFail("expected an error")
        } catch {
            XCTAssertEqual(error as? PanelAPIError, .http(status: 503))
        }
    }

    func testATapIsPostedFromTheAgentUnderItsKeyWithTheMomentOfThePress() async throws {
        var seen: URLRequest?
        QuickMarksStub.handler = { request in
            seen = request
            return stubReply(request, status: 201, body: """
            {"event_id": 5, "quick_mark_id": 7, "entry_id": 9, "entry_date": "2026-10-31",
             "occurred_at": "2026-10-31T09:00:00Z", "today_total": 1000.0, "done": true}
            """)
        }
        let tap = QuickMarkTap(
            key: UUID(uuidString: "11111111-2222-3333-4444-555555555555")!, markID: 7,
            occurredAt: Date(timeIntervalSince1970: 1_792_915_200), utcOffsetMinutes: 180
        )

        let result = try await client().send(tap)

        XCTAssertEqual(seen?.httpMethod, "POST")
        XCTAssertEqual(seen?.url?.absoluteString, "https://habit.example/api/v1/quick-marks/7/events")
        XCTAssertEqual(seen?.value(forHTTPHeaderField: "Idempotency-Key"), "11111111-2222-3333-4444-555555555555")
        XCTAssertEqual(seen?.value(forHTTPHeaderField: "X-API-Key"), "secret")
        let sent = try XCTUnwrap(JSONSerialization.jsonObject(with: bodyData(of: try XCTUnwrap(seen))) as? [String: Any])
        XCTAssertEqual(sent["source"] as? String, "agent")
        XCTAssertEqual(sent["utc_offset_minutes"] as? Int, 180)
        XCTAssertEqual(sent["occurred_at"] as? String, "2026-10-25T08:00:00Z")
        XCTAssertNil(sent["value"], "without a value the server applies the step of the button")
        XCTAssertNil(sent["entry_date"], "the day is the server's call")
        XCTAssertEqual(result, QuickMarkEventResult(quickMarkID: 7, entryDate: "2026-10-31", todayTotal: 1000, done: true))
    }

    func testARepeatedKeyAnswers200WithTheSameEvent() async throws {
        QuickMarksStub.handler = { request in
            stubReply(request, status: 200, body: """
            {"event_id": 5, "quick_mark_id": 7, "entry_id": 9, "entry_date": "2026-10-31",
             "occurred_at": "2026-10-31T09:00:00Z", "today_total": 1000.0, "done": true}
            """)
        }
        let tap = QuickMarkTap(key: UUID(), markID: 7, occurredAt: Date(), utcOffsetMinutes: 0)
        let result = try await client().send(tap)
        XCTAssertEqual(result.todayTotal, 1000)
    }

    func testRefusalsThatRepeatAreFinalAndTheRestAreRetried() async {
        let tap = QuickMarkTap(key: UUID(), markID: 7, occurredAt: Date(), utcOffsetMinutes: 0)
        for (status, expected) in [(404, PanelAPIError.rejected(status: 404)), (409, .rejected(status: 409)),
                                   (422, .rejected(status: 422)), (401, .http(status: 401)), (500, .http(status: 500))] {
            QuickMarksStub.handler = { stubReply($0, status: status) }
            do {
                _ = try await client().send(tap)
                XCTFail("\(status) must throw")
            } catch {
                XCTAssertEqual(error as? PanelAPIError, expected, "status \(status)")
            }
        }
    }
}
