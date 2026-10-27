// [review:need-review] PHASE-01/213, PHASE-03/227, PHASE-03/230
// summary: dictation seam of the day-summary screen — the SpeechDictating protocol the view model talks to, and the system implementation on SFSpeechRecognizer (on-device when the recognizer supports it) fed by a fresh AVAudioEngine per session; the tap is removed unconditionally, the audio session is released on stop, and a call, a route change of its own engine or a reset of the media services ends the stream with .interrupted (never after an ordinary stop); an input started before any tap gave it an engine throws .unavailable instead of pretending to listen
import AVFoundation
import Foundation
import Speech

/// What the person allowed. Anything but `granted` leaves the screen usable by typing.
enum SpeechAccess: Equatable {
    case granted
    case speechDenied
    case microphoneDenied
    /// No recognizer for the language, or the system cannot recognize right now.
    case unavailable
}

enum SpeechDictationError: Error, Equatable {
    case unavailable
    /// A call, another app taking the microphone, or a route change stopped the engine.
    case interrupted
}

/// A microphone that turns speech into text. The view model owns the text; this only reports it.
@MainActor
protocol SpeechDictating: AnyObject {
    /// Asks for speech recognition and the microphone, in that order. Safe to call every time:
    /// the system prompts once and remembers the answer.
    func requestAccess() async -> SpeechAccess
    /// Starts listening. Every element is the whole phrase heard so far, not a delta.
    /// The stream ends after `stop()` (once the last result arrived), or throws on a failure
    /// (`SpeechDictationError.interrupted` when the system took the microphone away).
    func start() throws -> AsyncThrowingStream<String, Error>
    func stop()
}

// MARK: - Seams under the system recognizer

/// The microphone tap. `removeTap` is always safe to call: the system stops the engine itself on
/// a call or a route change and leaves the tap behind, and a second tap on the same bus traps.
@MainActor
protocol AudioInput: AnyObject {
    /// The object whose `AVAudioEngineConfigurationChange` is ours: the system posts it for every
    /// engine in the process, and another engine's route change is not a reason to stop dictating.
    var configurationChangeSource: AnyObject? { get }
    /// Starts a session on a fresh engine: one the media services reset left behind is dead.
    func installTap(_ onBuffer: @escaping @Sendable (AVAudioPCMBuffer) -> Void)
    func removeTap()
    func start() throws
    func stop()
}

@MainActor
protocol AudioSessionControlling: AnyObject {
    func activate() throws
    func deactivate()
}

/// One running recognition: results come back through the handler on any queue.
protocol RecognitionBackend: AnyObject {
    var isAvailable: Bool { get }
    var supportsOnDevice: Bool { get }
    /// Returns the closure that cancels the task.
    func startTask(
        request: SFSpeechAudioBufferRecognitionRequest,
        handler: @escaping @Sendable (_ text: String?, _ isFinal: Bool, _ error: Error?) -> Void
    ) -> @Sendable () -> Void
}

final class SFRecognitionBackend: RecognitionBackend {
    private let recognizer: SFSpeechRecognizer

    init?(locale: Locale) {
        guard let recognizer = SFSpeechRecognizer(locale: locale) else { return nil }
        self.recognizer = recognizer
    }

    var isAvailable: Bool { recognizer.isAvailable }
    var supportsOnDevice: Bool { recognizer.supportsOnDeviceRecognition }

    func startTask(
        request: SFSpeechAudioBufferRecognitionRequest,
        handler: @escaping @Sendable (String?, Bool, Error?) -> Void
    ) -> @Sendable () -> Void {
        let task = recognizer.recognitionTask(with: request) { result, error in
            handler(result?.bestTranscription.formattedString, result?.isFinal ?? false, error)
        }
        return { task.cancel() }
    }
}

@MainActor
final class EngineAudioInput: AudioInput {
    /// Created per session in `installTap`: building one up front would open an `inputNode` that is
    /// never used.
    private var engine: AVAudioEngine?

    var configurationChangeSource: AnyObject? { engine }

    func installTap(_ onBuffer: @escaping @Sendable (AVAudioPCMBuffer) -> Void) {
        engine?.inputNode.removeTap(onBus: 0)
        let engine = AVAudioEngine()
        self.engine = engine
        let input = engine.inputNode
        input.installTap(onBus: 0, bufferSize: 1024, format: input.outputFormat(forBus: 0)) { buffer, _ in
            onBuffer(buffer)
        }
    }

    func removeTap() {
        engine?.inputNode.removeTap(onBus: 0)
    }

    /// Without a tap there is no engine: starting nothing would report a session that never hears.
    func start() throws {
        guard let engine else { throw SpeechDictationError.unavailable }
        engine.prepare()
        try engine.start()
    }

    func stop() {
        engine?.stop()
    }
}

@MainActor
final class SystemAudioSession: AudioSessionControlling {
    func activate() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .measurement, options: .duckOthers)
        try session.setActive(true, options: .notifyOthersOnDeactivation)
    }

    /// Hands the audio back, so music that was ducked for the microphone resumes.
    func deactivate() {
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
}

// MARK: - System implementation

