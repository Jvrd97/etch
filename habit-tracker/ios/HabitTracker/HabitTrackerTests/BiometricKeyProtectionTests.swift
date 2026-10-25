// [review:need-review] PHASE-01/214
// summary: tests for the protected API key item and the Settings switch — a refused Face ID or a failed re-save never erases the key
import LocalAuthentication
import XCTest
@testable import HabitTracker

@MainActor
final class BiometricKeyProtectionTests: XCTestCase {
    private static let suite = "com.habittracker.tests.protection"
    private let keychain = KeychainStore(service: "com.habittracker.tests.protection")
    private var defaults: UserDefaults!
    private var authenticator: FakeAuthenticator!
    private var session: BiometricSession!

    override func setUpWithError() throws {
        try super.setUpWithError()
        defaults = UserDefaults(suiteName: Self.suite)
        defaults.removePersistentDomain(forName: Self.suite)
        authenticator = FakeAuthenticator()
        session = BiometricSession()
        try keychain.delete(SettingsViewModel.apiKeyKeychainKey)
    }

    override func tearDownWithError() throws {
        defaults.removePersistentDomain(forName: Self.suite)
        try keychain.delete(SettingsViewModel.apiKeyKeychainKey)
        try super.tearDownWithError()
    }

    private func makeViewModel() -> SettingsViewModel {
        SettingsViewModel(
            keychain: keychain,
            defaults: defaults,
            session: MockURLProtocol.makeSession(),
            authenticator: authenticator,
            biometricSession: session
        )
    }

    func testEnablingProtectsTheKeyAndKeepsItReadable() async throws {
        try keychain.save("secret", for: SettingsViewModel.apiKeyKeychainKey)
        let viewModel = makeViewModel()

        await viewModel.setFaceIDLock(true)

        XCTAssertTrue(viewModel.faceIDLockEnabled)
        XCTAssertTrue(LockSettings(defaults: defaults).isEnabled)
        XCTAssertNotNil(session.authenticatedContext, "the unlocked period must carry the evaluated context")
        XCTAssertEqual(try keychain.read(SettingsViewModel.apiKeyKeychainKey, context: session.readContext()), "secret")
    }

    func testRefusedFaceIDLeavesTheSwitchOffAndTheKeyIntact() async throws {
        try keychain.save("secret", for: SettingsViewModel.apiKeyKeychainKey)
        authenticator.result = .failure(.failed)
        let viewModel = makeViewModel()

        await viewModel.setFaceIDLock(true)

        XCTAssertFalse(viewModel.faceIDLockEnabled)
        XCTAssertFalse(LockSettings(defaults: defaults).isEnabled)
        XCTAssertNotNil(viewModel.lockMessage)
        XCTAssertEqual(try keychain.read(SettingsViewModel.apiKeyKeychainKey), "secret")
    }

    func testDisablingAfterRefusedFaceIDKeepsTheLockOn() async throws {
        try keychain.save("secret", for: SettingsViewModel.apiKeyKeychainKey)
        let viewModel = makeViewModel()
        await viewModel.setFaceIDLock(true)

        authenticator.result = .failure(.cancelled)
        await viewModel.setFaceIDLock(false)

        XCTAssertTrue(viewModel.faceIDLockEnabled)
        XCTAssertEqual(try keychain.read(SettingsViewModel.apiKeyKeychainKey, context: session.readContext()), "secret")
    }

    func testDisablingRestoresPlainKeyAndEndsTheSession() async throws {
        try keychain.save("secret", for: SettingsViewModel.apiKeyKeychainKey)
        let viewModel = makeViewModel()
        await viewModel.setFaceIDLock(true)

        await viewModel.setFaceIDLock(false)

        XCTAssertFalse(viewModel.faceIDLockEnabled)
        XCTAssertNil(session.authenticatedContext)
        XCTAssertEqual(try keychain.read(SettingsViewModel.apiKeyKeychainKey), "secret")
    }

    func testEnablingWithoutAStoredKeyOnlyTurnsTheFlagOn() async {
        let viewModel = makeViewModel()

        await viewModel.setFaceIDLock(true)

        XCTAssertTrue(viewModel.faceIDLockEnabled)
        XCTAssertNil(viewModel.lockMessage)
    }

    func testPasscodeChoiceIsAskedWithPasscodePolicyAndStored() async throws {
        try keychain.save("secret", for: SettingsViewModel.apiKeyKeychainKey)
        let viewModel = makeViewModel()
        await viewModel.setFaceIDLock(true)

        await viewModel.setPasscodeFallback(true)

        XCTAssertEqual(authenticator.allowPasscodeCalls, [false, true])
        XCTAssertTrue(viewModel.passcodeFallbackEnabled)
        XCTAssertEqual(LockSettings(defaults: defaults).keyProtection, .biometryOrPasscode)
        XCTAssertEqual(try keychain.read(SettingsViewModel.apiKeyKeychainKey, context: session.readContext()), "secret")
    }

    func testSavingSettingsKeepsTheKeyProtectedWhileTheLockIsOn() async throws {
        let viewModel = makeViewModel()
        await viewModel.setFaceIDLock(true)
        viewModel.apiKey = "typed-after"

        try viewModel.saveSettings()

        XCTAssertEqual(try keychain.read(SettingsViewModel.apiKeyKeychainKey, context: session.readContext()), "typed-after")
    }
}
