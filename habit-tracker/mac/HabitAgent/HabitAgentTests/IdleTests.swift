// [review:need-review] PHASE-03/172
// summary: verifies the checkpoint cutting only on fresh input (swept over the moment of the last input), the adaptive sampling period, idle_seconds inside an interval, closing at the last input after a long absence or at sleep and lock, and that nothing is queued while collection is paused
import XCTest
@testable import HabitAgent

final class IdlePeriodTests: XCTestCase {
    func testPeriodIsFiveSecondsUpToAMinuteOfIdleAndThirtyAfterIt() {
        XCTAssertEqual(IdleMonitor.samplingPeriod(idleSeconds: 0), 5)
        XCTAssertEqual(IdleMonitor.samplingPeriod(idleSeconds: IdleMonitor.idleThreshold), 5)
        XCTAssertEqual(IdleMonitor.samplingPeriod(idleSeconds: IdleMonitor.idleThreshold + 0.5), 30)
        XCTAssertEqual(IdleMonitor.samplingPeriod(idleSeconds: 3600), 30)
    }

    func testPeriodReturnsToFiveSecondsAtTheFirstInput() {
        XCTAssertEqual(IdleMonitor.samplingPeriod(idleSeconds: 240), 30)
        XCTAssertEqual(IdleMonitor.samplingPeriod(idleSeconds: 0.2), 5)
    }

    func testTheIdleSamplingPeriodStaysInsideTheSilenceWindow() {
        XCTAssertLessThan(IdleMonitor.idlePeriod, IntervalBuilder.silenceWindow)
    }
}

final class IdleIntervalTests: XCTestCase {
    private let start = Date(timeIntervalSince1970: 1_800_000_000)
    private let editor = "com.example.editor"

    private func at(_ seconds: TimeInterval) -> Date { start.addingTimeInterval(seconds) }

    private func sighting(_ seconds: TimeInterval, idle: TimeInterval = 0) -> AppSighting {
        AppSighting(bundleID: editor, date: at(seconds), idleSeconds: idle)
    }

    /// Work at the active period from 0 up to `quiet`, input at every sighting.
    private func work(_ builder: inout IntervalBuilder, until quiet: TimeInterval) {
        for second in stride(from: 0.0, through: quiet, by: IdleMonitor.activePeriod) {
            _ = builder.record(sighting(second))
        }
    }

    /// Typing until `quiet`, then nothing until `back`: the idle reading grows with the clock.
    private func feedPause(_ builder: inout IntervalBuilder, quiet: TimeInterval, back: TimeInterval) -> [ActivityInterval] {
        var closed: [ActivityInterval] = []
        var now = quiet
        while now < back {
            let idle = now - quiet
            closed += builder.record(sighting(now, idle: idle))
            now += IdleMonitor.samplingPeriod(idleSeconds: idle)
        }
        return closed
    }

    func testSightingsAtTheIdlePeriodStayOneInterval() {
        var builder = IntervalBuilder()
        var closed = builder.record(sighting(0))
        for second in stride(from: 30.0, through: 300, by: IdleMonitor.idlePeriod) {
            closed += builder.record(sighting(second, idle: 100))
        }
        XCTAssertTrue(closed.isEmpty)
        XCTAssertEqual(builder.finish(at: at(300)).count, 1)
    }

    func testIdleSecondsMatchThePauseInsideTheIntervalWithinOnePeriod() {
        var builder = IntervalBuilder()
        work(&builder, until: 55)
        // Input stops at 60 and comes back at 250; the idle sampling period is 30 seconds.
        XCTAssertTrue(feedPause(&builder, quiet: 60, back: 250).isEmpty)
        _ = builder.record(sighting(270, idle: 20))
        let interval = builder.finish(at: at(275)).first
        XCTAssertEqual(interval?.startedAt, start)
        let actualPause = 190.0
        XCTAssertGreaterThan(interval?.idleSeconds ?? 0, 0)
        XCTAssertLessThanOrEqual(abs(Double(interval?.idleSeconds ?? 0) - actualPause), IdleMonitor.idlePeriod)
    }

    func testAShortPauseUnderTheThresholdIsNotIdle() {
        var builder = IntervalBuilder()
        _ = builder.record(sighting(0))
        for second in stride(from: 5.0, through: 55, by: 5) {
            _ = builder.record(sighting(second, idle: second))
        }
        XCTAssertEqual(builder.finish(at: at(60)).first?.idleSeconds, 0)
    }