/// `SFSpeechRecognizer` over `AVAudioEngine`. The real microphone and the permission prompts only
/// exist on a device; tests drive this class through the seams above.
@MainActor
final class SystemSpeechRecognizer: SpeechDictating {
    nonisolated static let defaultLocale = Locale(identifier: "ru-RU")
    /// How long `stop()` waits for the recognizer's last result before it gives up on it.
    private static let finalResultGrace: Duration = .seconds(3)

    private let backend: RecognitionBackend?
    private let input: AudioInput
    private let session: AudioSessionControlling
    private let notifications: NotificationCenter
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var cancelTask: (@Sendable () -> Void)?
    private var continuation: AsyncThrowingStream<String, Error>.Continuation?
    private var observers: [NSObjectProtocol] = []
    private var generation = 0
    private var isStopping = false

    init(
        backend: RecognitionBackend? = SFRecognitionBackend(locale: SystemSpeechRecognizer.defaultLocale),
        input: AudioInput? = nil,
        session: AudioSessionControlling? = nil,
        notifications: NotificationCenter = .default
    ) {
        self.backend = backend
        self.input = input ?? EngineAudioInput()
        self.session = session ?? SystemAudioSession()
        self.notifications = notifications
    }

    /// Audio stays on the phone whenever the recognizer can do it on the phone.
    nonisolated static func makeRequest(supportsOnDevice: Bool) -> SFSpeechAudioBufferRecognitionRequest {
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.requiresOnDeviceRecognition = supportsOnDevice
        return request
    }

    func requestAccess() async -> SpeechAccess {
        let speech = await withCheckedContinuation { (answer: CheckedContinuation<SFSpeechRecognizerAuthorizationStatus, Never>) in
            SFSpeechRecognizer.requestAuthorization { answer.resume(returning: $0) }
        }
        guard speech == .authorized else { return .speechDenied }
        guard await AVAudioApplication.requestRecordPermission() else { return .microphoneDenied }
        guard let backend, backend.isAvailable else { return .unavailable }
        return .granted
    }

    func start() throws -> AsyncThrowingStream<String, Error> {
        guard let backend else { throw SpeechDictationError.unavailable }
        teardown()
        generation += 1
        isStopping = false

        try session.activate()
        let request = Self.makeRequest(supportsOnDevice: backend.supportsOnDevice)
        input.installTap { request.append($0) }
        do {
            try input.start()
        } catch {
            input.removeTap()
            session.deactivate()
            throw error
        }
        self.request = request
        // After installTap: the engine behind `configurationChangeSource` exists only from then on.
        observeInterruptions(generation: generation)

        let current = generation
        return AsyncThrowingStream { continuation in
            self.continuation = continuation
            self.cancelTask = backend.startTask(request: request) { [weak self] text, isFinal, error in
                if let text {
                    continuation.yield(text)
                }
                guard isFinal || error != nil else { return }
                Task { @MainActor [weak self] in
                    guard let self, self.generation == current else { return }
                    // A failure after stop() is the recognizer closing, not a fault to report.
                    if let error, !self.isStopping {
                        continuation.finish(throwing: error)
                    } else {
                        continuation.finish()
                    }
                    self.teardown()
                }
            }
        }
    }

    func stop() {
        guard request != nil, !isStopping else { return }
        isStopping = true
        input.stop()
        input.removeTap()
        request?.endAudio()
        // Nothing more is recorded, so the microphone goes back now: the final result needs no session.
        session.deactivate()
        let current = generation
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: Self.finalResultGrace)
            guard let self, self.generation == current, self.continuation != nil else { return }
            self.continuation?.finish()
            self.teardown()
        }
    }

    /// A call, Siri, another app or an unplugged headset: end the stream so the screen can say so.
    private func observeInterruptions(generation current: Int) {
        let began: @Sendable (Notification) -> Bool = { note in
            guard let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt else { return false }
            return AVAudioSession.InterruptionType(rawValue: raw) == .began
        }
        observers = [
            notifications.addObserver(
                forName: AVAudioSession.interruptionNotification, object: nil, queue: .main
            ) { [weak self] note in
                guard began(note) else { return }
                Task { @MainActor in self?.interrupt(generation: current) }
            },
            notifications.addObserver(
                forName: .AVAudioEngineConfigurationChange, object: input.configurationChangeSource, queue: .main
            ) { [weak self] _ in
                Task { @MainActor in self?.interrupt(generation: current) }
            },
            notifications.addObserver(
                forName: AVAudioSession.mediaServicesWereResetNotification, object: nil, queue: .main
            ) { [weak self] _ in
                Task { @MainActor in self?.interrupt(generation: current) }
            },
        ]
    }

    /// An ordinary stop is already winding down: a notification that arrives in its last seconds
    /// must not turn the final phrase into a fault. A signal queued for an earlier session must not
    /// end the next one.
    private func interrupt(generation signalled: Int) {
        guard signalled == generation, let continuation, !isStopping else { return }
        continuation.finish(throwing: SpeechDictationError.interrupted)
        teardown()
    }

    private func teardown() {
        for observer in observers {
            notifications.removeObserver(observer)
        }
        observers = []
        input.stop()
        // Unconditional: the system may have stopped the engine itself and left the tap behind.
        input.removeTap()
        cancelTask?()
        cancelTask = nil
        request = nil
        continuation = nil
        session.deactivate()
    }
}
