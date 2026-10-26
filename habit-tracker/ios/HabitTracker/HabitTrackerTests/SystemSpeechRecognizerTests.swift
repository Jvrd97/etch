// [review:need-review] PHASE-01/213
// summary: tests for SystemSpeechRecognizer over faked microphone, audio session and recognition backend — a restart after the system stopped the engine never installs a second tap, stop and failures release the session, a call or a route change ends the stream with .interrupted, results flow and an error after stop is not reported
import AVFoundation
import Speech
import XCTest
@testable import HabitTracker

@MainActor
private final class FakeAudioInput: AudioInput {
    private(set) var tapInstalled = false
    private(set) var installs = 0
    /// A second tap on the same bus traps in the real engine; here it is only counted.
    private(set) var installsOverATap = 0
    var isRunning = false
    var startError: Error?

    func installTap(_ onBuffer: @escaping @Sendable (AVAudioPCMBuffer) -> Void) {
        if tapInstalled { installsOverATap += 1 }
        tapInstalled = true
        installs += 1
    }

    func removeTap() { tapInstalled = false }

    func start() throws {
        if let startError { throw startError }
        isRunning = true
    }

    func stop() { isRunning = false }

    /// A call or a route change: the engine stops and the tap stays.
    func systemStopsEngine() { isRunning = false }
}

@MainActor
private final class FakeAudioSession: AudioSessionControlling {
    private(set) var activations = 0
    private(set) var deactivations = 0
    func activate() throws { activations += 1 }
    func deactivate() { deactivations += 1 }
}

private final class FakeBackend: RecognitionBackend, @unchecked Sendable {
    var isAvailable = true
    var supportsOnDevice = true
    private(set) var handler: (@Sendable (String?, Bool, Error?) -> Void)?
    private(set) var cancels = 0

    func startTask(
        request: SFSpeechAudioBufferRecognitionRequest,
        handler: @escaping @Sendable (String?, Bool, Error?) -> Void
    ) -> () -> Void {
        self.handler = handler
        return { [unowned self] in cancels += 1 }
    }

    func emit(_ text: String?, final: Bool = false, error: Error? = nil) {
        handler?(text, final, error)
    }
}

@MainActor
final class SystemSpeechRecognizerTests: XCTestCase {
    private struct Boom: Error {}

    private struct Rig {
        let recognizer: SystemSpeechRecognizer
        fileprivate let input: FakeAudioInput
        fileprivate let session: FakeAudioSession
        fileprivate let backend: FakeBackend
        let notifications: NotificationCenter
    }

    private func makeRig() -> Rig {
        let input = FakeAudioInput()
        let session = FakeAudioSession()
        let backend = FakeBackend()
        let notifications = NotificationCenter()
        let recognizer = SystemSpeechRecognizer(
            backend: backend, input: input, session: session, notifications: notifications
        )
        return Rig(recognizer: recognizer, input: input, session: session, backend: backend, notifications: notifications)
    }

    private func collect(_ stream: AsyncThrowingStream<String, Error>) async -> (phrases: [String], error: Error?) {
        var phrases: [String] = []
        do {
            for try await phrase in stream { phrases.append(phrase) }
            return (phrases, nil)
        } catch {
            return (phrases, error)
        }
    }

    func testRestartAfterTheSystemStoppedTheEngineDoesNotInstallASecondTap() throws {
        let rig = makeRig()
        _ = try rig.recognizer.start()
        rig.input.systemStopsEngine()

        _ = try rig.recognizer.start()

        XCTAssertEqual(rig.input.installs, 2)
        XCTAssertEqual(rig.input.installsOverATap, 0)
        XCTAssertTrue(rig.input.tapInstalled)
        XCTAssertTrue(rig.input.isRunning)
    }

    func testStopRemovesTheTapAndReleasesTheAudioSessionAtOnce() throws {
        let rig = makeRig()
        _ = try rig.recognizer.start()
        let before = rig.session.deactivations

        rig.recognizer.stop()

        XCTAssertEqual(rig.session.deactivations, before + 1)
        XCTAssertFalse(rig.input.tapInstalled)
        XCTAssertFalse(rig.input.isRunning)
    }

    func testAnEngineThatFailsToStartLeavesNothingBehind() {
        let rig = makeRig()
        rig.input.startError = Boom()
        XCTAssertThrowsError(try rig.recognizer.start())
        XCTAssertFalse(rig.input.tapInstalled)
        XCTAssertGreaterThanOrEqual(rig.session.deactivations, 1)
        XCTAssertEqual(rig.session.activations, 1)
    }

    func testAMissingRecognizerIsReportedAsUnavailable() {
        let recognizer = SystemSpeechRecognizer(
            backend: nil, input: FakeAudioInput(), session: FakeAudioSession(), notifications: NotificationCenter()
        )
        XCTAssertThrowsError(try recognizer.start()) {
            XCTAssertEqual($0 as? SpeechDictationError, .unavailable)
        }
    }

    func testACallEndsTheStreamAsInterruptedAndFreesTheMicrophone() async throws {
        let rig = makeRig()
        let stream = try rig.recognizer.start()

        rig.notifications.post(
            name: AVAudioSession.interruptionNotification, object: nil,
            userInfo: [AVAudioSessionInterruptionTypeKey: AVAudioSession.InterruptionType.began.rawValue]
        )
        let result = await collect(stream)

        XCTAssertEqual(result.error as? SpeechDictationError, .interrupted)
        XCTAssertFalse(rig.input.tapInstalled)
        XCTAssertEqual(rig.backend.cancels, 1)
        XCTAssertGreaterThanOrEqual(rig.session.deactivations, 1)
    }

    func testARouteChangeEndsTheStreamAsInterrupted() async throws {
        let rig = makeRig()
        let stream = try rig.recognizer.start()

        rig.notifications.post(name: .AVAudioEngineConfigurationChange, object: nil)
        let result = await collect(stream)

        XCTAssertEqual(result.error as? SpeechDictationError, .interrupted)
    }

    func testSpeakingAgainAfterACallStartsCleanly() async throws {
        let rig = makeRig()
        let first = try rig.recognizer.start()
        rig.notifications.post(name: .AVAudioEngineConfigurationChange, object: nil)
        _ = await collect(first)

        _ = try rig.recognizer.start()

        XCTAssertEqual(rig.input.installsOverATap, 0)
        XCTAssertTrue(rig.input.isRunning)
    }

    func testPartialResultsFlowAndTheFinalOneEndsTheStream() async throws {
        let rig = makeRig()
        let stream = try rig.recognizer.start()
        rig.backend.emit("съел")
        rig.backend.emit("съел борщ", final: true)

        let result = await collect(stream)

        XCTAssertEqual(result.phrases, ["съел", "съел борщ"])
        XCTAssertNil(result.error)
    }

    func testAnErrorAfterStopIsTheRecognizerClosingNotAFault() async throws {
        let rig = makeRig()
        let stream = try rig.recognizer.start()
        rig.backend.emit("съел борщ")
        rig.recognizer.stop()
        rig.backend.emit(nil, error: Boom())

        let result = await collect(stream)

        XCTAssertEqual(result.phrases, ["съел борщ"])
        XCTAssertNil(result.error)
    }

    func testAnErrorWhileListeningIsReported() async throws {
        let rig = makeRig()
        let stream = try rig.recognizer.start()
        rig.backend.emit(nil, error: Boom())

        let result = await collect(stream)

        XCTAssertNotNil(result.error)
    }
}
