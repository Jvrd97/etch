// [review:need-review] PHASE-01/214
// summary: unit tests for the app lock — launch state, timeout after background, failed and cancelled Face ID, one prompt at a time; the authenticator is a fake
import LocalAuthentication
import XCTest
@testable import HabitTracker

@MainActor
final class FakeAuthenticator: BiometricAuthenticating {
    var result: Result<Void, BiometricFailure> = .success(())
    private(set) var allowPasscodeCalls: [Bool] = []
    /// Suspends `authenticate` until `release()`, to hold a prompt open.
    var holdsPrompt = false
    private var continuation: CheckedContinuation<Void, Never>?

    func authenticate(reason: String, allowPasscode: Bool) async throws -> LAContext {
        allowPasscodeCalls.append(allowPasscode)
        if holdsPrompt {
            await withCheckedContinuation { continuation = $0 }
        }
        try result.get()
        return LAContext()
    }

    func release() {
        continuation?.resume()
        continuation = nil
    }
}

@MainActor
final class LockControllerTests: XCTestCase {
    private static let suite = "com.habittracker.tests.lock"
    private var defaults: UserDefaults!
    private var authenticator: FakeAuthenticator!
    private var session: BiometricSession!
    private var clock: Date!

    override func setUp() {
        super.setUp()
        defaults = UserDefaults(suiteName: Self.suite)
        defaults.removePersistentDomain(forName: Self.suite)
        authenticator = FakeAuthenticator()
        session = BiometricSession()
        clock = Date(timeIntervalSince1970: 1_000_000)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: Self.suite)
        super.tearDown()
    }

    private func makeController(enabled: Bool = true, passcode: Bool = false) -> AppLockController {
        let settings = LockSettings(defaults: defaults)
        settings.isEnabled = enabled
        settings.allowsPasscode = passcode
        return AppLockController(
            settings: settings,
            authenticator: authenticator,
            session: session,
            now: { [unowned self] in self.clock }
        )
    }

    func testLaunchIsLockedWhenEnabled() {
        XCTAssertTrue(makeController(enabled: true).isLocked)
    }

    func testLaunchIsOpenWhenDisabled() {
        XCTAssertFalse(makeController(enabled: false).isLocked)
    }

    func testUnlockSuccessOpensAndKeepsAuthenticatedContext() async {
        let controller = makeController()

        await controller.unlock()

        XCTAssertFalse(controller.isLocked)
        XCTAssertNil(controller.message)
        XCTAssertNotNil(session.authenticatedContext)
    }

    func testFailedAuthenticationStaysLockedWithMessageAndNoContext() async {
        authenticator.result = .failure(.failed)
        let controller = makeController()

        await controller.unlock()

        XCTAssertTrue(controller.isLocked)
        XCTAssertNotNil(controller.message)
        XCTAssertNil(session.authenticatedContext)
    }

    func testCancelledAuthenticationStaysLockedAndAsksToRetry() async {
        authenticator.result = .failure(.cancelled)
        let controller = makeController()

        await controller.unlock()

        XCTAssertTrue(controller.isLocked)
        XCTAssertEqual(controller.message, BiometricFailure.cancelled.userMessage)
    }

    func testRetryAfterFailureCanUnlock() async {
        authenticator.result = .failure(.failed)
        let controller = makeController()
        await controller.unlock()

        authenticator.result = .success(())
        await controller.unlock()

        XCTAssertFalse(controller.isLocked)
        XCTAssertNil(controller.message)
    }

    func testPasscodeChoiceIsPassedToTheAuthenticator() async {
        await makeController(passcode: false).unlock()
        await makeController(passcode: true).unlock()
        XCTAssertEqual(authenticator.allowPasscodeCalls, [false, true])
    }

    func testUnlockWhenAlreadyOpenDoesNotPrompt() async {
        let controller = makeController(enabled: false)
        await controller.unlock()
        XCTAssertTrue(authenticator.allowPasscodeCalls.isEmpty)
    }

    func testSecondUnlockWhilePromptIsOpenDoesNotPromptAgain() async {
        authenticator.holdsPrompt = true
        let controller = makeController()
        let first = Task { await controller.unlock() }
        await Task.yield()

        await controller.unlock()
        authenticator.release()
        await first.value

        XCTAssertEqual(authenticator.allowPasscodeCalls.count, 1)
        XCTAssertFalse(controller.isLocked)
    }

    func testShortBackgroundKeepsTheAppOpen() async {
        let controller = makeController()
        await controller.unlock()

        controller.sceneDidEnterBackground()
        clock = clock.addingTimeInterval(AppLockController.lockTimeout - 1)
        controller.sceneDidBecomeActive()

        XCTAssertFalse(controller.isLocked)
        XCTAssertNotNil(session.authenticatedContext)
    }

    func testLongBackgroundLocksAndDropsTheContext() async {
        let controller = makeController()
        await controller.unlock()

        controller.sceneDidEnterBackground()
        clock = clock.addingTimeInterval(AppLockController.lockTimeout + 1)
        controller.sceneDidBecomeActive()

        XCTAssertTrue(controller.isLocked)
        XCTAssertNil(session.authenticatedContext)
    }

    func testLongBackgroundDoesNotLockWhenDisabled() {
        let controller = makeController(enabled: false)

        controller.sceneDidEnterBackground()
        clock = clock.addingTimeInterval(AppLockController.lockTimeout * 10)
        controller.sceneDidBecomeActive()

        XCTAssertFalse(controller.isLocked)
    }

    func testActivatingWithoutPriorBackgroundDoesNotLock() async {
        let controller = makeController()
        await controller.unlock()

        controller.sceneDidBecomeActive()

        XCTAssertFalse(controller.isLocked)
    }

    func testLockSettingsMapToKeyProtection() {
        let settings = LockSettings(defaults: defaults)
        XCTAssertEqual(settings.keyProtection, .none)
        settings.isEnabled = true
        XCTAssertEqual(settings.keyProtection, .biometry)
        settings.allowsPasscode = true
        XCTAssertEqual(settings.keyProtection, .biometryOrPasscode)
        settings.isEnabled = false
        XCTAssertEqual(settings.keyProtection, .none)
    }
}
