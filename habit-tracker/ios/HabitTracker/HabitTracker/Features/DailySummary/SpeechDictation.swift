// [review:need-review] PHASE-01/213
// summary: dictation seam of the day-summary screen — the SpeechDictating protocol the view model talks to, and the system implementation on SFSpeechRecognizer (on-device when the recognizer supports it) fed by AVAudioEngine
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
}

/// A microphone that turns speech into text. The view model owns the text; this only reports it.
@MainActor
protocol SpeechDictating: AnyObject {
    /// Asks for speech recognition and the microphone, in that order. Safe to call every time:
    /// the system prompts once and remembers the answer.
    func requestAccess() async -> SpeechAccess
    /// Starts listening. Every element is the whole phrase heard so far, not a delta.
    /// The stream ends after `stop()` (once the last result arrived) or on a failure.
    func start() throws -> AsyncThrowingStream<String, Error>
    func stop()
}

/// `SFSpeechRecognizer` over `AVAudioEngine`. The real microphone and the permission prompts only
/// exist on a device; tests fake `SpeechDictating` and only check how the request is configured.
@MainActor
final class SystemSpeechRecognizer: SpeechDictating {
    nonisolated static let defaultLocale = Locale(identifier: "ru-RU")
    /// How long `stop()` waits for the recognizer's last result before it gives up on it.
    private static let finalResultGrace: Duration = .seconds(3)

    private let recognizer: SFSpeechRecognizer?
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var continuation: AsyncThrowingStream<String, Error>.Continuation?
    private var session = 0
    private var isStopping = false

    init(locale: Locale = SystemSpeechRecognizer.defaultLocale) {
        recognizer = SFSpeechRecognizer(locale: locale)
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
        guard let recognizer, recognizer.isAvailable else { return .unavailable }
        return .granted
    }

    func start() throws -> AsyncThrowingStream<String, Error> {
        guard let recognizer else { throw SpeechDictationError.unavailable }
        teardown()
        session += 1
        isStopping = false

        let audioSession = AVAudioSession.sharedInstance()
        try audioSession.setCategory(.record, mode: .measurement, options: .duckOthers)
        try audioSession.setActive(true, options: .notifyOthersOnDeactivation)

        let request = Self.makeRequest(supportsOnDevice: recognizer.supportsOnDeviceRecognition)
        let input = engine.inputNode
        input.installTap(onBus: 0, bufferSize: 1024, format: input.outputFormat(forBus: 0)) { buffer, _ in
            request.append(buffer)
        }
        do {
            engine.prepare()
            try engine.start()
        } catch {
            input.removeTap(onBus: 0)
            try? audioSession.setActive(false, options: .notifyOthersOnDeactivation)
            throw error
        }
        self.request = request

        let current = session
        return AsyncThrowingStream { continuation in
            self.continuation = continuation
            self.task = recognizer.recognitionTask(with: request) { [weak self] result, error in
                if let result {
                    continuation.yield(result.bestTranscription.formattedString)
                }
                let finished = result?.isFinal == true || error != nil
                guard finished else { return }
                Task { @MainActor [weak self] in
                    guard let self, self.session == current else { return }
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
        engine.stop()
        engine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        let current = session
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: Self.finalResultGrace)
            guard let self, self.session == current, self.continuation != nil else { return }
            self.continuation?.finish()
            self.teardown()
        }
    }

    private func teardown() {
        if engine.isRunning {
            engine.stop()
            engine.inputNode.removeTap(onBus: 0)
        }
        task?.cancel()
        task = nil
        request = nil
        continuation = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
}
