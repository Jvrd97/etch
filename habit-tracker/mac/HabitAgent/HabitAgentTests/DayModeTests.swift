// [review:need-review] PHASE-03/228
// summary: tests of the day mode in the floating window — the config's day_mode decodes with its source, the window says where the mode came from (schedule or hand), a decision goes to PUT /day-mode/{date} with kind and nocode both, a reset to DELETE, the window repaints from the next config after a write, and a refused write is shown instead of pretending; since #228 also: a source the window does not know does not fail the whole config, a second write while one is in flight is not sent (the window repaints only after the first, so its fields would be stale), the switcher view is locked while a write runs, and a fresh config clears «не сохранилось»
import SwiftUI
import XCTest
@testable import HabitAgent

private final class ModeStubProtocol: URLProtocol {
    nonisolated(unsafe) static var handler: ((URLRequest) -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let handler = Self.handler else { return }
        let (response, data) = handler(request)
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    static func session() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ModeStubProtocol.self]
        return URLSession(configuration: configuration)
    }
}

private func configJSON(kind: String, nocode: Bool, source: String) -> String {
    """
    {"titles_enabled": true, "sampling_seconds": 5,
     "day_mode": {"date": "2026-10-27", "kind": "\(kind)", "nocode": \(nocode), "source": "\(source)"},
     "title_rules": [], "current_task": null, "day_path": "/day/2026-10-27"}
    """
}

private func requestBody(_ request: URLRequest) -> Data {
    if let body = request.httpBody { return body }
    guard let stream = request.httpBodyStream else { return Data() }
    stream.open()
    defer { stream.close() }
    var data = Data()
    var buffer = [UInt8](repeating: 0, count: 1024)
    while stream.hasBytesAvailable {
        let count = stream.read(&buffer, maxLength: buffer.count)
        if count <= 0 { break }
        data.append(buffer, count: count)
    }
    return data
}

final class DayModeDecodingTests: XCTestCase {
    func testTheModeComesWithItsSource() throws {
        let data = Data(configJSON(kind: "work", nocode: true, source: "schedule").utf8)

        let config = try PanelAPIClient.decoder.decode(PanelConfig.self, from: data)

        XCTAssertEqual(config.dayMode, PanelDayMode(kind: "work", nocode: true, source: .schedule))
        XCTAssertEqual(config.date, "2026-10-27")
    }

    func testAServerWithoutTheFieldsStillGivesAWindow() throws {
        let json = #"{"day_mode": {"date": "2026-10-27"}, "current_task": null, "day_path": "/day/2026-10-27"}"#

        let config = try PanelAPIClient.decoder.decode(PanelConfig.self, from: Data(json.utf8))

        XCTAssertNil(config.dayMode)
    }

    func testASourceTheWindowDoesNotKnowKeepsTheTaskAndTheDateButNotTheSwitcher() throws {
        let data = Data(configJSON(kind: "work", nocode: true, source: "calendar").utf8)

        let config = try PanelAPIClient.decoder.decode(PanelConfig.self, from: data)

        XCTAssertNil(config.dayMode)
        XCTAssertEqual(config.date, "2026-10-27")
        XCTAssertEqual(config.dayPath, "/day/2026-10-27")
    }

    func testTheWindowNamesWhoDecided() {
        XCTAssertEqual(PanelDayMode(kind: "work", nocode: true, source: .schedule).sourceText, "по расписанию")
        XCTAssertEqual(PanelDayMode(kind: "vacation", nocode: false, source: .manual).sourceText, "вручную")
    }

    func testKindsHaveWordsAndAnUnknownOneIsShownAsIs() {
        XCTAssertEqual(PanelDayMode.label(of: "sick"), "Болезнь")
        XCTAssertEqual(PanelDayMode.label(of: "holiday"), "holiday")
    }
}

final class DayModeRequestTests: XCTestCase {
    private func client() -> PanelAPIClient {
        PanelAPIClient(serverAddress: "https://habit.example", apiKey: "secret", session: ModeStubProtocol.session())
    }

    func testADecisionIsPutWithBothFields() async throws {
        var seen: URLRequest?
        var sent = Data()
        ModeStubProtocol.handler = { request in
            seen = request
            sent = requestBody(request)
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Data())
        }

        try await client().change(mode: .decide(kind: "vacation", nocode: true), date: "2026-10-27")

