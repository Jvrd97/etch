// [review:need-review] PHASE-03/155, PHASE-03/217
// summary: verifies coalescing, micro-switches under 30 seconds, closing at the moment of leaving, the silence gap, dropped titles and the checkpoint that bounds what a kill can lose
import XCTest
@testable import HabitAgent

final class IntervalBuilderTests: XCTestCase {
    private let start = Date(timeIntervalSince1970: 1_800_000_000)
    private let editor = "com.example.editor"
    private let browser = "com.example.browser"
    private let chat = "com.example.chat"

    private func at(_ seconds: TimeInterval) -> Date { start.addingTimeInterval(seconds) }

    private func feed(_ builder: inout IntervalBuilder, _ sightings: [(String, TimeInterval)]) -> [ActivityInterval] {
        sightings.flatMap { builder.record(AppSighting(bundleID: $0.0, date: at($0.1))) }
    }

    func testSightingsOfOneAppFormOneTitleFreeIntervalWithoutSwitches() {
        var builder = IntervalBuilder()
        XCTAssertTrue(feed(&builder, [(editor, 0), (editor, 5), (editor, 10)]).isEmpty)
        let intervals = builder.finish(at: at(12))
        XCTAssertEqual(intervals.count, 1)
        XCTAssertEqual(intervals.first?.startedAt, start)
        XCTAssertEqual(intervals.first?.endedAt, at(12))
        XCTAssertEqual(intervals.first?.switchCount, 0)
        XCTAssertNil(intervals.first?.title)
        XCTAssertEqual(intervals.first?.titleSource, "dropped")
    }

    func testTwentyMinutesInOneAppCountNoSwitches() {
        var builder = IntervalBuilder()
        let ticks = stride(from: 0.0, through: 1200, by: IntervalBuilder.continuityWindow / 6).map { (editor, $0) }
        XCTAssertTrue(feed(&builder, ticks).isEmpty)
        XCTAssertEqual(builder.finish(at: at(1200)).map(\.switchCount), [0])
    }

    func testReturnWithinThirtySecondsIsAMicroSwitchInsideTheInterval() {
        var builder = IntervalBuilder()
        let closed = feed(&builder, [(editor, 0), (editor, 5), (browser, 8), (browser, 13), (editor, 37), (browser, 40), (editor, 45)])
        XCTAssertTrue(closed.isEmpty)
        let intervals = builder.finish(at: at(50))
        XCTAssertEqual(intervals.map(\.bundleID), [editor])
        XCTAssertEqual(intervals.first?.startedAt, start)
        XCTAssertEqual(intervals.first?.endedAt, at(50))
        XCTAssertEqual(intervals.first?.switchCount, 2)
    }

    func testVisitOfThirtySecondsClosesTheIntervalAtTheMomentOfLeaving() {
        var builder = IntervalBuilder()
        let closed = feed(&builder, [(editor, 0), (editor, 5), (browser, 7), (browser, 12), (browser, 37)])
        XCTAssertEqual(closed.map(\.bundleID), [editor])
        XCTAssertEqual(closed.first?.endedAt, at(7))
        XCTAssertEqual(closed.first?.switchCount, 0)
        let rest = builder.finish(at: at(40))
        XCTAssertEqual(rest.map(\.bundleID), [browser])
        XCTAssertEqual(rest.first?.startedAt, at(7))
        XCTAssertEqual(rest.first?.endedAt, at(40))
    }

    func testVisitThatLeadsToAThirdAppKeepsEveryAppItsOwnTime() {
        var builder = IntervalBuilder()
        let closed = feed(&builder, [(editor, 0), (browser, 10), (chat, 15)])
        XCTAssertEqual(closed.map(\.bundleID), [editor])
        XCTAssertEqual(closed.first?.endedAt, at(10))
        let rest = builder.finish(at: at(20))
        XCTAssertEqual(rest.map(\.bundleID), [browser, chat])
        XCTAssertEqual(rest.map(\.startedAt), [at(10), at(15)])
        XCTAssertEqual(rest.map(\.endedAt), [at(15), at(20)])
    }