    func testAbsenceBeyondTenMinutesClosesTheIntervalAtTheLastInput() {
        var builder = IntervalBuilder()
        work(&builder, until: 55)
        let closed = feedPause(&builder, quiet: 60, back: 60 + IdleMonitor.awayThreshold + 60)
        XCTAssertEqual(closed.count, 1)
        XCTAssertEqual(closed.first?.startedAt, start)
        XCTAssertEqual(closed.first?.endedAt, at(60))
        XCTAssertEqual(closed.first?.idleSeconds, 0, "the absence after the last input is not part of the interval")
        XCTAssertTrue(builder.finish(at: at(5000)).isEmpty, "nothing stays open while the person is away")
    }

    func testThePersonComingBackOpensAFreshIntervalAtThatMoment() {
        var builder = IntervalBuilder()
        _ = builder.record(sighting(0))
        _ = feedPause(&builder, quiet: 10, back: 10 + IdleMonitor.awayThreshold + 60)
        XCTAssertTrue(builder.record(sighting(2400, idle: 0)).isEmpty)
        let interval = builder.finish(at: at(2410)).first
        XCTAssertEqual(interval?.startedAt, at(2400))
        XCTAssertEqual(interval?.endedAt, at(2410))
    }

    func testFinishAtTheLastInputClosesThereAndNotAtTheMomentOfSleep() {
        var builder = IntervalBuilder()
        work(&builder, until: 95)
        _ = feedPause(&builder, quiet: 100, back: 400)
        let closed = builder.finish(at: at(400), lastInput: at(100))
        XCTAssertEqual(closed.count, 1)
        XCTAssertEqual(closed.first?.endedAt, at(100))
        XCTAssertEqual(closed.first?.idleSeconds, 0)
    }

    func testFinishWithoutLastInputKeepsTheOldEndOfTheInterval() {
        var builder = IntervalBuilder()
        _ = builder.record(sighting(0))
        _ = builder.record(sighting(5))
        XCTAssertEqual(builder.finish(at: at(8)).first?.endedAt, at(8))
    }
}

final class CheckpointDuringPauseTests: XCTestCase {
    private let start = Date(timeIntervalSince1970: 1_800_000_000)
    private let editor = "com.example.editor"

    private func at(_ seconds: TimeInterval) -> Date { start.addingTimeInterval(seconds) }

    /// Work up to `quiet`, then silence; every sighting is followed by the checkpoint, as the sampler does.
    private func run(quiet: TimeInterval, until end: TimeInterval) -> [ActivityInterval] {
        var builder = IntervalBuilder()
        var closed: [ActivityInterval] = []
        var now = 0.0
        while now < end {
            let idle = max(0, now - quiet)
            closed += builder.record(AppSighting(bundleID: editor, date: at(now), idleSeconds: idle))
            closed += builder.checkpoint()
            now += IdleMonitor.samplingPeriod(idleSeconds: idle)
        }
        return closed
    }

    func testCheckpointDoesNotCutWhileAPauseIsGoingOn() {
        var builder = IntervalBuilder()
        for second in stride(from: 0.0, through: 100, by: 5) {
            _ = builder.record(AppSighting(bundleID: editor, date: at(second)))
        }
        // Input stopped at 100; the pause counts from 160 on, and the interval passes the checkpoint age at 310.
        for second in stride(from: 130.0, through: 400, by: IdleMonitor.idlePeriod) {
            _ = builder.record(AppSighting(bundleID: editor, date: at(second), idleSeconds: second - 100))
            XCTAssertTrue(builder.checkpoint().isEmpty, "the time after the last input must not leave as work")
        }
    }

    /// The moment of the last input is swept over a grid, so a checkpoint that lands on any second of a pause is met.
    static let lastInputGrid = stride(from: 300.0, through: 1500, by: 5)
    /// A sampler writes a queue file per pass, so its sweep covers one checkpoint cycle (300 s) instead.
    static let lastInputGridOfOneCycle = stride(from: 300.0, through: 600, by: 5)

    func testNoLastInputMomentLetsTheCheckpointSendTheTimeAfterItAsWork() {
        for quiet in Self.lastInputGrid {
            let closed = run(quiet: quiet, until: quiet + 40 * 60)
            let end = closed.map(\.endedAt).max()
            XCTAssertEqual(end?.timeIntervalSince(start) ?? -1, quiet, accuracy: IdleMonitor.activePeriod, "last input at \(quiet) s")
            XCTAssertLessThanOrEqual(end ?? .distantFuture, at(quiet), "last input at \(quiet) s")
        }
    }