        XCTAssertEqual(seen?.httpMethod, "PUT")
        XCTAssertEqual(seen?.url?.absoluteString, "https://habit.example/api/v1/day-mode/2026-10-27")
        XCTAssertEqual(seen?.value(forHTTPHeaderField: "X-API-Key"), "secret")
        let body = try JSONSerialization.jsonObject(with: sent) as? [String: Any]
        XCTAssertEqual(body?["kind"] as? String, "vacation")
        XCTAssertEqual(body?["nocode"] as? Bool, true)
    }

    func testAResetIsADelete() async throws {
        var seen: URLRequest?
        ModeStubProtocol.handler = { request in
            seen = request
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Data())
        }

        try await client().change(mode: .reset, date: "2026-10-27")

        XCTAssertEqual(seen?.httpMethod, "DELETE")
        XCTAssertEqual(seen?.url?.path, "/api/v1/day-mode/2026-10-27")
    }

    func testARefusalIsAnError() async {
        ModeStubProtocol.handler = { request in
            (HTTPURLResponse(url: request.url!, statusCode: 422, httpVersion: nil, headerFields: nil)!, Data())
        }

        do {
            try await client().change(mode: .decide(kind: "holiday", nocode: false), date: "2026-10-27")
            XCTFail("expected a refusal")
        } catch {
            XCTAssertEqual(error as? PanelAPIError, .rejected(status: 422))
        }
    }
}

@MainActor
final class DayModeModelTests: XCTestCase {
    private struct Refused: Error {}

    @MainActor private final class World {
        var mode = PanelDayMode(kind: "work", nocode: true, source: .schedule)
        var writes: [(String, ModeChange)] = []
        var refuse = false
        /// While `holdWrites` is set, every write waits here until the test lets it go.
        var gates: [CheckedContinuation<Void, Never>] = []
        var holdWrites = false
        var model: PanelModel!

        init() {
            let poller = ConditionalPoller<PanelConfig>(interval: 30, staleAfter: 120, maxRetryDelay: 60, sleep: { _ in }) { [unowned self] _ in
                .modified(PanelConfig(currentTask: nil, dayPath: "/day/2026-10-27", date: "2026-10-27", dayMode: mode), etag: nil)
            }
            model = PanelModel(
                config: poller,
                timer: TaskTimer(emit: { _ in }),
                serverAddress: { "https://habit.example" },
                openURL: { _ in },
                modeWrite: { [unowned self] date, change in
                    if refuse { throw Refused() }
                    writes.append((date, change))
                    if holdWrites { await withCheckedContinuation { gates.append($0) } }
                    switch change {
                    case let .decide(kind, nocode): mode = PanelDayMode(kind: kind, nocode: nocode, source: .manual)
                    case .reset: mode = PanelDayMode(kind: "work", nocode: true, source: .schedule)
                    }
                }
            )
        }
    }

    func testTheWindowShowsTheModeAndWhereItCameFrom() async {
        let world = World()
        await world.model.config.pollOnce()

        XCTAssertEqual(world.model.dayMode?.kind, "work")
        XCTAssertEqual(world.model.dayMode?.nocode, true)
        XCTAssertEqual(world.model.dayMode?.sourceText, "по расписанию")
    }

    func testADecisionIsWrittenForTheDateOfTheWindowAndRepainted() async {
        let world = World()
        await world.model.config.pollOnce()

        await world.model.decideMode(kind: "vacation", nocode: true)

        XCTAssertEqual(world.writes.first?.0, "2026-10-27")
        XCTAssertEqual(world.writes.first?.1, .decide(kind: "vacation", nocode: true))
        XCTAssertEqual(world.model.dayMode?.kind, "vacation")
        XCTAssertEqual(world.model.dayMode?.sourceText, "вручную")
    }

    func testNocodeFlipsWithoutTheKind() async {
        let world = World()
        await world.model.config.pollOnce()

        await world.model.decideMode(kind: "work", nocode: false)

        XCTAssertEqual(world.model.dayMode?.kind, "work")
        XCTAssertEqual(world.model.dayMode?.nocode, false)
    }

    func testAResetGivesTheDayBackToTheSchedule() async {
        let world = World()
        world.mode = PanelDayMode(kind: "sick", nocode: false, source: .manual)
        await world.model.config.pollOnce()

        await world.model.resetMode()

        XCTAssertEqual(world.writes.first?.1, .reset)
        XCTAssertEqual(world.model.dayMode?.sourceText, "по расписанию")
    }

    func testARefusedWriteKeepsTheModeAndSaysSo() async {
        let world = World()
        await world.model.config.pollOnce()
        world.refuse = true

        await world.model.decideMode(kind: "dayoff", nocode: false)

        XCTAssertEqual(world.model.dayMode?.kind, "work")
        XCTAssertTrue(world.model.modeWriteFailed)
    }