    func testSilenceOfThirtySecondsEndsTheIntervalAtTheLastSighting() {
        var builder = IntervalBuilder()
        let closed = feed(&builder, [(editor, 0), (editor, 5), (editor, 35)])
        XCTAssertEqual(closed.count, 1)
        XCTAssertEqual(closed.first?.endedAt, at(5))
        XCTAssertEqual(builder.finish(at: at(40)).first?.startedAt, at(35))
    }

    func testStoppingDuringAShortVisitReportsBothApps() {
        var builder = IntervalBuilder()
        _ = feed(&builder, [(editor, 0), (browser, 10)])
        let intervals = builder.finish(at: at(12))
        XCTAssertEqual(intervals.map(\.bundleID), [editor, browser])
        XCTAssertEqual(intervals.map(\.endedAt), [at(10), at(12)])
    }

    func testSingleSightingStoppedAtOnceProducesNoZeroLengthInterval() {
        var builder = IntervalBuilder()
        _ = feed(&builder, [(editor, 0)])
        XCTAssertTrue(builder.finish(at: start).isEmpty)
    }

    // MARK: Checkpoint

    private func ticks(_ bundleID: String, from first: TimeInterval, through last: TimeInterval) -> [(String, TimeInterval)] {
        stride(from: first, through: last, by: 5).map { (bundleID, $0) }
    }

    func testIntervalOpenForLessThanTheCheckpointIntervalIsLeftAlone() {
        var builder = IntervalBuilder()
        _ = feed(&builder, ticks(editor, from: 0, through: IntervalBuilder.checkpointInterval - 5))
        XCTAssertTrue(builder.checkpoint().isEmpty)
    }

    func testCheckpointClosesTheOpenIntervalAtTheLastSightingAndContinuesFromThere() {
        var builder = IntervalBuilder()
        let limit = IntervalBuilder.checkpointInterval
        _ = feed(&builder, [(editor, 0), (browser, 5), (editor, 10)] + ticks(editor, from: 15, through: limit))
        let closed = builder.checkpoint()
        XCTAssertEqual(closed.map(\.bundleID), [editor])
        XCTAssertEqual(closed.first?.startedAt, start)
        XCTAssertEqual(closed.first?.endedAt, at(limit))
        XCTAssertEqual(closed.first?.switchCount, 1)

        let rest = builder.finish(at: at(limit + 5))
        XCTAssertEqual(rest.map(\.bundleID), [editor])
        XCTAssertEqual(rest.first?.startedAt, at(limit))
        XCTAssertEqual(rest.first?.endedAt, at(limit + 5))
        XCTAssertEqual(rest.first?.switchCount, 0)
    }

    func testCheckpointWaitsWhileAnotherAppIsInFrontSoTheInterruptedIntervalCanStillBeResumed() {
        var builder = IntervalBuilder()
        let limit = IntervalBuilder.checkpointInterval
        _ = feed(&builder, ticks(editor, from: 0, through: limit) + [(browser, limit + 5)])
        XCTAssertTrue(builder.checkpoint().isEmpty)
        _ = feed(&builder, [(editor, limit + 10)])
        XCTAssertEqual(builder.checkpoint().first?.switchCount, 1)
    }

    func testHourInOneAppIsCutIntoContiguousIntervalsNoLongerThanTheCheckpointInterval() {
        var builder = IntervalBuilder()
        var closed: [ActivityInterval] = []
        for second in stride(from: 0.0, through: 3600, by: 5) {
            closed += builder.record(AppSighting(bundleID: editor, date: at(second)))
            closed += builder.checkpoint()
        }
        closed += builder.finish(at: at(3600))
        XCTAssertGreaterThan(closed.count, 1)
        XCTAssertEqual(closed.first?.startedAt, start)
        XCTAssertEqual(closed.last?.endedAt, at(3600))
        for (earlier, later) in zip(closed, closed.dropFirst()) {
            XCTAssertEqual(earlier.endedAt, later.startedAt)
        }
        for interval in closed {
            XCTAssertLessThanOrEqual(interval.endedAt.timeIntervalSince(interval.startedAt), IntervalBuilder.checkpointInterval)
        }
    }
}