    func testAbsenceAfterTwelveMinutesOfWorkEndsTheLastIntervalAtTheLastInput() {
        let quiet = 720.0
        let closed = run(quiet: quiet, until: quiet + 40 * 60)
        XCTAssertEqual(closed.last?.endedAt, at(quiet))
        XCTAssertEqual(closed.first?.startedAt, start)
        for (earlier, later) in zip(closed, closed.dropFirst()) {
            XCTAssertEqual(earlier.endedAt, later.startedAt)
        }
        let worked = closed.reduce(0) { $0 + $1.endedAt.timeIntervalSince($1.startedAt) }
        XCTAssertEqual(worked, quiet, "40 minutes away are not work time")
    }
}

@MainActor
final class PowerObserverTests: XCTestCase {
    private var changes: [Bool] = []

    private func makeObserver() -> PowerObserver {
        changes = []
        return PowerObserver { [unowned self] paused in changes.append(paused) }
    }

    func testSleepPausesAndWakeResumes() {
        let observer = makeObserver()
        observer.handle(.willSleep)
        observer.handle(.didWake)
        XCTAssertEqual(changes, [true, false])
    }

    func testLockedScreenKeepsCollectionPausedUntilUnlockEvenAfterTheDisplayWakes() {
        let observer = makeObserver()
        observer.handle(.screenLocked)
        observer.handle(.screensDidSleep)
        observer.handle(.screensDidWake)
        XCTAssertTrue(observer.isPaused)
        observer.handle(.screenUnlocked)
        XCTAssertEqual(changes, [true, false])
    }

    func testAnotherPauseReasonWhilePausedDoesNotNotifyAgain() {
        let observer = makeObserver()
        observer.handle(.screensDidSleep)
        observer.handle(.willSleep)
        observer.handle(.didWake)
        XCTAssertTrue(observer.isPaused)
        observer.handle(.screensDidWake)
        XCTAssertEqual(changes, [true, false])
    }
}

@MainActor
final class SamplerPauseTests: XCTestCase {
    private let start = Date(timeIntervalSince1970: 1_800_000_000)
    private let editor = "com.example.editor"
    private var directory: URL!
    private var idleReading: TimeInterval = 0