    func testASecondWriteWhileOneIsInFlightIsNotSentAndDoesNotUndoTheFirst() async {
        // «Выключил no-code, сразу выбрал отпуск»: the second change is built from the
        // mode still on screen (no-code on) and would switch the first one back.
        let world = World()
        await world.model.config.pollOnce()
        world.holdWrites = true

        let first = Task { await world.model.decideMode(kind: "work", nocode: false) }
        while world.gates.isEmpty { await Task.yield() }
        XCTAssertTrue(world.model.modeSaving)
        let second = Task { await world.model.decideMode(kind: "vacation", nocode: true) }
        for _ in 0..<20 { await Task.yield() }
        world.holdWrites = false
        world.gates.forEach { $0.resume() }
        await first.value
        await second.value

        XCTAssertEqual(world.writes.count, 1)
        XCTAssertEqual(world.writes.first?.1, .decide(kind: "work", nocode: false))
        XCTAssertEqual(world.model.dayMode?.nocode, false)
        XCTAssertFalse(world.model.modeSaving)
    }

    func testAFreshConfigClearsTheNoteThatTheWriteDidNotGoThrough() async {
        let world = World()
        await world.model.config.pollOnce()
        world.refuse = true
        await world.model.decideMode(kind: "dayoff", nocode: false)
        XCTAssertTrue(world.model.modeWriteFailed)

        await world.model.config.pollOnce()

        XCTAssertFalse(world.model.modeWriteFailed)
    }
}

/// The view is drawn into a real `NSHostingView`: SwiftUI hosts its picker, switch and
/// link button as AppKit controls there, so what the person can press is countable
/// and its `isEnabled` is the lock.
@MainActor
final class ModeSwitcherViewTests: XCTestCase {
    private final class Gate {
        var continuation: CheckedContinuation<Void, Never>?
    }

    private func model(mode: PanelDayMode?, gate: Gate? = nil) async -> PanelModel {
        let poller = ConditionalPoller<PanelConfig>(interval: 30, staleAfter: 120, maxRetryDelay: 60, sleep: { _ in }) { _ in
            .modified(PanelConfig(currentTask: nil, dayPath: "/day/2026-10-27", date: "2026-10-27", dayMode: mode), etag: nil)
        }
        let model = PanelModel(
            config: poller,
            timer: TaskTimer(emit: { _ in }),
            serverAddress: { nil },
            openURL: { _ in },
            modeWrite: { _, _ in
                if let gate { await withCheckedContinuation { gate.continuation = $0 } }
            }
        )
        await poller.pollOnce()
        return model
    }

    private func controls(of model: PanelModel) -> [NSControl] {
        let host = NSHostingView(rootView: ModeSwitcher(model: model))
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 320, height: 120), styleMask: [.titled], backing: .buffered, defer: false)
        window.contentView = host
        RunLoop.main.run(until: Date().addingTimeInterval(0.05))
        host.layoutSubtreeIfNeeded()
        func collect(_ view: NSView) -> [NSControl] {
            let own = (view as? NSControl).map { [$0] } ?? []
            return own + view.subviews.flatMap(collect)
        }
        return collect(host)
    }

    func testNothingIsDrawnForAServerThatSendsNoMode() async {
        let found = controls(of: await model(mode: nil))

        XCTAssertTrue(found.isEmpty)
    }

    func testAScheduleDayDrawsTheKindAndTheSwitchWithoutAWayBack() async {
        let found = controls(of: await model(mode: PanelDayMode(kind: "work", nocode: true, source: .schedule)))

        XCTAssertEqual(found.count, 2)
        XCTAssertTrue(found.allSatisfy(\.isEnabled))
    }

    func testADayDecidedByHandAlsoOffersTheWayBackToTheSchedule() async {
        let found = controls(of: await model(mode: PanelDayMode(kind: "sick", nocode: false, source: .manual)))

        XCTAssertEqual(found.count, 3)
        XCTAssertTrue(found.allSatisfy(\.isEnabled))
    }

    func testEveryControlIsLockedWhileAWriteRuns() async {
        let gate = Gate()
        let panel = await model(mode: PanelDayMode(kind: "sick", nocode: false, source: .manual), gate: gate)

        let write = Task { await panel.decideMode(kind: "work", nocode: true) }
        while gate.continuation == nil { await Task.yield() }
        let locked = controls(of: panel)
        gate.continuation?.resume()
        await write.value
        let unlocked = controls(of: panel)

        XCTAssertEqual(locked.count, 3)
        XCTAssertTrue(locked.allSatisfy { !$0.isEnabled })
        XCTAssertTrue(unlocked.allSatisfy(\.isEnabled))
    }
}