    override func setUp() async throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("idle-\(UUID().uuidString)")
        idleReading = 0
    }

    override func tearDown() async throws {
        try? FileManager.default.removeItem(at: directory)
    }

    private func at(_ seconds: TimeInterval) -> Date { start.addingTimeInterval(seconds) }

    private func makeSampler() -> ActivitySampler {
        let sampler = ActivitySampler(queueDirectory: directory, idle: IdleMonitor { [unowned self] in idleReading })
        // No server address, so a closed interval is queued and nothing leaves the test.
        sampler.serverAddress = ""
        _ = sampler.openQueue()
        return sampler
    }

    func testALockedScreenQueuesNoIntervalsAndTheOpenOneEndsAtTheLastInput() throws {
        let sampler = makeSampler()
        for second in stride(from: 0.0, through: 60, by: 5) {
            sampler.sample(bundleID: editor, at: at(second), idle: 0)
        }
        idleReading = 20
        sampler.setPaused(true, now: at(80))

        let queued = try XCTUnwrap(sampler.store?.nextBatch()).intervals
        XCTAssertEqual(queued.map(\.endedAt), [at(60)])
        XCTAssertEqual(queued.count, 1)

        for second in stride(from: 85.0, through: 28_000, by: 600) {
            sampler.sample(bundleID: editor, at: at(second), idle: second - 60)
        }
        sampler.setPaused(true, now: at(28_100))
        XCTAssertEqual(sampler.store?.count, 1, "nothing is queued while the screen is locked")
    }

    func testCollectionResumesAfterUnlockWithoutRestartingTheAgent() throws {
        let sampler = makeSampler()
        sampler.sample(bundleID: editor, at: at(0), idle: 0)
        sampler.sample(bundleID: editor, at: at(5), idle: 0)
        sampler.setPaused(true, now: at(10))
        sampler.setPaused(false, now: at(500))
        XCTAssertFalse(sampler.isPaused)

        sampler.sample(bundleID: editor, at: at(505), idle: 0)
        sampler.sample(bundleID: editor, at: at(510), idle: 0)
        XCTAssertEqual(sampler.store?.count, 1)
        sampler.setPaused(true, now: at(512))
        XCTAssertEqual(sampler.store?.count, 2)
    }

    /// Typing until `quiet`, then no input: the idle reading grows with the clock, the period follows it.
    private func work(_ sampler: ActivitySampler, until quiet: TimeInterval, away: TimeInterval) {
        var now = 0.0
        while now < quiet + away {
            let idle = max(0, now - quiet)
            sampler.sample(bundleID: editor, at: at(now), idle: idle)
            now += IdleMonitor.samplingPeriod(idleSeconds: idle)
        }
    }

    private func queuedEnds(_ sampler: ActivitySampler) throws -> [Date] {
        try XCTUnwrap(sampler.store?.nextBatch()).intervals.map(\.endedAt)
    }

    func testNoLastInputMomentLetsALockSendTheTimeAfterItAsWork() throws {
        for quiet in CheckpointDuringPauseTests.lastInputGridOfOneCycle {
            try runWithFreshSampler { sampler in
                work(sampler, until: quiet, away: 180)
                idleReading = 180
                sampler.setPaused(true, now: at(quiet + 180))
                let end = try XCTUnwrap(try queuedEnds(sampler).max(), "last input at \(quiet) s")
                XCTAssertLessThanOrEqual(end, at(quiet), "last input at \(quiet) s")
                XCTAssertEqual(end.timeIntervalSince(start), quiet, accuracy: IdleMonitor.activePeriod, "last input at \(quiet) s")
            }
        }
    }

    func testNoLastInputMomentLetsTheAwayRuleSendTheTimeAfterItAsWork() throws {
        for quiet in CheckpointDuringPauseTests.lastInputGridOfOneCycle {
            try runWithFreshSampler { sampler in
                work(sampler, until: quiet, away: IdleMonitor.awayThreshold + 60)
                let end = try XCTUnwrap(try queuedEnds(sampler).max(), "last input at \(quiet) s")
                XCTAssertLessThanOrEqual(end, at(quiet), "last input at \(quiet) s")
                XCTAssertEqual(end.timeIntervalSince(start), quiet, accuracy: IdleMonitor.activePeriod, "last input at \(quiet) s")
            }
        }
    }

    /// A sampler on its own queue directory, so each pass of a sweep starts empty.
    private func runWithFreshSampler(_ body: (ActivitySampler) throws -> Void) throws {
        let previous = directory
        directory = FileManager.default.temporaryDirectory.appendingPathComponent("idle-\(UUID().uuidString)")
        defer {
            try? FileManager.default.removeItem(at: directory)
            directory = previous
        }
        try body(makeSampler())
    }

    func testFortyMinutesAwayWithoutALockEndTheLastIntervalAtTheLastInput() throws {
        let sampler = makeSampler()
        let quiet = 12.0 * 60
        // 40 minutes of absence: the ten-minute rule closes the interval on its own.
        work(sampler, until: quiet, away: 40 * 60)
        let ends = try queuedEnds(sampler)
        XCTAssertEqual(ends.last, at(quiet))
        XCTAssertEqual(ends.max(), at(quiet), "nothing reaches past the last input")
    }

    func testPausingTenMinutesAfterTheLastInputEndsTheLastIntervalAtTheLastInput() throws {
        let sampler = makeSampler()
        let quiet = 12.0 * 60
        work(sampler, until: quiet, away: IdleMonitor.awayThreshold - 5)
        idleReading = IdleMonitor.awayThreshold
        sampler.setPaused(true, now: at(quiet + IdleMonitor.awayThreshold))
        let ends = try queuedEnds(sampler)
        XCTAssertEqual(ends.last, at(quiet))
        XCTAssertEqual(ends.max(), at(quiet))
    }

    func testAStalePauseWithoutAWakeNotificationEndsOnFreshInput() {
        let sampler = makeSampler()
        sampler.sample(bundleID: editor, at: at(0), idle: 0)
        idleReading = 300
        sampler.setPaused(true, now: at(300))

        sampler.resumeIfPauseIsStale(screenLocked: false)
        XCTAssertTrue(sampler.isPaused, "no fresh input yet")

        idleReading = 1
        sampler.resumeIfPauseIsStale(screenLocked: true)
        XCTAssertTrue(sampler.isPaused, "a locked screen stays paused however fresh the input")

        sampler.resumeIfPauseIsStale(screenLocked: false)
        XCTAssertFalse(sampler.isPaused)
    }

    func testStopClosesTheOpenIntervalAtTheLastInput() async throws {
        let sampler = makeSampler()
        let now = Date()
        for second in stride(from: -130.0, through: -10, by: 5) {
            sampler.sample(bundleID: editor, at: now.addingTimeInterval(second), idle: 0)
        }
        idleReading = 40
        await sampler.stop()
        let end = try XCTUnwrap(try queuedEnds(sampler).last)
        XCTAssertEqual(end.timeIntervalSince(now), -40, accuracy: 1)
    }
}
